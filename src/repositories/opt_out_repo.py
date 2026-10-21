"""
Members who asked not to be featured, through "Stop featuring me", offered after deleting their data
on /my_data.

Their messages are not reposted to any board or stored, so they never reach a leaderboard, profile or
Wrapped. Keeping the user ID here is the least the bot can store to remember the request.
"""


def create_opted_out_member_table(connection):
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS opted_out_member (
            user_id BIGINT PRIMARY KEY,
            opted_out_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    connection.commit()
    cursor.close()


def is_opted_out(connection, user_id) -> bool:
    cursor = connection.cursor()
    cursor.execute("SELECT 1 FROM opted_out_member WHERE user_id = %s", (user_id,))
    opted_out = cursor.fetchone() is not None
    cursor.close()
    return opted_out


def find_opted_out(connection, user_ids) -> set:
    """
    Which of these members asked not to be featured, in one query, for Wrapped
    :param connection: The database connection
    :param user_ids: The members to check
    :return: The IDs among them that are opted out
    """
    user_ids = list(user_ids)
    if not user_ids:
        return set()
    cursor = connection.cursor()
    cursor.execute("SELECT user_id FROM opted_out_member WHERE user_id = ANY(%s)", (user_ids,))
    found = {row[0] for row in cursor.fetchall()}
    cursor.close()
    return found


def opted_out_since(connection, user_id):
    """
    When a member asked not to be featured, for the /my_data summary, which shows it in place of a file
    :param connection: The database connection
    :param user_id: The member's user ID
    :return: The time they asked, or None when they did not
    """
    cursor = connection.cursor()
    cursor.execute("SELECT opted_out_at FROM opted_out_member WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


def set_opted_out(connection, user_id, opted_out: bool, commit: bool = True):
    """
    Stop or start featuring a member's messages
    :param connection: The database connection
    :param user_id: The member's user ID
    :param opted_out: True to stop featuring them
    :param commit: False to leave the commit to the caller, as part of a larger transaction
    """
    cursor = connection.cursor()
    if opted_out:
        cursor.execute("INSERT INTO opted_out_member (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                       (user_id,))
    else:
        cursor.execute("DELETE FROM opted_out_member WHERE user_id = %s", (user_id,))
    if commit:
        connection.commit()
    cursor.close()
