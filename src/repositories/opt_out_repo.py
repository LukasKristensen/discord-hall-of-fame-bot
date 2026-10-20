"""
Members who asked not to be counted, through "Delete and stop counting me" on /delete_my_data.

Their posts can still reach a server's board, since the board belongs to the server, but the post is
stored without an author, so it never reaches a leaderboard, profile or Wrapped. Keeping the user ID
here is the least the bot can store to remember the request.
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


def set_opted_out(connection, user_id, opted_out: bool, commit: bool = True):
    """
    Stop or start counting a member
    :param connection: The database connection
    :param user_id: The member's user ID
    :param opted_out: True to stop counting them
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
