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