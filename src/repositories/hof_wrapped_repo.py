def create_hof_wrapped_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hof_wrapped (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            year INTEGER NOT NULL,
            reaction_count INTEGER,
            hof_message_posts INTEGER,
            most_used_channels TEXT,
            most_used_emojis TEXT,
            most_reacted_post_message_id BIGINT,
            most_reacted_post_channel_id BIGINT,
            most_reacted_post_reaction_count INTEGER,
            fan_of_users TEXT,
            users_fans TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, user_id, year),
            user_ranks TEXT
        )
    """)
    connection.commit()
    cursor.close()

def insert_hof_wrapped(connection, guild_id, user_id, year, reaction_count, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_message_id, most_reacted_post_channel_id, most_reacted_post_reaction_count, fan_of_users, users_fans, user_ranks):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO hof_wrapped (
            guild_id, user_id, year, reaction_count, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_message_id, most_reacted_post_channel_id, most_reacted_post_reaction_count, fan_of_users, users_fans, user_ranks
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (guild_id, user_id, year) DO UPDATE SET
            reaction_count=EXCLUDED.reaction_count,
            hof_message_posts=EXCLUDED.hof_message_posts,
            most_used_channels=EXCLUDED.most_used_channels,
            most_used_emojis=EXCLUDED.most_used_emojis,
            most_reacted_post_message_id=EXCLUDED.most_reacted_post_message_id,
            most_reacted_post_channel_id=EXCLUDED.most_reacted_post_channel_id,
            most_reacted_post_reaction_count=EXCLUDED.most_reacted_post_reaction_count,
            fan_of_users=EXCLUDED.fan_of_users,
            users_fans=EXCLUDED.users_fans,
            user_ranks=EXCLUDED.user_ranks,
            created_at=CURRENT_TIMESTAMP
    """,
    (guild_id, user_id, year, reaction_count, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_message_id, most_reacted_post_channel_id, most_reacted_post_reaction_count, fan_of_users, users_fans, user_ranks))
    connection.commit()
    cursor.close()

def get_hof_wrapped(connection, guild_id, user_id, year):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM hof_wrapped WHERE guild_id = %s AND user_id = %s AND year = %s
    """, (guild_id, user_id, year))
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    result = dict(zip(columns, row))
    cursor.close()
    return result

def delete_hof_wrapped_for_guild(connection, guild_id):
    cursor = connection.cursor()
    cursor.execute("""
        DELETE FROM hof_wrapped WHERE guild_id = %s
    """, (guild_id,))
    connection.commit()
    cursor.close()