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
        SELECT channel_id, message_id FROM hall_of_fame_message 
        WHERE guild_id = %s
    """, (guild_id,))
    results = cursor.fetchall()
    cursor.close()
    return results

def find_hall_of_fame_message(connection, guild_id, channel_id, message_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hall_of_fame_message 
        WHERE guild_id = %s AND channel_id = %s AND message_id = %s
    """, (guild_id, channel_id, message_id))
    result = cursor.fetchone()
    cursor.close()
    return result

def guild_message_count_past_24_hours(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM hall_of_fame_message 
        WHERE guild_id = %s AND created_at >= NOW() - INTERVAL '24 HOURS'
    """, (guild_id,))
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result else 0

def update_field_for_message(connection, guild_id, channel_id, message_id, field_name, field_value):
    cursor = connection.cursor()
    query = f"""
        UPDATE hall_of_fame_message 
        SET {field_name} = %s 
        WHERE guild_id = %s AND channel_id = %s AND message_id = %s
    """
    cursor.execute(query, (field_value, guild_id, channel_id, message_id))
    connection.commit()
    cursor.close()

def find_guild_ids_from_server(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT author_id FROM hall_of_fame_message
        WHERE guild_id = %s
    """, (guild_id,))
    results = cursor.fetchall()
    cursor.close()
    return results