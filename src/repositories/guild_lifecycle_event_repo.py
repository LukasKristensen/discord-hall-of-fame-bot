def create_guild_lifecycle_event_table(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guild_lifecycle_event (
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            event_type VARCHAR(8) NOT NULL CHECK (event_type IN ('JOIN', 'LEAVE')),
            occurred_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_guild_lifecycle_event_occurred_at
        ON guild_lifecycle_event (occurred_at)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_guild_lifecycle_event_guild_occurred
        ON guild_lifecycle_event (guild_id, occurred_at)
        """
    )
    connection.commit()
    cursor.close()


def insert_guild_lifecycle_event(connection, guild_id, event_type, occurred_at):
    if event_type not in ("JOIN", "LEAVE"):
        raise ValueError(f"Unsupported event_type: {event_type}")

    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO guild_lifecycle_event (guild_id, event_type, occurred_at)
        VALUES (%s, %s, %s)
        """,
        (guild_id, event_type, occurred_at),
    )
    connection.commit()
    cursor.close()


def get_monthly_join_leave_counts(connection, start_month, end_month):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            DATE_TRUNC('month', occurred_at) AS month_start,
            SUM(CASE WHEN event_type = 'JOIN' THEN 1 ELSE 0 END) AS joined_count,
            SUM(CASE WHEN event_type = 'LEAVE' THEN 1 ELSE 0 END) AS left_count
        FROM guild_lifecycle_event
        WHERE occurred_at >= %s AND occurred_at < %s
        GROUP BY DATE_TRUNC('month', occurred_at)
        ORDER BY month_start ASC
        """,
        (start_month, end_month),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [
        {"month_start": row[0], "joined_count": row[1], "left_count": row[2]}
        for row in rows
    ]


def get_active_servers_as_of(connection, as_of_timestamp):
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT
                guild_id,
                SUM(
                    CASE
                        WHEN event_type = 'JOIN' THEN 1
                        WHEN event_type = 'LEAVE' THEN -1
                        ELSE 0
                    END
                ) AS net_presence
            FROM guild_lifecycle_event
            WHERE occurred_at <= %s
            GROUP BY guild_id
            HAVING SUM(
                CASE
                    WHEN event_type = 'JOIN' THEN 1
                    WHEN event_type = 'LEAVE' THEN -1
                    ELSE 0
                END
            ) > 0
        ) active_guilds
        """,
        (as_of_timestamp,),
    )
    result = cursor.fetchone()
    cursor.close()
    return result[0] if result else 0


def get_active_servers_timeseries(connection, start_month, end_month):
    cursor = connection.cursor()
    cursor.execute(
        """
        WITH months AS (
            SELECT generate_series(
                DATE_TRUNC('month', %s::timestamptz),
                DATE_TRUNC('month', %s::timestamptz) - INTERVAL '1 month',
                INTERVAL '1 month'
            ) AS month_start
        )
        SELECT
            m.month_start,
            (
                SELECT COUNT(*) FROM (
                    SELECT
                        guild_id,
                        SUM(
                            CASE
                                WHEN event_type = 'JOIN' THEN 1
                                WHEN event_type = 'LEAVE' THEN -1
                                ELSE 0
                            END
                        ) AS net_presence
                    FROM guild_lifecycle_event
                    WHERE occurred_at < (m.month_start + INTERVAL '1 month')
                    GROUP BY guild_id
                    HAVING SUM(
                        CASE
                            WHEN event_type = 'JOIN' THEN 1
                            WHEN event_type = 'LEAVE' THEN -1
                            ELSE 0
                        END
                    ) > 0
                ) active_guilds
            ) AS active_servers
        FROM months m
        ORDER BY m.month_start ASC
        """,
        (start_month, end_month),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [{"month_start": row[0], "active_servers": row[1]} for row in rows]
