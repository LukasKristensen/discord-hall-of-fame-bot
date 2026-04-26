def create_guild_monthly_snapshot_table(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guild_monthly_snapshot (
            guild_id BIGINT NOT NULL,
            month_start DATE NOT NULL,
            member_count INTEGER NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            captured_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (guild_id, month_start)
        )
        """
    )
    cursor.execute(
        """
        ALTER TABLE guild_monthly_snapshot
        ALTER COLUMN captured_at TYPE TIMESTAMPTZ
        USING captured_at AT TIME ZONE 'UTC'
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_guild_monthly_snapshot_month_start
        ON guild_monthly_snapshot (month_start)
        """
    )
    connection.commit()
    cursor.close()


def upsert_guild_monthly_snapshot(
    connection,
    guild_id,
    month_start,
    member_count,
    message_count,
    captured_at,
):
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO guild_monthly_snapshot
            (guild_id, month_start, member_count, message_count, captured_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (guild_id, month_start) DO UPDATE SET
            member_count = EXCLUDED.member_count,
            message_count = EXCLUDED.message_count,
            captured_at = EXCLUDED.captured_at
        """,
        (guild_id, month_start, member_count, message_count, captured_at),
    )
    # Removing commit here because we want to commit outside in bulk
    connection.commit()
    cursor.close()

def upsert_guild_monthly_snapshots_batch(connection, records):
    """
    records is a list of tuples: (guild_id, month_start, member_count, message_count, captured_at)
    """
    if not records:
        return
    cursor = connection.cursor()
    from psycopg2.extras import execute_values
    execute_values(
        cursor,
        """
        INSERT INTO guild_monthly_snapshot
            (guild_id, month_start, member_count, message_count, captured_at)
        VALUES %s
        ON CONFLICT (guild_id, month_start) DO UPDATE SET
            member_count = EXCLUDED.member_count,
            message_count = EXCLUDED.message_count,
            captured_at = EXCLUDED.captured_at
        """,
        records,
    )
    connection.commit()
    cursor.close()


def get_monthly_members_per_server(connection, month_start):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT guild_id, member_count
        FROM guild_monthly_snapshot
        WHERE month_start = %s
        ORDER BY member_count DESC
        """,
        (month_start,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [{"guild_id": row[0], "member_count": row[1]} for row in rows]


def get_monthly_messages_per_server(connection, month_start):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT guild_id, message_count
        FROM guild_monthly_snapshot
        WHERE month_start = %s
        ORDER BY message_count DESC
        """,
        (month_start,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [{"guild_id": row[0], "message_count": row[1]} for row in rows]


def get_monthly_messages_vs_members(connection, month_start):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            guild_id,
            message_count,
            member_count,
            CASE
                WHEN member_count > 0
                THEN ROUND((message_count::numeric / member_count::numeric) * 1000, 2)
                ELSE 0
            END AS messages_per_1k_members
        FROM guild_monthly_snapshot
        WHERE month_start = %s
        ORDER BY messages_per_1k_members DESC
        """,
        (month_start,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [
        {
            "guild_id": row[0],
            "message_count": row[1],
            "member_count": row[2],
            "messages_per_1k_members": float(row[3]),
        }
        for row in rows
    ]
