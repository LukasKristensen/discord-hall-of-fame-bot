def create_hof_wrapped_progress_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hof_wrapped_progress (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            year INTEGER NOT NULL,
            is_complete BOOLEAN DEFAULT FALSE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hall_of_fame_message_count INTEGER DEFAULT 0,
            duration_seconds FLOAT,
            UNIQUE(guild_id, year)
        )
    """)
    connection.commit()
    cursor.close()

def create_progress_entry(connection, guild_id, year, message_count):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO hof_wrapped_progress (guild_id, year, hall_of_fame_message_count)
        VALUES (%s, %s, %s)
        ON CONFLICT (guild_id, year) DO NOTHING
    """, (guild_id, year, message_count))
    connection.commit()
    cursor.close()

def mark_hof_wrapped_as_processed(connection, guild_id, year, duration_seconds):
    cursor = connection.cursor()
    cursor.execute("""
        UPDATE hof_wrapped_progress
        SET is_complete = TRUE,
            duration_seconds = %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE guild_id = %s AND year = %s
    """, (duration_seconds, guild_id, year))
    connection.commit()
    cursor.close()

def is_hof_wrapped_processed(connection, guild_id, year):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT is_complete FROM hof_wrapped_progress WHERE guild_id = %s AND year = %s
    """, (guild_id, year))
    row = cursor.fetchone()
    cursor.close()
    if row:
        return row[0]
    return False