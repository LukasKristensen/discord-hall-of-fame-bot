from src.classes.server_class import ServerClass

ALLOWED_COLUMNS = {
    "hall_of_fame_channel_id",
    "reaction_threshold",
    "post_due_date",
    "leaderboard_message_ids",
    "sweep_limit",
    "sweep_limited",
    "include_author_in_reaction_calculation",
    "allow_messages_in_hof_channel",
    "custom_emoji_check_logic",
    "whitelisted_emojis",
    "leaderboard_setup",
    "ignore_bot_messages",
    "server_member_count",
    "reaction_count_calculation_method",
    "hide_hof_post_below_threshold"
}

def create_server_config_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_configs (
                guild_id BIGINT PRIMARY KEY,
                hall_of_fame_channel_id BIGINT,
                reaction_threshold INT DEFAULT 5,
                post_due_date INT DEFAULT 30,
                leaderboard_message_ids TEXT[],
                sweep_limit INT DEFAULT 100,
                sweep_limited BOOLEAN DEFAULT TRUE,
                include_author_in_reaction_calculation BOOLEAN DEFAULT TRUE,
                allow_messages_in_hof_channel BOOLEAN DEFAULT TRUE,
                custom_emoji_check_logic BOOLEAN DEFAULT FALSE,
                whitelisted_emojis TEXT[],
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                leaderboard_setup BOOLEAN DEFAULT FALSE,
                ignore_bot_messages BOOLEAN DEFAULT FALSE,
                server_member_count INT DEFAULT 0,
                reaction_count_calculation_method VARCHAR(50) DEFAULT 'most_reactions_on_emoji',
                hide_hof_post_below_threshold BOOLEAN DEFAULT TRUE
            )
        """
    )
    connection.commit()
    cursor.close()

def insert_server_with_parameters(connection, guild_id, hall_of_fame_channel_id, reaction_threshold,
                                  post_due_date, leaderboard_message_ids, sweep_limit, sweep_limited,
                                  include_author_in_reaction_calculation, allow_messages_in_hof_channel,
                                  custom_emoji_check_logic, whitelisted_emojis, joined_date, leaderboard_setup,
                                  ignore_bot_messages, server_member_count, reaction_count_calculation_method,
                                  hide_hof_post_below_threshold):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO server_configs (
            guild_id, hall_of_fame_channel_id, reaction_threshold, post_due_date, leaderboard_message_ids,
            sweep_limit, sweep_limited, include_author_in_reaction_calculation, allow_messages_in_hof_channel,
            custom_emoji_check_logic, whitelisted_emojis, joined_date, leaderboard_setup, ignore_bot_messages,
            server_member_count, reaction_count_calculation_method, hide_hof_post_below_threshold
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (guild_id) DO NOTHING;
        """, (guild_id, hall_of_fame_channel_id, reaction_threshold, post_due_date, leaderboard_message_ids,
              sweep_limit, sweep_limited, include_author_in_reaction_calculation, allow_messages_in_hof_channel,
              custom_emoji_check_logic, whitelisted_emojis, joined_date, leaderboard_setup, ignore_bot_messages,
              server_member_count, reaction_count_calculation_method, hide_hof_post_below_threshold))
    connection.commit()
    cursor.close()

def update_server_config_param(guild_id, param_name, param_value, connection):
    cursor = connection.cursor()
    if param_name not in ALLOWED_COLUMNS:
        raise ValueError("Invalid column name")
    query = f"UPDATE server_configs SET {param_name} = %s WHERE guild_id = %s"
    cursor.execute(query, (param_value, guild_id))
    connection.commit()
    cursor.close()

def get_parameter_value(connection, guild_id, param_name):
    cursor = connection.cursor()
    if param_name not in ALLOWED_COLUMNS:
        raise ValueError("Invalid column name")
    query = f"SELECT {param_name} FROM server_configs WHERE guild_id = %s"
    cursor.execute(query, (guild_id,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result else None

def insert_server_config(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO server_configs (guild_id)
        VALUES (%s)
        ON CONFLICT (guild_id) DO NOTHING;
    """, (guild_id,))
    connection.commit()
    cursor.close()

def check_if_guild_exists(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("SELECT 1 FROM server_configs WHERE guild_id = %s", (guild_id,))
    exists = cursor.fetchone() is not None
    cursor.close()
    return exists

def delete_server_config(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM server_configs 
        WHERE guild_id = %s
    """, (guild_id,))
    connection.commit()
    cursor.close()

def get_server_classes(connection) -> dict[int, ServerClass]:
    cursor = connection.cursor()
    cursor.execute("""
        SELECT hall_of_fame_channel_id, guild_id, reaction_threshold, post_due_date,
               sweep_limit, sweep_limited, include_author_in_reaction_calculation,
               allow_messages_in_hof_channel, custom_emoji_check_logic, whitelisted_emojis,
               leaderboard_setup, ignore_bot_messages, reaction_count_calculation_method,
               hide_hof_post_below_threshold
        FROM server_configs
    """)
    rows = cursor.fetchall()
    cursor.close()
    return {row[1]: ServerClass(*row) for row in rows}
