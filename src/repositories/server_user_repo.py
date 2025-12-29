def create_server_user_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_user (
            user_id BIGINT PRIMARY KEY,
            guild_id BIGINT,
            monthly_reaction_rank INTEGER,
            total_message_rank INTEGER,
            total_reaction_rank INTEGER,
            this_month_hall_of_fame_messages INTEGER,
            total_hall_of_fame_messages INTEGER,
            monthly_message_rank INTEGER,
            this_month_hall_of_fame_message_reactions INTEGER,
            total_hall_of_fame_message_reactions INTEGER
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
    try:
        cursor.execute("""
            SELECT user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
                   this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
                   this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions
            FROM server_user
            WHERE user_id = %s AND guild_id = %s
        """, (user_id, guild_id))
        result = cursor.fetchone()
    except Exception as e:
        connection.rollback()
        print(f"Error fetching server user: {e}")
        raise
    finally:
        cursor.close()
    return result

def update_user_stats(connection, stats, user_id, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO server_user (
            user_id, guild_id, monthly_reaction_rank, total_message_rank, total_reaction_rank,
            this_month_hall_of_fame_messages, total_hall_of_fame_messages, monthly_message_rank,
            this_month_hall_of_fame_message_reactions, total_hall_of_fame_message_reactions
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id) DO UPDATE SET
            total_hall_of_fame_messages = excluded.total_hall_of_fame_messages,
            this_month_hall_of_fame_messages = excluded.this_month_hall_of_fame_messages,
            total_hall_of_fame_message_reactions = excluded.total_hall_of_fame_message_reactions,
            this_month_hall_of_fame_message_reactions = excluded.this_month_hall_of_fame_message_reactions,
            total_message_rank = excluded.total_message_rank,
            monthly_message_rank = excluded.monthly_message_rank,
            total_reaction_rank = excluded.total_reaction_rank,
            monthly_reaction_rank = excluded.monthly_reaction_rank,
            guild_id = excluded.guild_id
    """, (
        user_id, guild_id, stats["monthly_reaction_rank"], stats["total_message_rank"], stats["total_reaction_rank"],
        stats["this_month_hall_of_fame_messages"], stats["total_hall_of_fame_messages"], stats["monthly_message_rank"],
        stats["this_month_hall_of_fame_message_reactions"], stats["total_hall_of_fame_message_reactions"]
    ))
    connection.commit()
    cursor.close()

def get_top_users_by_stat(connection, guild_id, stat_field, limit=10):
    cursor = connection.cursor()
    query = f"""
        SELECT user_id, guild_id, {stat_field}
        FROM server_user
        WHERE guild_id = %s
        ORDER BY {stat_field} DESC
        LIMIT %s
    """
    cursor.execute(query, (guild_id, limit))
    results = cursor.fetchall()
    cursor.close()
    return results

def check_if_user_is_top_of_stat(connection, user_id, guild_id, stat_field):
    """
    Checks if the user is the ranked 1 in the specified stat field within the guild
    """
    cursor = connection.cursor()
    query = f"""
        SELECT user_id
        FROM server_user
        WHERE guild_id = %s
        ORDER BY {stat_field} DESC
        LIMIT 1
    """
    cursor.execute(query, (guild_id,))
    result = cursor.fetchone()
    cursor.close()
    return result is not None and result[0] == user_id