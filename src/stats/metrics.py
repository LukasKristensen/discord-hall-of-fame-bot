"""Pure calculations behind the server statistics report.

Nothing in this module imports numpy, matplotlib or psycopg2. The report is a
developer tool whose plotting dependencies are deliberately kept out of
``requirements.txt``, and staying dependency free is what lets the unit tests
cover these calculations in CI.

The vocabulary used throughout:

* **installed**  - the bot is currently in the server.
* **activated**  - the server has published at least one Hall of Fame post.
* **live**       - the server published a post inside the trailing 30 days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

LIVE_WINDOW_DAYS = 30
DAYS_PER_MONTH = 30.44

# The epoch placeholder that legacy MongoDB rows were migrated with. Anything at
# or before this is not a real timestamp and would drag every time axis to 1970.
EPOCH_CUTOFF = datetime(2000, 1, 1, tzinfo=timezone.utc)

SIZE_BUCKETS = (
    ("< 100", 0, 100),
    ("100 - 499", 100, 500),
    ("500 - 1.9k", 500, 2_000),
    ("2k - 9.9k", 2_000, 10_000),
    ("10k+", 10_000, None),
)

THRESHOLD_BANDS = (
    ("1 - 3", 1, 4),
    ("4 - 5", 4, 6),
    ("6 - 9", 6, 10),
    ("10 - 19", 10, 20),
    ("20+", 20, None),
)

# Config flags worth reporting on, in the order they appear in the adoption table.
CONFIG_FLAGS = (
    ("leaderboard_setup", "Leaderboard set up"),
    ("custom_emoji_check_logic", "Custom emoji whitelist"),
    ("require_image_or_video", "Requires image or video"),
    ("ignore_bot_messages", "Ignores bot messages"),
    ("include_author_in_reaction_calculation", "Counts the author's own reaction"),
    ("allow_messages_in_hof_channel", "Allows chatting in the HOF channel"),
    ("hide_hof_post_below_threshold", "Hides posts that fall below threshold"),
)


def as_utc(value):
    """Normalise a timestamp to an aware UTC datetime.

    Half the schema stores ``TIMESTAMP`` and half stores ``TIMESTAMPTZ``, so
    without this the report hits "can't subtract offset-naive and offset-aware"
    the moment two sources are compared.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return None


def is_real_timestamp(value) -> bool:
    """Whether a timestamp is a genuine event rather than a migration placeholder."""
    normalised = as_utc(value)
    return normalised is not None and normalised >= EPOCH_CUTOFF


def month_floor(value) -> date:
    """The first day of the month a timestamp falls in."""
    normalised = as_utc(value)
    return date(normalised.year, normalised.month, 1)


def add_months(month: date, count: int) -> date:
    """Shift a month-start date by a whole number of months."""
    total = (month.year * 12 + month.month - 1) + count
    return date(total // 12, total % 12 + 1, 1)


def months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``; negative when ``end`` precedes ``start``."""
    return (end.year * 12 + end.month) - (start.year * 12 + start.month)


def month_range(first: date, last: date) -> list[date]:
    """Every month start from ``first`` to ``last`` inclusive, with no gaps."""
    months = []
    current = date(first.year, first.month, 1)
    stop = date(last.year, last.month, 1)
    while current <= stop:
        months.append(current)
        current = add_months(current, 1)
    return months


@dataclass(frozen=True)
class ServerRow:
    """One installed server, joined to its Hall of Fame activity."""

    guild_id: int
    member_count: int
    reaction_threshold: int
    joined_at: datetime | None
    hof_channel_configured: bool
    total_posts: int
    posts_last_30d: int
    first_post_at: datetime | None
    last_post_at: datetime | None
    distinct_authors: int
    calculation_method: str = ""
    flags: dict = field(default_factory=dict)

    @property
    def is_activated(self) -> bool:
        return self.total_posts > 0

    @property
    def is_live(self) -> bool:
        return self.posts_last_30d > 0

    def tenure_days(self, now: datetime):
        """Days since the bot joined, or ``None`` when the join date is unusable."""
        if not is_real_timestamp(self.joined_at):
            return None
        return max((as_utc(now) - as_utc(self.joined_at)).total_seconds() / 86400.0, 0.0)

    def posts_per_day(self, now: datetime):
        """Lifetime posting rate, the only fair way to compare servers that
        joined years apart."""
        tenure = self.tenure_days(now)
        if tenure is None:
            return None
        return self.total_posts / max(tenure, 1.0)

    @property
    def posts_per_1k_members(self):
        if not self.member_count:
            return None
        return self.total_posts / self.member_count * 1000.0

    @property
    def days_to_first_post(self):
        if not is_real_timestamp(self.joined_at) or not is_real_timestamp(self.first_post_at):
            return None
        delta = (as_utc(self.first_post_at) - as_utc(self.joined_at)).total_seconds() / 86400.0
        return max(delta, 0.0)

    @property
    def size_bucket(self) -> str:
        return bucket_label(self.member_count, SIZE_BUCKETS)

    @property
    def threshold_band(self) -> str:
        return bucket_label(self.reaction_threshold, THRESHOLD_BANDS)


@dataclass(frozen=True)
class GuildLifespan:
    """When a guild installed the bot and, if it has gone, when it left."""

    guild_id: int
    joined_at: datetime
    left_at: datetime | None = None

    @property
    def is_alive(self) -> bool:
        return self.left_at is None


@dataclass(frozen=True)
class MonthlyGuildPosts:
    month: date
    guild_id: int
    posts: int


@dataclass(frozen=True)
class MonthlyAuthors:
    month: date
    authors: int


@dataclass(frozen=True)
class RhythmCell:
    """Posts published in a given weekday/hour slot, in UTC."""

    weekday: int  # 0 = Monday
    hour: int
    posts: int


@dataclass(frozen=True)
class ReactionBucket:
    """How many posts landed on ``reaction_count`` under a given threshold."""

    reaction_count: int
    reaction_threshold: int
    posts: int


@dataclass
class StatsDataset:
    """Everything the report renders from, in a shape both Postgres and the
    synthetic generator can produce."""

    generated_at: datetime
    servers: list = field(default_factory=list)
    lifespans: list = field(default_factory=list)
    monthly_guild_posts: list = field(default_factory=list)
    monthly_authors: list = field(default_factory=list)
    posting_rhythm: list = field(default_factory=list)
    reaction_headroom: list = field(default_factory=list)
    source: str = "postgres"

    @property
    def now(self) -> datetime:
        return as_utc(self.generated_at)


def bucket_label(value, buckets) -> str:
    """Label the bucket ``value`` falls into, clamping below the first bucket."""
    number = value or 0
    for label, low, high in buckets:
        if number >= low and (high is None or number < high):
            return label
    return buckets[0][0]


def percentile(values, q: float) -> float:
    """Linearly interpolated percentile, matching ``numpy.percentile`` defaults.

    Reimplemented rather than imported so this module stays dependency free.
    """
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * (q / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[int(position)])
    weight = position - lower
    return float(ordered[lower]) * (1 - weight) + float(ordered[upper]) * weight


def mean(values) -> float:
    cleaned = [v for v in values if v is not None]
    return sum(cleaned) / len(cleaned) if cleaned else 0.0


def share(part: float, whole: float) -> float:
    """``part`` as a percentage of ``whole``, guarding division by zero."""
    return (part / whole * 100.0) if whole else 0.0


def gini(values) -> float:
    """Gini coefficient of a non-negative distribution: 0 is perfectly even,
    1 means a single server accounts for everything."""
    ordered = sorted(float(v) for v in values if v is not None and v >= 0)
    total = sum(ordered)
    if not ordered or total <= 0:
        return 0.0
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (count * total) - (count + 1) / count


def lorenz_curve(values):
    """Cumulative population share vs cumulative value share, both as percentages."""
    ordered = sorted(float(v) for v in values if v is not None and v >= 0)
    total = sum(ordered)
    if not ordered or total <= 0:
        return [0.0, 100.0], [0.0, 100.0]
    population = [0.0]
    cumulative = [0.0]
    running = 0.0
    for index, value in enumerate(ordered, start=1):
        running += value
        population.append(index / len(ordered) * 100.0)
        cumulative.append(running / total * 100.0)
    return population, cumulative


def top_share(values, top_fraction: float) -> float:
    """Percentage of the total held by the largest ``top_fraction`` of entries."""
    ordered = sorted((float(v) for v in values if v is not None and v >= 0), reverse=True)
    total = sum(ordered)
    if not ordered or total <= 0:
        return 0.0
    take = max(1, int(round(len(ordered) * top_fraction)))
    return sum(ordered[:take]) / total * 100.0


def log_histogram(values, bins_per_decade: int = 2):
    """Histogram over log10 spaced edges.

    Server sizes and post counts span four orders of magnitude, so linear bins
    put every server in the first bar and tell the reader nothing.
    """
    positive = [float(v) for v in values if v is not None and v > 0]
    if not positive:
        return [1.0, 10.0], [0]
    low = math.floor(math.log10(min(positive)) * bins_per_decade) / bins_per_decade
    high = math.ceil(math.log10(max(positive)) * bins_per_decade) / bins_per_decade
    if high <= low:
        high = low + 1.0 / bins_per_decade
    step = 1.0 / bins_per_decade
    edges = []
    current = low
    while current < high + step / 2:
        edges.append(10.0 ** current)
        current += step
    counts = [0] * (len(edges) - 1)
    for value in positive:
        for index in range(len(counts)):
            if value < edges[index + 1] or index == len(counts) - 1:
                counts[index] += 1
                break
    return edges, counts


def bin_by_edges(pairs, edges):
    """Sum the weights of ``(value, weight)`` pairs into ``edges`` shaped bins."""
    totals = [0.0] * (len(edges) - 1)
    for value, weight in pairs:
        if value is None or value < edges[0]:
            continue
        for index in range(len(totals)):
            if value < edges[index + 1] or index == len(totals) - 1:
                totals[index] += weight
                break
    return totals


def build_lifespans(events, servers=None) -> list:
    """Fold raw JOIN/LEAVE events into one lifespan per guild.

    ``guild_lifecycle_event`` was added long after the bot shipped, so guilds
    that are installed but have no JOIN event fall back to
    ``server_configs.joined_date``. A guild with events that is no longer in
    ``server_configs`` counts as churned even if its LEAVE was never recorded.
    """
    installed = {server.guild_id: server for server in servers} if servers else {}

    ordered_events = sorted(
        (
            (as_utc(occurred_at), guild_id, str(event_type).upper())
            for guild_id, event_type, occurred_at in events
            if is_real_timestamp(occurred_at)
        ),
        key=lambda item: (item[1], item[0]),
    )

    first_join = {}
    last_event = {}
    for occurred_at, guild_id, event_type in ordered_events:
        if event_type == "JOIN":
            # A re-invite restarts the clock, so keep the most recent join.
            first_join[guild_id] = occurred_at
            last_event[guild_id] = (occurred_at, "JOIN")
        elif event_type == "LEAVE":
            last_event[guild_id] = (occurred_at, "LEAVE")

    lifespans = []
    for guild_id, (occurred_at, event_type) in last_event.items():
        joined_at = first_join.get(guild_id)
        if joined_at is None:
            server = installed.get(guild_id)
            if server is not None and is_real_timestamp(server.joined_at):
                joined_at = as_utc(server.joined_at)
        if joined_at is None:
            continue
        if event_type == "LEAVE":
            left_at = occurred_at
        elif guild_id in installed:
            left_at = None
        else:
            # No LEAVE row, but the config is gone: treat the last thing we heard
            # from the guild as its departure rather than counting it as alive.
            left_at = occurred_at
        lifespans.append(GuildLifespan(guild_id, joined_at, left_at))

    covered = {lifespan.guild_id for lifespan in lifespans}
    for guild_id, server in installed.items():
        if guild_id in covered or not is_real_timestamp(server.joined_at):
            continue
        lifespans.append(GuildLifespan(guild_id, as_utc(server.joined_at), None))

    lifespans.sort(key=lambda lifespan: (lifespan.joined_at, lifespan.guild_id))
    return lifespans


def lifecycle_by_month(lifespans, now: datetime) -> list:
    """Joins, leaves, net change and end-of-month installed count per month."""
    if not lifespans:
        return []
    first = min(month_floor(lifespan.joined_at) for lifespan in lifespans)
    months = month_range(first, month_floor(now))

    joined_counts = {month: 0 for month in months}
    left_counts = {month: 0 for month in months}
    for lifespan in lifespans:
        joined_month = month_floor(lifespan.joined_at)
        if joined_month in joined_counts:
            joined_counts[joined_month] += 1
        if lifespan.left_at is not None:
            left_month = month_floor(lifespan.left_at)
            if left_month in left_counts:
                left_counts[left_month] += 1

    rows = []
    installed = 0
    for month in months:
        joined = joined_counts[month]
        left = left_counts[month]
        opening = installed
        installed += joined - left
        rows.append(
            {
                "month": month,
                "joined": joined,
                "left": left,
                "net": joined - left,
                "installed": installed,
                # Churn is measured against the servers that were there to leave.
                "churn_rate": share(left, opening),
            }
        )
    return rows


def monthly_post_summary(monthly_guild_posts) -> list:
    """Per month: total posts, how many servers posted, and the spread across them."""
    by_month = {}
    for entry in monthly_guild_posts:
        by_month.setdefault(entry.month, []).append(entry.posts)
    if not by_month:
        return []

    rows = []
    for month in month_range(min(by_month), max(by_month)):
        counts = by_month.get(month, [])
        rows.append(
            {
                "month": month,
                "posts": sum(counts),
                "active_servers": len(counts),
                # Median rather than mean: a handful of huge servers would
                # otherwise decide the "typical server" number for all 500.
                "median_per_server": percentile(counts, 50),
                "p25_per_server": percentile(counts, 25),
                "p75_per_server": percentile(counts, 75),
            }
        )
    return rows


FUNNEL_STAGES = (
    ("Bot installed", lambda server: True),
    ("Hall of Fame channel set", lambda server: server.hof_channel_configured),
    ("Published a first post", lambda server: server.total_posts >= 1),
    (f"Posted in the last {LIVE_WINDOW_DAYS} days", lambda server: server.is_live),
    ("Still posting, 10+ posts in total", lambda server: server.total_posts >= 10),
)


def activation_funnel(servers) -> list:
    """The install-to-habit funnel.

    Each stage narrows the previous stage's set rather than being counted
    independently, so the stages really are nested. Counting them separately
    produces conversions above 100%, because a server can be posting this month
    without ever having reached ten posts.
    """
    total = len(servers)
    remaining = list(servers)
    rows = []
    for label, predicate in FUNNEL_STAGES:
        previous = len(remaining)
        remaining = [server for server in remaining if predicate(server)]
        rows.append(
            {
                "stage": label,
                "servers": len(remaining),
                "share_of_installs": share(len(remaining), total),
                "step_conversion": share(len(remaining), previous),
            }
        )
    return rows


def size_segments(servers) -> list:
    """Break the fleet down by member count, the split that actually separates
    behaviours once there are hundreds of servers."""
    total_members = sum(s.member_count or 0 for s in servers)
    total_posts = sum(s.total_posts for s in servers)

    rows = []
    for label, _low, _high in SIZE_BUCKETS:
        in_bucket = [s for s in servers if s.size_bucket == label]
        if not in_bucket:
            rows.append(
                {
                    "segment": label, "servers": 0, "share_of_servers": 0.0,
                    "members": 0, "share_of_members": 0.0, "posts": 0,
                    "share_of_posts": 0.0, "activation_rate": 0.0, "live_rate": 0.0,
                    "median_posts": 0.0, "median_posts_per_1k": 0.0, "median_threshold": 0.0,
                }
            )
            continue

        activated = [s for s in in_bucket if s.is_activated]
        per_1k = [s.posts_per_1k_members for s in activated if s.posts_per_1k_members is not None]
        rows.append(
            {
                "segment": label,
                "servers": len(in_bucket),
                "share_of_servers": share(len(in_bucket), len(servers)),
                "members": sum(s.member_count or 0 for s in in_bucket),
                "share_of_members": share(sum(s.member_count or 0 for s in in_bucket), total_members),
                "posts": sum(s.total_posts for s in in_bucket),
                "share_of_posts": share(sum(s.total_posts for s in in_bucket), total_posts),
                "activation_rate": share(len(activated), len(in_bucket)),
                "live_rate": share(sum(1 for s in in_bucket if s.is_live), len(in_bucket)),
                "median_posts": percentile([s.total_posts for s in in_bucket], 50),
                "median_posts_per_1k": percentile(per_1k, 50),
                "median_threshold": percentile([s.reaction_threshold or 0 for s in in_bucket], 50),
            }
        )
    return rows


def threshold_bands(servers) -> list:
    """Adoption and outcome per reaction-threshold band."""
    rows = []
    for label, _low, _high in THRESHOLD_BANDS:
        in_band = [s for s in servers if s.threshold_band == label]
        if not in_band:
            rows.append(
                {
                    "band": label, "servers": 0, "share_of_servers": 0.0,
                    "activation_rate": 0.0, "median_members": 0.0, "median_posts_per_1k": 0.0,
                }
            )
            continue
        activated = [s for s in in_band if s.is_activated]
        per_1k = [s.posts_per_1k_members for s in activated if s.posts_per_1k_members is not None]
        rows.append(
            {
                "band": label,
                "servers": len(in_band),
                "share_of_servers": share(len(in_band), len(servers)),
                "activation_rate": share(len(activated), len(in_band)),
                "median_members": percentile([s.member_count or 0 for s in in_band], 50),
                "median_posts_per_1k": percentile(per_1k, 50),
            }
        )
    return rows


def config_adoption(servers) -> list:
    """For each config flag: who turns it on, and whether it goes with activation."""
    total = len(servers)
    total_members = sum(s.member_count or 0 for s in servers)

    rows = []
    for key, label in CONFIG_FLAGS:
        enabled = [s for s in servers if s.flags.get(key)]
        disabled = [s for s in servers if not s.flags.get(key)]
        rows.append(
            {
                "setting": label,
                "servers_on": len(enabled),
                "share_of_servers": share(len(enabled), total),
                "share_of_members": share(sum(s.member_count or 0 for s in enabled), total_members),
                "activation_on": share(sum(1 for s in enabled if s.is_activated), len(enabled)),
                "activation_off": share(sum(1 for s in disabled if s.is_activated), len(disabled)),
            }
        )
    return rows


def calculation_method_adoption(servers) -> list:
    """How the fleet splits across the reaction counting methods."""
    total = len(servers)
    grouped = {}
    for server in servers:
        grouped.setdefault(server.calculation_method or "unknown", []).append(server)
    rows = []
    for method, in_group in grouped.items():
        rows.append(
            {
                "method": method,
                "servers": len(in_group),
                "share_of_servers": share(len(in_group), total),
                "activation_rate": share(sum(1 for s in in_group if s.is_activated), len(in_group)),
            }
        )
    rows.sort(key=lambda row: row["servers"], reverse=True)
    return rows


def distribution_table(servers, now: datetime) -> list:
    """Percentiles for the metrics that a single average would hide."""
    activated = [s for s in servers if s.is_activated]
    metrics = [
        ("Members per server", [s.member_count or 0 for s in servers]),
        ("Hall of Fame posts (lifetime)", [s.total_posts for s in servers]),
        ("Posts per day (activated)", [s.posts_per_day(now) for s in activated]),
        ("Posts per 1k members (activated)", [s.posts_per_1k_members for s in activated]),
        ("Distinct celebrated members", [s.distinct_authors for s in servers]),
        ("Reaction threshold", [s.reaction_threshold or 0 for s in servers]),
        ("Days installed", [s.tenure_days(now) for s in servers]),
        ("Days to first post", [s.days_to_first_post for s in activated]),
    ]
    rows = []
    for label, values in metrics:
        cleaned = [v for v in values if v is not None]
        rows.append(
            {
                "metric": label,
                "n": len(cleaned),
                "p10": percentile(cleaned, 10),
                "p25": percentile(cleaned, 25),
                "p50": percentile(cleaned, 50),
                "p75": percentile(cleaned, 75),
                "p90": percentile(cleaned, 90),
                "p99": percentile(cleaned, 99),
                "mean": mean(cleaned),
            }
        )
    return rows


def top_servers(servers, now: datetime, limit: int = 25) -> list:
    """The servers carrying the fleet, ranked by trailing 30 day posts."""
    ranked = sorted(servers, key=lambda s: (s.posts_last_30d, s.total_posts), reverse=True)[:limit]
    rows = []
    for rank, server in enumerate(ranked, start=1):
        tenure = server.tenure_days(now)
        rows.append(
            {
                "rank": rank,
                "guild_id": server.guild_id,
                "members": server.member_count or 0,
                "posts_30d": server.posts_last_30d,
                "posts_total": server.total_posts,
                "posts_per_1k": server.posts_per_1k_members or 0.0,
                "authors": server.distinct_authors,
                "threshold": server.reaction_threshold or 0,
                "months_installed": (tenure / DAYS_PER_MONTH) if tenure is not None else 0.0,
            }
        )
    return rows


def cohort_retention(lifespans, now: datetime, max_months: int = 12) -> dict:
    """Share of each join cohort still installed N months later.

    Only elapsed cells are filled; a cohort three months old has no twelve month
    number, and inventing one as 100% would flatter every recent cohort.
    """
    if not lifespans:
        return {"cohorts": [], "sizes": [], "matrix": [], "max_months": max_months}

    now = as_utc(now)
    current_month = month_floor(now)
    grouped = {}
    for lifespan in lifespans:
        grouped.setdefault(month_floor(lifespan.joined_at), []).append(lifespan)

    cohorts = sorted(grouped)
    matrix = []
    sizes = []
    for cohort in cohorts:
        members = grouped[cohort]
        sizes.append(len(members))
        elapsed = months_between(cohort, current_month)
        row = []
        for offset in range(max_months + 1):
            if offset > elapsed:
                row.append(None)
                continue
            checkpoint = add_months(cohort, offset)
            moment = datetime(checkpoint.year, checkpoint.month, 1, tzinfo=timezone.utc)
            retained = sum(1 for ls in members if ls.left_at is None or as_utc(ls.left_at) > moment)
            row.append(share(retained, len(members)))
        matrix.append(row)

    return {"cohorts": cohorts, "sizes": sizes, "matrix": matrix, "max_months": max_months}


def survival_curve(lifespans, now: datetime, max_months: int = 24) -> list:
    """Share of servers still installed N months after joining.

    Each point only counts servers old enough to have reached that age, so the
    tail is not dragged down by servers that joined last week.
    """
    now = as_utc(now)
    points = []
    for offset in range(max_months + 1):
        eligible = 0
        alive = 0
        for lifespan in lifespans:
            reaches = add_months(month_floor(lifespan.joined_at), offset)
            checkpoint = datetime(reaches.year, reaches.month, 1, tzinfo=timezone.utc)
            if checkpoint > now:
                continue
            eligible += 1
            if lifespan.left_at is None or as_utc(lifespan.left_at) > checkpoint:
                alive += 1
        points.append(
            {
                "month": offset,
                "eligible": eligible,
                "alive": alive,
                "survival": share(alive, eligible) if eligible else None,
            }
        )
    return points


def survival_half_life(points):
    """The first age at which survival drops below 50%, or ``None`` if it never does."""
    for point in points:
        if point["survival"] is not None and point["survival"] < 50.0:
            return point["month"]
    return None


# Deliberately absent: survival split by whether a server ever posted. Leaving
# the bot deletes the guild's config row and its messages, so a churned guild
# can never look activated. The split would put every survivor in one arm and
# every departure in the other and draw a flat 100% line, which is survivorship
# bias rendered as a chart rather than a finding.


def reaction_headroom_histogram(buckets, edges=None):
    """How far past its threshold a typical post lands.

    A fleet where everything sits at exactly 1.0x is one whose thresholds are
    doing all the selecting; a long right tail means the threshold is a formality.
    """
    edges = list(edges or [1.0, 1.25, 1.5, 2.0, 3.0, 5.0])
    labels = []
    for index, edge in enumerate(edges):
        if index == len(edges) - 1:
            labels.append(f"{edge:g}x+")
        else:
            labels.append(f"{edge:g} - {edges[index + 1]:g}x")

    counts = [0] * len(labels)
    for bucket in buckets:
        if not bucket.reaction_threshold:
            continue
        ratio = bucket.reaction_count / bucket.reaction_threshold
        if ratio < edges[0]:
            continue
        for index in range(len(edges) - 1, -1, -1):
            if ratio >= edges[index]:
                counts[index] += bucket.posts
                break
    return labels, counts


def median_reaction_multiple(buckets) -> float:
    """Median of ``reaction_count / threshold`` across every recorded post."""
    weighted = sorted(
        (bucket.reaction_count / bucket.reaction_threshold, bucket.posts)
        for bucket in buckets
        if bucket.reaction_threshold
    )
    total = sum(posts for _, posts in weighted)
    if not total:
        return 0.0
    seen = 0
    for ratio, posts in weighted:
        seen += posts
        if seen >= total / 2:
            return ratio
    return weighted[-1][0]


def headline_kpis(dataset) -> list:
    """The numbers that belong on the first page of the report."""
    servers = dataset.servers
    now = dataset.now
    if not servers:
        return []

    member_counts = [s.member_count or 0 for s in servers]
    post_counts = [s.total_posts for s in servers]
    activated = [s for s in servers if s.is_activated]
    live = [s for s in servers if s.is_live]

    lifecycle = lifecycle_by_month(dataset.lifespans, now)
    last_month = lifecycle[-1] if lifecycle else None
    churn = mean([row["churn_rate"] for row in lifecycle[-6:]]) if lifecycle else 0.0

    monthly = monthly_post_summary(dataset.monthly_guild_posts)
    latest = monthly[-1] if monthly else None
    tenures = [t for t in (s.tenure_days(now) for s in servers) if t is not None]

    return [
        {"label": "Servers installed", "value": len(servers), "format": "int",
         "note": f"{len(live):,} posted in the last {LIVE_WINDOW_DAYS} days"},
        {"label": "Members reached", "value": sum(member_counts), "format": "int",
         "note": f"median server has {percentile(member_counts, 50):,.0f} members"},
        {"label": "Hall of Fame posts", "value": sum(post_counts), "format": "int",
         "note": f"{sum(s.posts_last_30d for s in servers):,} in the last {LIVE_WINDOW_DAYS} days"},
        {"label": "Activation rate", "value": share(len(activated), len(servers)), "format": "pct",
         "note": f"{len(activated):,} servers have posted at least once"},
        {"label": "Still live", "value": share(len(live), len(servers)), "format": "pct",
         "note": f"of installed servers, trailing {LIVE_WINDOW_DAYS} days"},
        {"label": "Top 5% share of posts", "value": top_share(post_counts, 0.05), "format": "pct",
         "note": f"Gini {gini(post_counts):.2f} across installed servers"},
        {"label": "Median posts per active server", "value": latest["median_per_server"] if latest else 0.0,
         "format": "float", "note": "in the most recent month"},
        {"label": "Monthly churn", "value": churn, "format": "pct",
         "note": f"6 month average, {last_month['left'] if last_month else 0} left last month"},
        {"label": "Median tenure", "value": percentile(tenures, 50) / DAYS_PER_MONTH, "format": "float",
         "note": "months since install"},
    ]
