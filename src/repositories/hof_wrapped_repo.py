def create_hof_wrapped_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hof_wrapped (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            year INTEGER NOT NULL,
            message_count INTEGER,
            reaction_count INTEGER,
            reaction_to_non_hof_posts INTEGER,
            reaction_to_hof_posts INTEGER,
            hof_message_posts INTEGER,
            most_used_channels TEXT,
            most_used_emojis TEXT,
            most_reacted_post_id BIGINT,
            most_reacted_post_reaction_count INTEGER,
            fan_of_users TEXT,
            users_fans TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, user_id, year)
        )
    """)
    connection.commit()
    cursor.close()

def insert_hof_wrapped(connection, guild_id, user_id, year, message_count, reaction_count, reaction_to_non_hof_posts, reaction_to_hof_posts, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_id, most_reacted_post_reaction_count, fan_of_users, users_fans):
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO hof_wrapped (
            guild_id, user_id, year, message_count, reaction_count, reaction_to_non_hof_posts, reaction_to_hof_posts, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_id, most_reacted_post_reaction_count, fan_of_users, users_fans
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (guild_id, user_id, year) DO UPDATE SET
            message_count=EXCLUDED.message_count,
            reaction_count=EXCLUDED.reaction_count,
            reaction_to_non_hof_posts=EXCLUDED.reaction_to_non_hof_posts,
            reaction_to_hof_posts=EXCLUDED.reaction_to_hof_posts,
            hof_message_posts=EXCLUDED.hof_message_posts,
            most_used_channels=EXCLUDED.most_used_channels,
            most_used_emojis=EXCLUDED.most_used_emojis,
            most_reacted_post_id=EXCLUDED.most_reacted_post_id,
            most_reacted_post_reaction_count=EXCLUDED.most_reacted_post_reaction_count,
            fan_of_users=EXCLUDED.fan_of_users,
            users_fans=EXCLUDED.users_fans,
            created_at=CURRENT_TIMESTAMP
    """,
    (guild_id, user_id, year, message_count, reaction_count, reaction_to_non_hof_posts, reaction_to_hof_posts, hof_message_posts, most_used_channels, most_used_emojis, most_reacted_post_id, most_reacted_post_reaction_count, fan_of_users, users_fans))
    connection.commit()
    cursor.close()

def get_hof_wrapped(cursor, guild_id, user_id, year):
    cursor.execute("""
        SELECT * FROM hof_wrapped WHERE guild_id = %s AND user_id = %s AND year = %s
    """, (guild_id, user_id, year))
    return cursor.fetchone()
