"""The monthly server snapshot and the developer statistics report, against a real PostgreSQL database.

These read across every server at once, so a mistake shows up as a wrong number in a report rather
than an error. The tests use a handful of servers with hand-counted posts, joins and leaves.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import types
import unittest

from repositories import guild_lifecycle_event_repo, guild_monthly_snapshot_repo, hall_of_fame_message_repo, \
    server_config_repo
from scripts import monthly_guild_snapshot
from stats import queries

from tests.integration.database import DatabaseTestCase, skip_without_database

UTC = datetime.timezone.utc
BUSY, QUIET, GONE = 9001, 9002, 9003
OCTOBER = datetime.datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
OCTOBER_START = datetime.date(2026, 10, 1)


@skip_without_database
class SnapshotTestCase(DatabaseTestCase):
    def post(self, message_id, guild, created_at, author=101, reactions=5):
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, message_id, 500, guild, 5000 + message_id, reactions, author, created_at)

    def event(self, guild, event_type, when):
        guild_lifecycle_event_repo.insert_guild_lifecycle_event(self.connection, guild, event_type, when)


class MonthlySnapshotTests(SnapshotTestCase):
    def setUp(self):
        super().setUp()
        self.post(1, BUSY, datetime.datetime(2026, 10, 1, 0, 0))
        self.post(2, BUSY, datetime.datetime(2026, 10, 31, 23, 59))
        self.post(3, BUSY, datetime.datetime(2026, 11, 1, 0, 0))
        self.post(4, BUSY, datetime.datetime(2026, 9, 30, 23, 59))
        self.post(5, QUIET, datetime.datetime(2026, 10, 10))
        self.guilds = [types.SimpleNamespace(id=BUSY, member_count=120), types.SimpleNamespace(id=QUIET, member_count=8),
                       types.SimpleNamespace(id=GONE, member_count=None)]

    def snapshot(self):
        return {row[0]: row[1:] for row in self.rows(
            "SELECT guild_id, month_start, member_count, message_count FROM guild_monthly_snapshot")}

    def test_records_each_servers_members_and_posts_for_the_month(self):
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds, OCTOBER)

        self.assertEqual({BUSY: (OCTOBER_START, 120, 2), QUIET: (OCTOBER_START, 8, 1), GONE: (OCTOBER_START, 0, 0)},
                         self.snapshot())

    def test_running_again_in_the_month_updates_instead_of_adding(self):
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds, OCTOBER)
        self.post(6, QUIET, datetime.datetime(2026, 10, 20))
        self.guilds[1].member_count = 9
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds, OCTOBER + datetime.timedelta(days=1))

        self.assertEqual((OCTOBER_START, 9, 2), self.snapshot()[QUIET])
        self.assertEqual([(3,)], self.rows("SELECT COUNT(*) FROM guild_monthly_snapshot"))

    def test_a_new_month_adds_a_row(self):
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds, OCTOBER)
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds, datetime.datetime(2026, 11, 2, tzinfo=UTC))

        self.assertEqual([(6,)], self.rows("SELECT COUNT(*) FROM guild_monthly_snapshot"))

    def test_december_rolls_over_to_january(self):
        self.post(7, BUSY, datetime.datetime(2026, 12, 31, 23, 0))
        self.post(8, BUSY, datetime.datetime(2027, 1, 1, 0, 0))
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds[:1],
                                                    datetime.datetime(2026, 12, 5, tzinfo=UTC))

        self.assertEqual((datetime.date(2026, 12, 1), 120, 1), self.snapshot()[BUSY])

    def test_the_monthly_report_reads(self):
        monthly_guild_snapshot.run_monthly_snapshot(self.connection, self.guilds, OCTOBER)

        self.assertEqual([{"guild_id": BUSY, "member_count": 120}, {"guild_id": QUIET, "member_count": 8},
                          {"guild_id": GONE, "member_count": 0}],
                         guild_monthly_snapshot_repo.get_monthly_members_per_server(self.connection, OCTOBER_START))
        self.assertEqual(BUSY, guild_monthly_snapshot_repo.get_monthly_messages_per_server(
            self.connection, OCTOBER_START)[0]["guild_id"])
        per_member = guild_monthly_snapshot_repo.get_monthly_messages_vs_members(self.connection, OCTOBER_START)
        self.assertEqual(QUIET, per_member[0]["guild_id"], "1 post for 8 members beats 2 for 120")


class LifecycleTests(SnapshotTestCase):
    def setUp(self):
        super().setUp()
        self.event(BUSY, "JOIN", datetime.datetime(2026, 8, 3, tzinfo=UTC))
        self.event(QUIET, "JOIN", datetime.datetime(2026, 9, 10, tzinfo=UTC))
        self.event(GONE, "JOIN", datetime.datetime(2026, 9, 12, tzinfo=UTC))
        self.event(GONE, "LEAVE", datetime.datetime(2026, 10, 2, tzinfo=UTC))

    def test_the_latest_event_of_a_server(self):
        self.assertEqual("LEAVE", guild_lifecycle_event_repo.get_latest_event_type(self.connection, GONE))
        self.assertEqual("JOIN", guild_lifecycle_event_repo.get_latest_event_type(self.connection, BUSY))
        self.assertIsNone(guild_lifecycle_event_repo.get_latest_event_type(self.connection, 4242))

    def test_joins_and_leaves_per_month(self):
        counts = guild_lifecycle_event_repo.get_monthly_join_leave_counts(
            self.connection, datetime.datetime(2026, 8, 1, tzinfo=UTC), datetime.datetime(2026, 11, 1, tzinfo=UTC))

        self.assertEqual([(1, 0), (2, 0), (0, 1)], [(row["joined_count"], row["left_count"]) for row in counts])

    def test_servers_with_the_bot_at_a_moment(self):
        def active(year, month, day):
            return guild_lifecycle_event_repo.get_active_servers_as_of(
                self.connection, datetime.datetime(year, month, day, tzinfo=UTC))

        self.assertEqual(1, active(2026, 9, 1))
        self.assertEqual(3, active(2026, 9, 30))
        self.assertEqual(2, active(2026, 10, 5))

    def test_servers_with_the_bot_month_by_month(self):
        series = guild_lifecycle_event_repo.get_active_servers_timeseries(
            self.connection, datetime.datetime(2026, 8, 1, tzinfo=UTC), datetime.datetime(2026, 11, 1, tzinfo=UTC))

        self.assertEqual([1, 3, 2], [row["active_servers"] for row in series])


class StatisticsReportTests(SnapshotTestCase):
    NOW = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    def setUp(self):
        super().setUp()
        for guild in (BUSY, QUIET):
            server_config_repo.insert_server_config(self.connection, guild)
        server_config_repo.update_server_config_param(BUSY, "server_member_count", 40, self.connection)
        server_config_repo.update_server_config_param(BUSY, "reaction_threshold", 4, self.connection)
        # BUSY: three authors, one post migrated without an author or a real date
        self.post(1, BUSY, datetime.datetime(2026, 10, 12, 18, 0), author=101, reactions=6)
        self.post(2, BUSY, datetime.datetime(2026, 10, 13, 18, 30), author=102, reactions=4)
        self.post(3, BUSY, datetime.datetime(2026, 7, 1, 9, 0), author=103, reactions=9)
        self.post(4, BUSY, datetime.datetime(1970, 1, 1), author=0, reactions=5)
        # The latest snapshot with a member count is preferred over the count stored when the bot joined
        guild_monthly_snapshot_repo.upsert_guild_monthly_snapshot(self.connection, BUSY, datetime.date(2026, 9, 1), 70, 1,
                                                                  self.NOW)
        guild_monthly_snapshot_repo.upsert_guild_monthly_snapshot(self.connection, BUSY, datetime.date(2026, 10, 1), 0, 2,
                                                                  self.NOW)
        self.event(BUSY, "JOIN", datetime.datetime(2026, 6, 1, tzinfo=UTC))

    def dataset(self):
        return queries.load_dataset(self.connection, self.NOW)

    def busy(self):
        return next(server for server in self.dataset().servers if server.guild_id == BUSY)

    def test_server_totals(self):
        busy = self.busy()

        self.assertEqual((4, 2, 3), (busy.total_posts, busy.posts_last_30d, busy.distinct_authors))
        self.assertEqual(datetime.datetime(2026, 7, 1, 9, 0, tzinfo=UTC), busy.first_post_at)
        self.assertEqual(datetime.datetime(2026, 10, 13, 18, 30, tzinfo=UTC), busy.last_post_at)

    def test_member_count_comes_from_the_latest_snapshot_that_has_one(self):
        self.assertEqual(70, self.busy().member_count)

    def test_a_server_without_posts_is_listed_with_zeros(self):
        quiet = next(server for server in self.dataset().servers if server.guild_id == QUIET)

        self.assertEqual((0, 0, 0, None), (quiet.total_posts, quiet.posts_last_30d, quiet.distinct_authors,
                                           quiet.first_post_at))

    def test_posts_and_authors_per_month_leave_out_the_placeholder_date(self):
        dataset = self.dataset()

        self.assertEqual({(datetime.date(2026, 7, 1), 1), (datetime.date(2026, 10, 1), 2)},
                         {(row.month, row.posts) for row in dataset.monthly_guild_posts})
        self.assertEqual({(datetime.date(2026, 7, 1), 1), (datetime.date(2026, 10, 1), 2)},
                         {(row.month, row.authors) for row in dataset.monthly_authors})

    def test_posting_rhythm_by_weekday_and_hour(self):
        """12 October 2026 is a Monday and the 13th a Tuesday, both at 18:00 UTC."""
        cells = {(cell.weekday, cell.hour): cell.posts for cell in self.dataset().posting_rhythm}

        self.assertEqual(1, cells[(0, 18)])
        self.assertEqual(1, cells[(1, 18)])
        self.assertEqual(3, sum(cells.values()))

    def test_reaction_headroom_over_the_current_threshold(self):
        buckets = {(row.reaction_count, row.reaction_threshold): row.posts for row in self.dataset().reaction_headroom}

        self.assertEqual({(6, 4): 1, (4, 4): 1, (9, 4): 1}, buckets)

    def test_the_join_history_becomes_a_lifespan(self):
        self.assertTrue(self.dataset().lifespans)

    def test_a_database_without_the_join_history_still_reports(self):
        self.execute("DROP TABLE guild_lifecycle_event")

        dataset = self.dataset()
        self.assertEqual(2, len(dataset.servers))


if __name__ == "__main__":
    unittest.main()
