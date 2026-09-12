"""Every database read the statistics report performs.

The previous version of the report issued one ``COUNT(*)`` per guild and one
``get_parameter_value`` per guild, which is over a thousand round trips at the
current fleet size. Everything here is aggregated server side and pulled in a
fixed number of queries regardless of how many servers the bot is in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stats.metrics import (
    LIVE_WINDOW_DAYS,
    MonthlyAuthors,
    MonthlyGuildPosts,
    ReactionBucket,
    RhythmCell,
    ServerRow,
    StatsDataset,
    as_utc,
    build_lifespans,
)

# Rows migrated from MongoDB carry a 1970 placeholder that would otherwise
# stretch every time axis back fifty years.
REAL_TIMESTAMP = "TIMESTAMP '2000-01-01'"

SERVERS_SQL = f"""
    SELECT
        sc.guild_id,
        COALESCE(sc.server_member_count, 0),
        COALESCE(sc.reaction_threshold, 0),
        sc.joined_date,
        sc.hall_of_fame_channel_id IS NOT NULL,
        COALESCE(activity.total_posts, 0),
        COALESCE(activity.posts_last_30d, 0),
        activity.first_post_at,
        activity.last_post_at,
        COALESCE(activity.distinct_authors, 0),
        COALESCE(sc.reaction_count_calculation_method, ''),
        COALESCE(sc.leaderboard_setup, FALSE),
        COALESCE(sc.custom_emoji_check_logic, FALSE),
        COALESCE(sc.require_image_or_video, FALSE),
        COALESCE(sc.ignore_bot_messages, FALSE),
        COALESCE(sc.include_author_in_reaction_calculation, FALSE),
        COALESCE(sc.allow_messages_in_hof_channel, FALSE),
        COALESCE(sc.hide_hof_post_below_threshold, FALSE)
    FROM server_configs sc
    LEFT JOIN (
        SELECT
            guild_id,
            COUNT(*) AS total_posts,
            COUNT(*) FILTER (WHERE created_at >= %s) AS posts_last_30d,
            MIN(created_at) AS first_post_at,
            MAX(created_at) AS last_post_at,
            COUNT(DISTINCT author_id) AS distinct_authors
        FROM hall_of_fame_message
        WHERE created_at >= {REAL_TIMESTAMP}
        GROUP BY guild_id
    ) activity ON activity.guild_id = sc.guild_id
"""

LIFECYCLE_EVENTS_SQL = """
    SELECT guild_id, event_type, occurred_at
    FROM guild_lifecycle_event
    ORDER BY guild_id, occurred_at
"""

MONTHLY_GUILD_POSTS_SQL = f"""
    SELECT DATE_TRUNC('month', created_at)::date, guild_id, COUNT(*)
    FROM hall_of_fame_message
    WHERE created_at >= {REAL_TIMESTAMP}
    GROUP BY 1, 2
    ORDER BY 1, 2
"""

MONTHLY_AUTHORS_SQL = f"""
    SELECT DATE_TRUNC('month', created_at)::date, COUNT(DISTINCT author_id)
    FROM hall_of_fame_message
    WHERE created_at >= {REAL_TIMESTAMP}
    GROUP BY 1
    ORDER BY 1
"""

POSTING_RHYTHM_SQL = f"""
    SELECT
        EXTRACT(ISODOW FROM created_at)::int - 1 AS weekday,
        EXTRACT(HOUR FROM created_at)::int AS hour,
        COUNT(*)
    FROM hall_of_fame_message
    WHERE created_at >= {REAL_TIMESTAMP}
    GROUP BY 1, 2
"""

REACTION_HEADROOM_SQL = f"""
    SELECT h.reaction_count, sc.reaction_threshold, COUNT(*)
    FROM hall_of_fame_message h
    JOIN server_configs sc ON sc.guild_id = h.guild_id
    WHERE h.created_at >= {REAL_TIMESTAMP}
      AND sc.reaction_threshold > 0
      AND h.reaction_count > 0
    GROUP BY 1, 2
"""


def _fetch(connection, sql, params=None, optional=False):
    """Run one aggregate query.

    ``optional`` covers tables a given deployment may not have yet, such as the
    lifecycle log on an installation that predates it: those come back empty
    rather than taking down the whole report.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or ())
        return cursor.fetchall()
    except Exception:
        if not optional:
            raise
        connection.rollback()
        return []
    finally:
        cursor.close()


def _server_row(row) -> ServerRow:
    return ServerRow(
        guild_id=row[0],
        member_count=row[1],
        reaction_threshold=row[2],
        joined_at=as_utc(row[3]),
        hof_channel_configured=bool(row[4]),
        total_posts=row[5],
        posts_last_30d=row[6],
        first_post_at=as_utc(row[7]),
        last_post_at=as_utc(row[8]),
        distinct_authors=row[9],
        calculation_method=row[10] or "unknown",
        flags={
            "leaderboard_setup": bool(row[11]),
            "custom_emoji_check_logic": bool(row[12]),
            "require_image_or_video": bool(row[13]),
            "ignore_bot_messages": bool(row[14]),
            "include_author_in_reaction_calculation": bool(row[15]),
            "allow_messages_in_hof_channel": bool(row[16]),
            "hide_hof_post_below_threshold": bool(row[17]),
        },
    )


def load_dataset(connection, reference_dt=None) -> StatsDataset:
    """Pull the whole report dataset in six aggregate queries."""
    now = as_utc(reference_dt or datetime.now(timezone.utc))
    live_window_start = now - timedelta(days=LIVE_WINDOW_DAYS)

    servers = [_server_row(row) for row in _fetch(connection, SERVERS_SQL, (live_window_start,))]
    events = _fetch(connection, LIFECYCLE_EVENTS_SQL, optional=True)

    return StatsDataset(
        generated_at=now,
        servers=servers,
        # Folding events into lifespans is pure logic, so it lives in metrics
        # where it is unit tested rather than in SQL.
        lifespans=build_lifespans(events, servers),
        monthly_guild_posts=[
            MonthlyGuildPosts(month=row[0], guild_id=row[1], posts=row[2])
            for row in _fetch(connection, MONTHLY_GUILD_POSTS_SQL)
        ],
        monthly_authors=[
            MonthlyAuthors(month=row[0], authors=row[1])
            for row in _fetch(connection, MONTHLY_AUTHORS_SQL)
        ],
        posting_rhythm=[
            RhythmCell(weekday=row[0], hour=row[1], posts=row[2])
            for row in _fetch(connection, POSTING_RHYTHM_SQL)
        ],
        reaction_headroom=[
            ReactionBucket(reaction_count=row[0], reaction_threshold=row[1], posts=row[2])
            for row in _fetch(connection, REACTION_HEADROOM_SQL, optional=True)
        ],
        source="postgres",
    )
