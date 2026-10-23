"""
The warnings a server was sent about the bot missing permissions in its Hall of Fame channel.

Kept in the database so a restart does not warn every broken server again, and so the daily check can
stop after a few warnings about the same permissions instead of repeating them for as long as a server
ignores them. A row is deleted once the permissions are fixed, and when the bot leaves the server.
"""


def create_permission_warning_table(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS permission_warning (
            guild_id BIGINT PRIMARY KEY,
            missing_permissions TEXT[] NOT NULL,
            warnings_sent INTEGER NOT NULL,
            first_warned_at TIMESTAMPTZ NOT NULL,
            last_warned_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    connection.commit()
    cursor.close()


def get_permission_warnings(connection) -> dict:
    """Every server's latest warning, as guild ID to (missing permissions, warnings sent, first, last)."""
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT guild_id, missing_permissions, warnings_sent, first_warned_at, last_warned_at
        FROM permission_warning
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    return {row[0]: (frozenset(row[1] or ()), row[2], row[3], row[4]) for row in rows}


def save_permission_warnings(connection, records):
    """
    records is a list of tuples: (guild_id, missing_permissions, warnings_sent, first_warned_at, last_warned_at)
    """
    if not records:
        return
    cursor = connection.cursor()
    from psycopg2.extras import execute_values
    execute_values(
        cursor,
        """
        INSERT INTO permission_warning
            (guild_id, missing_permissions, warnings_sent, first_warned_at, last_warned_at)
        VALUES %s
        ON CONFLICT (guild_id) DO UPDATE SET
            missing_permissions = EXCLUDED.missing_permissions,
            warnings_sent = EXCLUDED.warnings_sent,
            first_warned_at = EXCLUDED.first_warned_at,
            last_warned_at = EXCLUDED.last_warned_at
        """,
        [(guild_id, sorted(missing), sent, first, last) for guild_id, missing, sent, first, last in records],
    )
    connection.commit()
    cursor.close()


def delete_permission_warnings(connection, guild_ids):
    if not guild_ids:
        return
    cursor = connection.cursor()
    cursor.execute("DELETE FROM permission_warning WHERE guild_id = ANY(%s)", (list(guild_ids),))
    connection.commit()
    cursor.close()
