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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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