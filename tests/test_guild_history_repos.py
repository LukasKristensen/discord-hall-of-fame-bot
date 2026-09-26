"""Tests for the two tables recording how the bot's servers change over time.

``guild_lifecycle_event`` is an append-only log of joins and leaves, and
``guild_monthly_snapshot`` records a server's size and activity once a month. Together they are what
the growth and retention figures are computed from, so what matters here is that a join and a leave
cannot be confused for one another and that a month is always treated as a half-open range.
"""

import datetime
import unittest

from repositories import guild_lifecycle_event_repo, guild_monthly_snapshot_repo

from tests.fakes import FakeConnection

MARCH = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
APRIL = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)


class InsertGuildLifecycleEventTests(unittest.TestCase):
    def test_records_a_join(self):
        connection = FakeConnection()
        guild_lifecycle_event_repo.insert_guild_lifecycle_event(connection, 200, "JOIN", MARCH)

        self.assertEqual([(200, "JOIN", MARCH)], connection.parameters)

    def test_records_a_leave(self):
        connection = FakeConnection()
        guild_lifecycle_event_repo.insert_guild_lifecycle_event(connection, 200, "LEAVE", MARCH)

        self.assertEqual([(200, "LEAVE", MARCH)], connection.parameters)

    def test_rejects_an_event_that_is_neither(self):
        """The column has a check constraint, and this is the guard that keeps it from tripping."""
        with self.assertRaises(ValueError):
            guild_lifecycle_event_repo.insert_guild_lifecycle_event(FakeConnection(), 200, "KICKED", MARCH)

    def test_rejects_a_lowercase_event(self):
        with self.assertRaises(ValueError):
            guild_lifecycle_event_repo.insert_guild_lifecycle_event(FakeConnection(), 200, "join", MARCH)

    def test_writes_nothing_when_the_event_is_rejected(self):
        connection = FakeConnection()
        with self.assertRaises(ValueError):
            guild_lifecycle_event_repo.insert_guild_lifecycle_event(connection, 200, "KICKED", MARCH)

        self.assertEqual([], connection.queries)
        self.assertEqual(0, connection.commits)

    def test_commits_an_accepted_event(self):
        connection = FakeConnection()
        guild_lifecycle_event_repo.insert_guild_lifecycle_event(connection, 200, "JOIN", MARCH)

        self.assertEqual(1, connection.commits)


class MonthlyJoinLeaveCountTests(unittest.TestCase):
    def test_maps_a_month_to_its_joins_and_leaves(self):
        connection = FakeConnection(rows=[(MARCH, 12, 3)])
        counts = guild_lifecycle_event_repo.get_monthly_join_leave_counts(connection, MARCH, APRIL)

        self.assertEqual([{"month_start": MARCH, "joined_count": 12, "left_count": 3}], counts)

    def test_maps_every_month_it_is_given(self):
        connection = FakeConnection(rows=[(MARCH, 12, 3), (APRIL, 8, 5)])
        counts = guild_lifecycle_event_repo.get_monthly_join_leave_counts(connection, MARCH, APRIL)

        self.assertEqual([12, 8], [month["joined_count"] for month in counts])

    def test_returns_nothing_for_a_period_with_no_events(self):
        connection = FakeConnection(rows=[])
        self.assertEqual([], guild_lifecycle_event_repo.get_monthly_join_leave_counts(connection, MARCH, APRIL))

    def test_takes_the_period_as_a_half_open_range(self):
        connection = FakeConnection(rows=[])
        guild_lifecycle_event_repo.get_monthly_join_leave_counts(connection, MARCH, APRIL)

        self.assertIn("occurred_at >= %s AND occurred_at < %s", connection.queries[0])
        self.assertEqual([(MARCH, APRIL)], connection.parameters)

    def test_reads_the_months_oldest_first(self):
        connection = FakeConnection(rows=[])
        guild_lifecycle_event_repo.get_monthly_join_leave_counts(connection, MARCH, APRIL)

        self.assertIn("ORDER BY month_start ASC", connection.queries[0])


class ActiveServersTests(unittest.TestCase):
    def test_counts_the_servers_the_bot_was_in(self):
        connection = FakeConnection(row=(140,))
        self.assertEqual(140, guild_lifecycle_event_repo.get_active_servers_as_of(connection, MARCH))

    def test_counts_none_before_the_first_event(self):
        connection = FakeConnection(row=None)
        self.assertEqual(0, guild_lifecycle_event_repo.get_active_servers_as_of(connection, MARCH))

    def test_counts_a_server_as_active_only_while_joins_outnumber_leaves(self):
        """A server that left and rejoined has several events, and must still count once."""
        connection = FakeConnection(row=(0,))
        guild_lifecycle_event_repo.get_active_servers_as_of(connection, MARCH)

        self.assertIn("GROUP BY guild_id", connection.queries[0])
        self.assertIn("net_presence", connection.queries[0])

    def test_maps_every_month_of_the_timeseries(self):
        connection = FakeConnection(rows=[(MARCH, 120), (APRIL, 140)])
        series = guild_lifecycle_event_repo.get_active_servers_timeseries(connection, MARCH, APRIL)

        self.assertEqual([{"month_start": MARCH, "active_servers": 120},
                          {"month_start": APRIL, "active_servers": 140}], series)

    def test_returns_an_empty_timeseries_without_history(self):
        connection = FakeConnection(rows=[])
        self.assertEqual([], guild_lifecycle_event_repo.get_active_servers_timeseries(connection, MARCH, APRIL))


class UpsertGuildMonthlySnapshotTests(unittest.TestCase):
    def test_writes_the_size_and_activity_of_one_server_for_one_month(self):
        connection = FakeConnection()
        guild_monthly_snapshot_repo.upsert_guild_monthly_snapshot(
            connection, 200, datetime.date(2026, 3, 1), 450, 32, MARCH)

        self.assertEqual([(200, datetime.date(2026, 3, 1), 450, 32, MARCH)], connection.parameters)

    def test_replaces_a_snapshot_taken_earlier_in_the_month(self):
        """The snapshot runs daily and keeps one row per month, the newest reading winning."""
        connection = FakeConnection()
        guild_monthly_snapshot_repo.upsert_guild_monthly_snapshot(
            connection, 200, datetime.date(2026, 3, 1), 450, 32, MARCH)

        self.assertIn("ON CONFLICT (guild_id, month_start) DO UPDATE", connection.queries[0])

    def test_writes_nothing_for_an_empty_batch(self):
        connection = FakeConnection()
        guild_monthly_snapshot_repo.upsert_guild_monthly_snapshots_batch(connection, [])

        self.assertEqual([], connection.queries)
        self.assertEqual(0, connection.commits)


class MonthlySnapshotReadTests(unittest.TestCase):
    def test_maps_the_members_of_every_server(self):
        connection = FakeConnection(rows=[(200, 450), (201, 120)])
        members = guild_monthly_snapshot_repo.get_monthly_members_per_server(
            connection, datetime.date(2026, 3, 1))

        self.assertEqual([{"guild_id": 200, "member_count": 450},
                          {"guild_id": 201, "member_count": 120}], members)

    def test_maps_the_messages_of_every_server(self):
        connection = FakeConnection(rows=[(200, 32)])
        messages = guild_monthly_snapshot_repo.get_monthly_messages_per_server(
            connection, datetime.date(2026, 3, 1))

        self.assertEqual([{"guild_id": 200, "message_count": 32}], messages)

    def test_reads_one_month(self):
        connection = FakeConnection(rows=[])
        guild_monthly_snapshot_repo.get_monthly_members_per_server(connection, datetime.date(2026, 3, 1))

        self.assertEqual([(datetime.date(2026, 3, 1),)], connection.parameters)

    def test_reports_activity_relative_to_server_size(self):
        connection = FakeConnection(rows=[(200, 32, 450, 71.11)])
        activity = guild_monthly_snapshot_repo.get_monthly_messages_vs_members(
            connection, datetime.date(2026, 3, 1))

        self.assertEqual(71.11, activity[0]["messages_per_1k_members"])
        self.assertEqual(450, activity[0]["member_count"])

    def test_does_not_divide_by_an_empty_server(self):
        connection = FakeConnection(rows=[(200, 0, 0, 0)])
        activity = guild_monthly_snapshot_repo.get_monthly_messages_vs_members(
            connection, datetime.date(2026, 3, 1))

        self.assertEqual(0, activity[0]["messages_per_1k_members"])
        self.assertIn("WHEN member_count > 0", connection.queries[0])

    def test_returns_nothing_for_a_month_that_was_never_captured(self):
        connection = FakeConnection(rows=[])
        self.assertEqual([], guild_monthly_snapshot_repo.get_monthly_messages_vs_members(
            connection, datetime.date(2026, 3, 1)))


if __name__ == "__main__":
    unittest.main()
