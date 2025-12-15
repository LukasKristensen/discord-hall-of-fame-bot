def create_hall_of_fame_message_table(cursor):
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

def check_if_message_id_exists(cursor, message_id):
    cursor.execute("SELECT 1 FROM hall_of_fame_message WHERE message_id = %s", (message_id,))
    return cursor.fetchone() is not None

def insert_hall_of_fame_message(cursor, message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id,
                                created_at, video_link_message_id=None):
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

def delete_hall_of_fame_messages_for_guild(cursor, guild_id):
    cursor.execute("""
        DELETE FROM hall_of_fame_message 
        WHERE guild_id = %s
    """, (guild_id,))

def setup_database(connection):
    cursor = connection.cursor()
    create_hall_of_fame_message_table(cursor)
    connection.commit()
    cursor.close()