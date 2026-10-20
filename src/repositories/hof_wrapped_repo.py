def create_hof_wrapped_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hof_wrapped (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            year INTEGER NOT NULL,
            reaction_count INTEGER,
            hof_message_posts INTEGER,
            most_used_channels TEXT,
            most_used_emojis TEXT,
            most_reacted_post_message_id BIGINT,
            most_reacted_post_channel_id BIGINT,
            most_reacted_post_reaction_count INTEGER,
            fan_of_users TEXT,
            users_fans TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, user_id, year),
            user_ranks TEXT
        )
    """)
    # The unique key starts with the guild, so looking a member up across guilds (/my_data and
    # deleting a member's data) would otherwise scan the whole table
    cursor.execute("CREATE INDEX IF NOT EXISTS hof_wrapped_user_idx ON hof_wrapped (user_id)")
    connection.commit()
    cursor.close()

def insert_hof_wrapped(connection, guild_id, user_id, year, reaction_count, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_message_id, most_reacted_post_channel_id, most_reacted_post_reaction_count, fan_of_users, users_fans, user_ranks):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO hof_wrapped (
            guild_id, user_id, year, reaction_count, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_message_id, most_reacted_post_channel_id, most_reacted_post_reaction_count, fan_of_users, users_fans, user_ranks
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (guild_id, user_id, year) DO UPDATE SET
            reaction_count=EXCLUDED.reaction_count,
            hof_message_posts=EXCLUDED.hof_message_posts,
            most_used_channels=EXCLUDED.most_used_channels,
            most_used_emojis=EXCLUDED.most_used_emojis,
            most_reacted_post_message_id=EXCLUDED.most_reacted_post_message_id,
            most_reacted_post_channel_id=EXCLUDED.most_reacted_post_channel_id,
            most_reacted_post_reaction_count=EXCLUDED.most_reacted_post_reaction_count,
            fan_of_users=EXCLUDED.fan_of_users,
            users_fans=EXCLUDED.users_fans,
            user_ranks=EXCLUDED.user_ranks,
            created_at=CURRENT_TIMESTAMP
    """,
    (guild_id, user_id, year, reaction_count, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_message_id, most_reacted_post_channel_id, most_reacted_post_reaction_count, fan_of_users, users_fans, user_ranks))
    connection.commit()
    cursor.close()

def get_hof_wrapped(connection, guild_id, user_id, year):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hof_wrapped WHERE guild_id = %s AND user_id = %s AND year = %s
    """, (guild_id, user_id, year))
    row = cursor.fetchone()
    if row is None:
        cursor.close()
        return None
    columns = [desc[0] for desc in cursor.description]
    result = dict(zip(columns, row))
    cursor.close()
    return result

def get_all_hof_wrapped_for_guild(connection, guild_id, year):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hof_wrapped WHERE guild_id = %s AND year = %s
    """, (guild_id, year))
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    return results

def delete_hof_wrapped_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM hof_wrapped WHERE guild_id = %s
    """, (guild_id,))
    connection.commit()
    cursor.close()

def get_hof_wrapped_for_user(connection, user_id) -> list[dict]:
    """
    Every Wrapped a member has, across guilds and years, for /my_data
    :param connection: The database connection
    :param user_id: The member's user ID
    :return: One dict per row, without the row's own serial ID
    """
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM hof_wrapped WHERE user_id = %s ORDER BY year, guild_id", (user_id,))
    columns = [desc[0] for desc in cursor.description]
    results = [{key: value for key, value in zip(columns, row) if key != "id"} for row in cursor.fetchall()]
    cursor.close()
    return results

def count_hof_wrapped_for_user(connection, user_id) -> int:
    """
    How many Wrapped rows a member has, across guilds and years, for the /my_data summary
    :param connection: The database connection
    :param user_id: The member's user ID
    :return: The number of rows
    """
    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM hof_wrapped WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else 0

def delete_hof_wrapped_for_user(connection, user_id, commit: bool = True) -> int:
    """
    Delete a member's own Wrapped rows, and take their ID out of everybody else's fan lists, where
    it is stored as a key of the JSON objects fan_of_users and users_fans
    :param connection: The database connection
    :param user_id: The member's user ID
    :param commit: False to leave the commit to the caller, as part of a larger transaction
    :return: The number of the member's own rows deleted
    """
    cursor = connection.cursor()
    cursor.execute("DELETE FROM hof_wrapped WHERE user_id = %s", (user_id,))
    deleted = cursor.rowcount
    key = str(user_id)
    # The LIKE narrows the update to rows that mention the member before any JSON is parsed. json.dumps
    # writes the integer keys as quoted strings, which is the form matched here
    pattern = f'%"{key}"%'
    for column in ("fan_of_users", "users_fans"):
        cursor.execute(f"""
            UPDATE hof_wrapped
            SET {column} = ({column}::jsonb - %s)::text
            WHERE {column} LIKE %s
        """, (key, pattern))
    if commit:
        connection.commit()
    cursor.close()
    return deleted

def check_if_guild_wrapped_data_exists(connection, guild_id, year):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT 1 FROM hof_wrapped WHERE guild_id = %s AND year = %s
    """, (guild_id, year))
    exists = cursor.fetchone() is not None
    cursor.close()
    return exists
