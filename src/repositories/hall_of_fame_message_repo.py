def create_hall_of_fame_message_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hall_of_fame_message (
            message_id BIGINT PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            guild_id BIGINT NOT NULL,
            hall_of_fame_message_id BIGINT,
            reaction_count INTEGER NOT NULL,
            author_id BIGINT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            video_link_message_id BIGINT
        )
    """)
    # The table is keyed by message, but nearly every read is by guild: the daily stats rebuild, the
    # leaderboard and the daily post limit checked on every reaction. Without this each of them scans
    # every guild's history. created_at comes second so the "posted today" and monthly windows are
    # served from the index too. IF NOT EXISTS makes it a one-off build on the existing table
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS hall_of_fame_message_guild_created_idx
        ON hall_of_fame_message (guild_id, created_at)
    """)
    # /my_data, /delete_my_data and the global profile read one member's posts across every guild.
    # Without this each of them scans the whole table, and psycopg2 holds the event loop while it does
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS hall_of_fame_message_author_idx
        ON hall_of_fame_message (author_id)
    """)
    connection.commit()
    cursor.close()

def check_if_message_id_exists(cursor, message_id):
    cursor.execute("SELECT 1 FROM hall_of_fame_message WHERE message_id = %s", (message_id,))
    return cursor.fetchone() is not None

def insert_hall_of_fame_message(connection, message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id,
                                created_at, video_link_message_id=None):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO hall_of_fame_message 
        (message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, created_at, video_link_message_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (message_id) DO UPDATE SET
            channel_id=EXCLUDED.channel_id,
            guild_id=EXCLUDED.guild_id,
            hall_of_fame_message_id=EXCLUDED.hall_of_fame_message_id,
            reaction_count=EXCLUDED.reaction_count,
            author_id=EXCLUDED.author_id,
            created_at=EXCLUDED.created_at,
            video_link_message_id=EXCLUDED.video_link_message_id
    """, (message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, created_at, video_link_message_id))
    connection.commit()
    cursor.close()

def delete_hall_of_fame_messages_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM hall_of_fame_message 
        WHERE guild_id = %s
    """, (guild_id,))
    connection.commit()
    cursor.close()

def get_all_hall_of_fame_messages_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hall_of_fame_message
        WHERE guild_id = %s
    """, (guild_id,))
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    return results

def find_hall_of_fame_message(connection, guild_id, channel_id, message_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hall_of_fame_message 
        WHERE guild_id = %s AND channel_id = %s AND message_id = %s
    """, (guild_id, channel_id, message_id))
    row = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    cursor.close()
    return dict(zip(columns, row)) if row else None

def guild_message_count_today(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
            SELECT COUNT(*) FROM hall_of_fame_message 
            WHERE guild_id = %s 
            AND created_at >= DATE_TRUNC('day', NOW())
        """, (guild_id,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result else 0

ALLOWED_UPDATE_FIELDS = {
    "hall_of_fame_message_id",
    "reaction_count",
    "video_link_message_id",
    "author_id",
    "created_at",
    "channel_id",
    "guild_id",
}

def update_field_for_message(connection, guild_id, channel_id, message_id, field_name, field_value):
    if field_name not in ALLOWED_UPDATE_FIELDS:
        raise ValueError(f"Unsupported field_name: {field_name}")

    cursor = connection.cursor()
    query = f"""
        UPDATE hall_of_fame_message
        SET {field_name} = %s
        WHERE guild_id = %s AND channel_id = %s AND message_id = %s
    """
    cursor.execute(query, (field_value, guild_id, channel_id, message_id))
    connection.commit()
    cursor.close()

def find_members_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT DISTINCT author_id FROM hall_of_fame_message 
        WHERE guild_id = %s
    """, (guild_id,))
    rows = cursor.fetchall()
    cursor.close()
    return [row[0] for row in rows]

def find_top_messages_by_reaction_count(connection, guild_id, limit=10):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hall_of_fame_message 
        WHERE guild_id = %s 
        ORDER BY reaction_count DESC 
        LIMIT %s
    """, (guild_id, limit))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    cursor.close()
    return [dict(zip(columns, row)) for row in rows]

def get_post_activity(connection, guild_id) -> dict:
    """
    How busy a server's board is, for /check_setup. One query, served from the guild and created_at index
    :return: total posts, the time of the latest (None without posts) and the posts made today
    """
    cursor = connection.cursor()
    cursor.execute("""
        SELECT COUNT(*), MAX(created_at),
               COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('day', NOW()))
        FROM hall_of_fame_message
        WHERE guild_id = %s
    """, (guild_id,))
    row = cursor.fetchone()
    cursor.close()
    if not row:
        return {"total": 0, "latest": None, "today": 0}
    return {"total": row[0] or 0, "latest": row[1], "today": row[2] or 0}

def count_messages_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM hall_of_fame_message 
        WHERE guild_id = %s
    """, (guild_id,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result else 0

def get_monthly_message_counts_by_guild(connection, month_start, month_end):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT guild_id, COUNT(*) AS message_count
        FROM hall_of_fame_message
        WHERE created_at >= %s AND created_at < %s
        GROUP BY guild_id
        ORDER BY message_count DESC
        """,
        (month_start, month_end),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [{"guild_id": row[0], "message_count": row[1]} for row in rows]

# Posts whose author is unknown or removed. The stats rebuild already skips it, which is what lets
# /delete_my_data take a member off every leaderboard without deleting the server's posts
NO_AUTHOR_ID = 0

def get_messages_by_author(connection, author_id) -> list[dict]:
    """
    Every featured post by one member, across every guild, for /my_data
    :param connection: The database connection
    :param author_id: The member's user ID
    :return: One dict per post, oldest first
    """
    cursor = connection.cursor()
    cursor.execute("""
        SELECT guild_id, channel_id, message_id, hall_of_fame_message_id, reaction_count, created_at
        FROM hall_of_fame_message
        WHERE author_id = %s
        ORDER BY created_at
    """, (author_id,))
    columns = ["guild_id", "channel_id", "message_id", "hall_of_fame_message_id", "reaction_count", "created_at"]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    return results

def get_member_highlights(connection, guild_id, author_id) -> dict:
    """
    A member's best post and most recent feature in one guild, for the highlights on /user_profile
    :param connection: The database connection
    :param guild_id: The guild the profile is for
    :param author_id: The member's user ID
    :return: best_post as a dict with channel_id, message_id and reaction_count, and last_featured
        as a datetime, either one None when the member has nothing featured here
    """
    cursor = connection.cursor()
    cursor.execute("""
        SELECT channel_id, message_id, reaction_count
        FROM hall_of_fame_message
        WHERE guild_id = %s AND author_id = %s
        ORDER BY reaction_count DESC, created_at DESC
        LIMIT 1
    """, (guild_id, author_id))
    best = cursor.fetchone()
    cursor.execute("""
        SELECT MAX(created_at) FROM hall_of_fame_message
        WHERE guild_id = %s AND author_id = %s
    """, (guild_id, author_id))
    latest = cursor.fetchone()
    cursor.close()
    return {
        "best_post": dict(zip(("channel_id", "message_id", "reaction_count"), best)) if best else None,
        "last_featured": latest[0] if latest else None,
    }

def remove_author(connection, author_id) -> int:
    """
    Detach a member from every post they wrote. The posts stay on their servers' boards, since they
    belong to those servers, but nothing links them to the member any more
    :param connection: The database connection
    :param author_id: The member's user ID
    :return: The number of posts changed
    """
    cursor = connection.cursor()
    cursor.execute("UPDATE hall_of_fame_message SET author_id = %s WHERE author_id = %s",
                   (NO_AUTHOR_ID, author_id))
    changed = cursor.rowcount
    connection.commit()
    cursor.close()
    return changed
