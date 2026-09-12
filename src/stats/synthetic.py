"""A synthetic dataset shaped like the production fleet.

Running ``server_stats.py --synthetic`` renders the full report without a
database. That is useful for two things: designing and reviewing the charts at
realistic scale without holding a production credential, and having a stable
fixture to eyeball after changing a chart.

The generator is seeded, so the same seed always produces the same report.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from stats.metrics import (
    GuildLifespan,
    MonthlyAuthors,
    MonthlyGuildPosts,
    ReactionBucket,
    RhythmCell,
    ServerRow,
    StatsDataset,
    add_months,
    month_floor,
    month_range,
    months_between,
)

CALCULATION_METHODS = (
    ("most_reactions_on_emoji", 0.72),
    ("total_reactions", 0.21),
    ("unique_reaction_users", 0.07),
)

# Roughly the production mix: a long tail of small communities plus a handful of
# very large ones that dominate the member total. Tuned so that ~500 servers add
# up to ~240k members, which is where the real fleet sits.
SMALL_SERVER_SHARE = 0.95


def _lognormal(rng, median, sigma):
    return median * math.exp(rng.gauss(0.0, sigma))


def _pick_weighted(rng, options):
    roll = rng.random()
    running = 0.0
    for value, weight in options:
        running += weight
        if roll <= running:
            return value
    return options[-1][0]


def _member_count(rng) -> int:
    if rng.random() < SMALL_SERVER_SHARE:
        return max(8, int(_lognormal(rng, 150, 1.10)))
    return max(1_500, int(_lognormal(rng, 2_500, 1.05)))


def _threshold(rng, member_count) -> int:
    """Most servers keep the default; larger ones tend to raise it."""
    if rng.random() < 0.62:
        return 5
    if member_count > 3_000:
        return rng.choice([8, 10, 10, 12, 15, 20, 25])
    return rng.choice([2, 3, 3, 4, 6, 7, 8, 10])


def _flags(rng, member_count):
    return {
        "leaderboard_setup": rng.random() < 0.34,
        "custom_emoji_check_logic": rng.random() < 0.18,
        "require_image_or_video": rng.random() < 0.11,
        "ignore_bot_messages": rng.random() < 0.27,
        "include_author_in_reaction_calculation": rng.random() < 0.81,
        "allow_messages_in_hof_channel": rng.random() < 0.64,
        "hide_hof_post_below_threshold": rng.random() < 0.88,
    }


def _generate_lifespans(rng, now, total_guilds, history_months):
    """Installs ramping up over time, with a hazard of leaving each month."""
    first_month = add_months(month_floor(now), -history_months)
    months = month_range(first_month, month_floor(now))

    # Weight later months more heavily so the install curve accelerates.
    weights = [math.exp(index / (len(months) / 2.2)) for index in range(len(months))]
    total_weight = sum(weights)

    lifespans = []
    guild_id = 100_000_000_000_000_000
    for month, weight in zip(months, weights):
        joins = max(1, int(round(total_guilds * weight / total_weight)))
        for _ in range(joins):
            guild_id += rng.randint(1, 9_999)
            joined_at = datetime(month.year, month.month, 1, tzinfo=timezone.utc) + timedelta(
                days=rng.uniform(0, 27), hours=rng.uniform(0, 23)
            )
            if joined_at > now:
                continue
            left_at = _sample_departure(rng, joined_at, now)
            lifespans.append(GuildLifespan(guild_id, joined_at, left_at))
    return lifespans


def _sample_departure(rng, joined_at, now):
    """Churn front-loaded into the first weeks, then a low steady hazard."""
    if rng.random() < 0.14:  # Uninstalled almost immediately.
        left_at = joined_at + timedelta(days=rng.uniform(0.2, 30))
        return left_at if left_at < now else None

    age_months = max(0, months_between(month_floor(joined_at), month_floor(now)))
    for month_index in range(1, age_months + 1):
        if rng.random() < 0.022:
            left_at = joined_at + timedelta(days=30.44 * month_index + rng.uniform(0, 30))
            return left_at if left_at < now else None
    return None


def _monthly_posts_for(rng, server, joined_at, now, member_count, threshold):
    """A decaying but noisy monthly posting series for one server."""
    start = month_floor(joined_at)
    months = month_range(start, month_floor(now))
    if not months:
        return []

    # Bigger servers clear the threshold more often; a high threshold suppresses
    # it again. The exponent keeps the relationship sublinear, as observed.
    base = (member_count ** 0.62) / (threshold ** 0.75) * rng.uniform(0.25, 1.9)

    # Roughly a third of servers eventually go quiet without uninstalling. Without
    # this every activated server also looks live, and the gap between "has ever
    # posted" and "still posting" - the gap the report exists to show - vanishes.
    goes_quiet_after = None
    if rng.random() < 0.34 and len(months) > 3:
        goes_quiet_after = rng.randint(2, len(months) - 1)

    series = []
    for index, month in enumerate(months):
        if goes_quiet_after is not None and index >= goes_quiet_after:
            break
        decay = 0.55 + 0.45 * math.exp(-index / 14.0)
        seasonal = 1.0 + 0.18 * math.sin((month.month / 12.0) * 2 * math.pi)
        expected = base * decay * seasonal * rng.uniform(0.35, 1.65)
        posts = int(max(0, round(expected)))
        if index == 0:
            posts = int(posts * rng.uniform(0.0, 0.6))  # Partial first month.
        if posts:
            series.append((month, posts))
    return series


def build_dataset(seed: int = 20260908, servers_alive: int = 520, history_months: int = 34) -> StatsDataset:
    """Generate a full report dataset at roughly production scale."""
    rng = random.Random(seed)
    now = datetime(2026, 9, 8, 20, 0, tzinfo=timezone.utc)

    # Over-generate so that after churn the surviving count lands near the target.
    lifespans = _generate_lifespans(rng, now, int(servers_alive * 1.45), history_months)
    alive = [lifespan for lifespan in lifespans if lifespan.left_at is None]

    servers = []
    monthly_guild_posts = []
    posts_by_month_total = {}

    for lifespan in alive:
        member_count = _member_count(rng)
        threshold = _threshold(rng, member_count)
        configured = rng.random() < 0.86

        series = []
        if configured and rng.random() < 0.79:
            series = _monthly_posts_for(rng, lifespan, lifespan.joined_at, now, member_count, threshold)

        total_posts = sum(posts for _, posts in series)
        current_month = month_floor(now)
        posts_last_30d = next((posts for month, posts in series if month == current_month), 0)

        first_post_at = None
        last_post_at = None
        if series:
            first_month, _ = series[0]
            last_month, _ = series[-1]
            first_post_at = datetime(first_month.year, first_month.month, 1, tzinfo=timezone.utc) + timedelta(
                days=rng.uniform(0, 27)
            )
            first_post_at = max(first_post_at, lifespan.joined_at + timedelta(days=rng.uniform(0.1, 21)))
            last_post_at = datetime(last_month.year, last_month.month, 1, tzinfo=timezone.utc) + timedelta(
                days=rng.uniform(0, 27)
            )

        servers.append(
            ServerRow(
                guild_id=lifespan.guild_id,
                member_count=member_count,
                reaction_threshold=threshold,
                joined_at=lifespan.joined_at,
                hof_channel_configured=configured,
                total_posts=total_posts,
                posts_last_30d=posts_last_30d,
                first_post_at=first_post_at,
                last_post_at=last_post_at,
                # Rarely does every member get celebrated; the ceiling is the
                # number of posts, the floor a fraction of them.
                distinct_authors=int(total_posts * rng.uniform(0.25, 0.75)) if total_posts else 0,
                calculation_method=_pick_weighted(rng, CALCULATION_METHODS),
                flags=_flags(rng, member_count),
            )
        )

        for month, posts in series:
            monthly_guild_posts.append(MonthlyGuildPosts(month=month, guild_id=lifespan.guild_id, posts=posts))
            posts_by_month_total[month] = posts_by_month_total.get(month, 0) + posts

    monthly_authors = [
        MonthlyAuthors(month=month, authors=int(posts * rng.uniform(0.3, 0.55)))
        for month, posts in sorted(posts_by_month_total.items())
    ]

    return StatsDataset(
        generated_at=now,
        servers=servers,
        lifespans=lifespans,
        monthly_guild_posts=monthly_guild_posts,
        monthly_authors=monthly_authors,
        posting_rhythm=_posting_rhythm(rng, sum(posts_by_month_total.values())),
        reaction_headroom=_reaction_headroom(rng, servers),
        source="synthetic",
    )


def _posting_rhythm(rng, total_posts):
    """Evening-weighted UTC activity with a weekend lift."""
    cells = []
    for weekday in range(7):
        weekend_lift = 1.35 if weekday >= 5 else 1.0
        for hour in range(24):
            # Two humps: European evening and American evening.
            evening = math.exp(-((hour - 20) ** 2) / 18.0) + 0.7 * math.exp(-((hour - 2) ** 2) / 14.0)
            night = 0.08
            weight = (evening + night) * weekend_lift * rng.uniform(0.85, 1.15)
            cells.append(RhythmCell(weekday=weekday, hour=hour, posts=int(weight * total_posts / 60)))
    return cells


def _reaction_headroom(rng, servers):
    """Reaction counts clustered just above each server's threshold."""
    tally = {}
    for server in servers:
        if not server.total_posts or not server.reaction_threshold:
            continue
        for _ in range(min(server.total_posts, 400)):
            ratio = 1.0 + abs(rng.gauss(0.0, 0.55)) ** 1.35
            reaction_count = max(server.reaction_threshold, int(round(server.reaction_threshold * ratio)))
            key = (reaction_count, server.reaction_threshold)
            tally[key] = tally.get(key, 0) + 1
    return [
        ReactionBucket(reaction_count=count, reaction_threshold=threshold, posts=posts)
        for (count, threshold), posts in sorted(tally.items())
    ]
