def create_server_user_table(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS server_user (
            user_id BIGINT NOT NULL,
            guild_id BIGINT NOT NULL,
            monthly_reaction_rank INTEGER,
            total_message_rank INTEGER,
            total_reaction_rank INTEGER,
            this_month_hall_of_fame_messages INTEGER,
            total_hall_of_fame_messages INTEGER,
            monthly_message_rank INTEGER,
            this_month_hall_of_fame_message_reactions INTEGER,
            total_hall_of_fame_message_reactions INTEGER,
            PRIMARY KEY (user_id, guild_id)
        )
        """
    )
    cursor.execute("ALTER TABLE server_user DROP CONSTRAINT IF EXISTS server_user_pkey CASCADE;")
    cursor.execute("ALTER TABLE server_user ADD PRIMARY KEY (user_id, guild_id);")
    connection.commit()
    cursor.close()

def insert_server_user(connection, user_id, guild_id, monthly_reaction_rank,
                       total_message_rank, total_reaction_rank, this_month_hall_of_fame_messages,
                       total_hall_of_fame_messages, monthly_message_rank,
                       this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO server_user 
        (user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
         this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
         this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
          this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
          this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions))
    connection.commit()
    cursor.close()

def delete_server_users(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM server_user 
        WHERE guild_id = %s
    """, (guild_id,))
    connection.commit()
    cursor.close()

def get_server_user(connection, user_id, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT *
        FROM server_user
        WHERE user_id = %s AND guild_id = %s
    """, (user_id, guild_id))
    row = cursor.fetchone()
    if row is not None:
        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))
    else:
        result = None
    cursor.close()
    return result

def update_user_stats(connection, stats, user_id, guild_id):
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO server_user (
            user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
            this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
            this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id, guild_id) DO UPDATE SET
            total_hall_of_fame_messages = excluded.total_hall_of_fame_messages,
            this_month_hall_of_fame_messages = excluded.this_month_hall_of_fame_messages,
            total_hall_of_fame_message_reactions = excluded.total_hall_of_fame_message_reactions,
            this_month_hall_of_fame_message_reactions = excluded.this_month_hall_of_fame_message_reactions,
            total_message_rank = excluded.total_message_rank,
            monthly_message_rank = excluded.monthly_message_rank,
            total_reaction_rank = excluded.total_reaction_rank,
            monthly_reaction_rank = excluded.monthly_reaction_rank
        """,
        (
            user_id,
            guild_id,
            stats["monthly_reaction_rank"],
            stats["total_message_rank"],
            stats["total_reaction_rank"],
            stats["this_month_hall_of_fame_messages"],
            stats["total_hall_of_fame_messages"],
            stats["monthly_message_rank"],
            stats["this_month_hall_of_fame_message_reactions"],
            stats["total_hall_of_fame_message_reactions"],
        ),
    )
    connection.commit()
    cursor.close()


def rebuild_user_stats_for_guild(connection, guild_id, monthly_window_start) -> int:
    """
    Recompute every member's hall of fame totals and ranks for one guild in a single statement.

    Counting and ranking happen in Postgres so that the guild's whole hall of fame history stays in
    the database. Reading it into the bot cost time proportional to all history ever recorded, every
    day, rather than to what actually changed.

    Ranks are assigned with ROW_NUMBER, so every member gets a distinct position and members on equal
    counts are ordered by user id. Swap it for RANK if tied members should share a position instead.

    :param connection: The database connection
    :param guild_id: The guild to recompute
    :param monthly_window_start: Naive UTC timestamp the monthly counters reach back to
    :return: The number of members whose stats were written
    """
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO server_user (
            user_id, guild_id,
            total_hall_of_fame_messages, this_month_hall_of_fame_messages,
            total_hall_of_fame_message_reactions, this_month_hall_of_fame_message_reactions,
            total_message_rank, monthly_message_rank,
            total_reaction_rank, monthly_reaction_rank
        )
        SELECT
            author_id,
            %(guild_id)s,
            total_messages,
            monthly_messages,
            total_reactions,
            monthly_reactions,
            ROW_NUMBER() OVER (ORDER BY total_messages DESC, author_id),
            ROW_NUMBER() OVER (ORDER BY monthly_messages DESC, author_id),
            ROW_NUMBER() OVER (ORDER BY total_reactions DESC, author_id),
            ROW_NUMBER() OVER (ORDER BY monthly_reactions DESC, author_id)
        FROM (
            SELECT
                author_id,
                COUNT(*) AS total_messages,
                COALESCE(SUM(reaction_count), 0) AS total_reactions,
                COUNT(*) FILTER (WHERE created_at >= %(monthly_window_start)s) AS monthly_messages,
                COALESCE(SUM(reaction_count) FILTER (WHERE created_at >= %(monthly_window_start)s), 0)
                    AS monthly_reactions
            FROM hall_of_fame_message
            WHERE guild_id = %(guild_id)s
              AND author_id IS NOT NULL
              AND created_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM server_configs WHERE server_configs.guild_id = %(guild_id)s)
            GROUP BY author_id
        ) AS totals
        ON CONFLICT (user_id, guild_id) DO UPDATE SET
            total_hall_of_fame_messages = EXCLUDED.total_hall_of_fame_messages,
            this_month_hall_of_fame_messages = EXCLUDED.this_month_hall_of_fame_messages,
            total_hall_of_fame_message_reactions = EXCLUDED.total_hall_of_fame_message_reactions,
            this_month_hall_of_fame_message_reactions = EXCLUDED.this_month_hall_of_fame_message_reactions,
            total_message_rank = EXCLUDED.total_message_rank,
            monthly_message_rank = EXCLUDED.monthly_message_rank,
            total_reaction_rank = EXCLUDED.total_reaction_rank,
            monthly_reaction_rank = EXCLUDED.monthly_reaction_rank
    """, {"guild_id": guild_id, "monthly_window_start": monthly_window_start})
    written = cursor.rowcount
    connection.commit()
    cursor.close()
    return written


ALLOWED_STAT_FIELDS = {
    "monthly_reaction_rank",
    "total_message_rank",
    "total_reaction_rank",
    "this_month_hall_of_fame_messages",
    "total_hall_of_fame_messages",
    "monthly_message_rank",
    "this_month_hall_of_fame_message_reactions",
    "total_hall_of_fame_message_reactions",
}


def get_top_users_by_stat(connection, guild_id, stat_field, limit=10):
    if stat_field not in ALLOWED_STAT_FIELDS:
        raise ValueError(f"Invalid stat_field: {stat_field}")
    cursor = connection.cursor()
    query = f"""
        SELECT user_id, guild_id, {stat_field}
        FROM server_user
        WHERE guild_id = %s
        ORDER BY {stat_field} DESC
        LIMIT %s
    """
    cursor.execute(query, (guild_id, limit))
    columns = [desc[0] for desc in cursor.description]
    results = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    return results


def check_if_user_is_top_of_stat(connection, user_id, guild_id, stat_field):
    """
    Returns True if the given user is currently #1 for the specified stat field within the guild.
    """
    if stat_field not in ALLOWED_STAT_FIELDS:
        raise ValueError(f"Invalid stat_field: {stat_field}")
    cursor = connection.cursor()
    query = f"""
        SELECT user_id
        FROM server_user
        WHERE guild_id = %s
        ORDER BY {stat_field} DESC
        LIMIT 1
    """
    cursor.execute(query, (guild_id,))
    row = cursor.fetchone()
    cursor.close()
    return row is not None and row[0] == user_id