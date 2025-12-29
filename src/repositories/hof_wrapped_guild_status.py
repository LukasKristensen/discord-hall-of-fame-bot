def create_hof_wrapped_progress_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hof_wrapped_progress (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            year INTEGER NOT NULL,
            is_complete BOOLEAN DEFAULT FALSE,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, year)
        )
    """)
    connection.commit()
    cursor.close()

def mark_hof_wrapped_as_processed(connection, guild_id, year):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO hof_wrapped_progress (guild_id, year, is_complete, last_updated)
        VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP)
        ON CONFLICT (guild_id, year) DO UPDATE SET
            is_complete = TRUE,
            last_updated = CURRENT_TIMESTAMP
    """, (guild_id, year))
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