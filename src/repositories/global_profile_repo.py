"""
The global profile: a member's Hall of Fame record added up across every server with the bot.

The card shows totals only. No server name, server ID or message content ever leaves this module, so
a card shown in one server says nothing about which other servers the member is in.

Every post counts, so the global numbers are the sum of the member's profiles in each server. A server
made for one person can pad them, but nothing is ranked or rewarded on them yet. Filter out small
servers and posts here if a global leaderboard or percentile is ever added.
"""


def create_hidden_global_profile_table(connection):
    """
    Members who hid their global profile from everybody else. A row exists only for them, so the
    default, a visible card, needs no row at all
    """
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hidden_global_profile (
            user_id BIGINT PRIMARY KEY,
            hidden_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    connection.commit()
    cursor.close()


def is_hidden(connection, user_id) -> bool:
    cursor = connection.cursor()
    cursor.execute("SELECT 1 FROM hidden_global_profile WHERE user_id = %s", (user_id,))
    hidden = cursor.fetchone() is not None
    cursor.close()
    return hidden


def set_hidden(connection, user_id, hidden: bool):
    """
    Hide or show a member's global profile
    :param connection: The database connection
    :param user_id: The member's user ID
    :param hidden: True to hide it from everybody else
    """
    cursor = connection.cursor()
    if hidden:
        cursor.execute("INSERT INTO hidden_global_profile (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                       (user_id,))
    else:
        cursor.execute("DELETE FROM hidden_global_profile WHERE user_id = %s", (user_id,))
    connection.commit()
    cursor.close()


PROFILE_FIELDS = ("posts", "reactions", "servers", "biggest_post", "best_month", "top_of_board")


def get_global_profile(connection, user_id) -> dict:
    """
    A member's totals across every server whose admins have not opted out of global profiles
    :param connection: The database connection
    :param user_id: The member's user ID
    :return: The totals named in PROFILE_FIELDS, all zero for a member with nothing that counts
    """
    cursor = connection.cursor()
    cursor.execute("""
        WITH counted AS (
            SELECT guild_id FROM server_configs WHERE COALESCE(count_in_global_profiles, TRUE)
        ),
        posts AS (
            SELECT post.guild_id, post.reaction_count, post.created_at
            FROM hall_of_fame_message post
            JOIN counted ON counted.guild_id = post.guild_id
            WHERE post.author_id = %(user_id)s
        )
        SELECT
            (SELECT COUNT(*) FROM posts),
            (SELECT COALESCE(SUM(reaction_count), 0) FROM posts),
            (SELECT COUNT(DISTINCT guild_id) FROM posts),
            (SELECT COALESCE(MAX(reaction_count), 0) FROM posts),
            (SELECT COALESCE(MAX(month_posts), 0) FROM (
                SELECT COUNT(*) AS month_posts FROM posts GROUP BY DATE_TRUNC('month', created_at)
            ) months),
            (SELECT COUNT(*) FROM server_user standing
             JOIN counted ON counted.guild_id = standing.guild_id
             WHERE standing.user_id = %(user_id)s AND standing.total_message_rank = 1
               AND standing.total_hall_of_fame_messages > 0)
    """, {"user_id": user_id})
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return {field: 0 for field in PROFILE_FIELDS}
    return {field: int(value or 0) for field, value in zip(PROFILE_FIELDS, row)}


def delete_for_user(connection, user_id):
    """Forget a member's privacy choice, as part of /delete_my_data"""
    set_hidden(connection, user_id, False)
