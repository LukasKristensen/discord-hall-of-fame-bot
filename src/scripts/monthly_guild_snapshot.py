from datetime import datetime, timezone
from repositories import hall_of_fame_message_repo, guild_monthly_snapshot_repo

def month_bounds_utc(reference_dt=None):
    now = reference_dt or datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return month_start.date(), month_start, next_month_start

def run_monthly_snapshot(connection, guilds, reference_dt=None):
    month_start_date, month_start_dt, next_month_start_dt = month_bounds_utc(reference_dt)
    captured_at = reference_dt or datetime.now(timezone.utc)

    # single query for all message counts
    message_counts_data = hall_of_fame_message_repo.get_monthly_message_counts_by_guild(
        connection,
        month_start_dt,
        next_month_start_dt,
    )
    message_counts = {row["guild_id"]: row["message_count"] for row in message_counts_data}

    records = []

    for guild in guilds:
        member_count = getattr(guild, "member_count", 0) or 0
        message_count = message_counts.get(guild.id, 0)

        records.append((
            guild.id,
            month_start_date,
            member_count,
            message_count,
            captured_at,
        ))

    guild_monthly_snapshot_repo.upsert_guild_monthly_snapshots_batch(
        connection,
        records
    )
