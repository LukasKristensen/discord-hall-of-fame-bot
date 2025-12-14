def create_server_config_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_config (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            hall_of_fame_message_id INTEGER,
            reaction_count INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            video_link_message_id INTEGER
        )
    """)

def check_if_message_id_exists(cursor, message_id):
    cursor.execute("SELECT 1 FROM server_config WHERE message_id = ?", (message_id,))
    return cursor.fetchone() is not None

def insert_hall_of_fame_message(cursor, message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id,
                                created_at, video_link_message_id=None):
    cursor.execute("""
        INSERT INTO server_config 
        (message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, created_at, video_link_message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, created_at, video_link_message_id))

def setup_database(connection):
    cursor = connection.cursor()
    create_server_config_table(cursor)
    connection.commit()
    cursor.close()