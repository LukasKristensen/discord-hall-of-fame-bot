ALLOWED_COLUMNS = {
    "hall_of_fame_channel_id",
    "reaction_threshold",
    "post_due_date",
    "sweep_limit",
    "sweep_limited",
    "include_author_in_reaction_calculation",
    "allow_messages_in_hof_channel",
    "custom_emoji_check_logic",
    "whitelisted_emojis",
    "leaderboard_setup",
    "ignore_bot_messages",
    "reaction_count_calculation_method",
    "hide_hof_post_below_threshold"
}

def create_server_config_table(cursor):
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_configs (
                guild_id BIGINT PRIMARY KEY,
                hall_of_fame_channel_id BIGINT,
                reaction_threshold INT DEFAULT 5,
                post_due_date INT DEFAULT 30,
                sweep_limit INT DEFAULT 100,
                sweep_limited BOOLEAN DEFAULT TRUE,
                include_author_in_reaction_calculation BOOLEAN DEFAULT TRUE,
                allow_messages_in_hof_channel BOOLEAN DEFAULT TRUE,
                custom_emoji_check_logic BOOLEAN DEFAULT FALSE,
                whitelisted_emojis TEXT[],
                leaderboard_setup BOOLEAN DEFAULT FALSE,
                ignore_bot_messages BOOLEAN DEFAULT FALSE,
                reaction_count_calculation_method VARCHAR(50) DEFAULT 'most_reactions_on_emoji',
                hide_hof_post_below_threshold BOOLEAN DEFAULT TRUE
            )
        """
    )

def update_server_config_param(db_connection, guild_id, param_name, param_value):
    if param_name not in ALLOWED_COLUMNS:
        raise ValueError("Invalid column name")

    cursor = db_connection.cursor()
    query = f"UPDATE server_configs SET {param_name} = ? WHERE guild_id = ?"
    cursor.execute(query, (param_value, guild_id))
    db_connection.commit()
    cursor.close()

def setup_database(db_connection):
    cursor = db_connection.cursor()
    create_server_config_table(cursor)
    db_connection.commit()
    cursor.close()
