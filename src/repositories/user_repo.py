def create_user_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_user (
            user_id BIGINT PRIMARY KEY,
            guild_id BIGINT,
            username TEXT,
            avatar_url TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    cursor.close()

def get_user_by_id(connection, user_id, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT user_id, guild_id, username, avatar_url, last_updated
        FROM guild_user
        WHERE user_id = %s AND guild_id = %s
    """, (user_id, guild_id))
    result = cursor.fetchone()
    cursor.close()
    return result

def store_user_if_not_exists_or_stale(connection, member, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO guild_user (user_id, guild_id, username, avatar_url, last_updated)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE
        SET guild_id = EXCLUDED.guild_id,
            username = EXCLUDED.username,
            avatar_url = EXCLUDED.avatar_url,
            last_updated = NOW()
        WHERE guild_user.last_updated < NOW() - INTERVAL '30 days'
    """, (member.id, guild_id, str(member), str(member.avatar.url) if member.avatar else None))
    connection.commit()
    cursor.close()

def delete_users_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM guild_user 
        WHERE guild_id = %s
    """, (guild_id,))
    connection.commit()
    cursor.close()
