import datetime
import unittest
from datetime import timezone
from unittest import mock

from tests.fakes import FakeBotWithGuilds, FakeConnection, FakeLogGuild

import utils
from caches import ExpiringSet
from repositories import server_user_repo


class MonthlyWindowStartTests(unittest.TestCase):
    def test_reaches_back_thirty_days(self):
        now = datetime.datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(datetime.datetime(2026, 8, 9, 12, 0), utils.monthly_window_start(now))

    def test_is_naive_so_it_compares_against_a_timestamp_column(self):
        # created_at is TIMESTAMP without a time zone, holding UTC wall time
        self.assertIsNone(utils.monthly_window_start().tzinfo)

    def test_uses_the_clock_when_no_time_is_given(self):
        before = datetime.datetime.now(timezone.utc).replace(tzinfo=None)
        window = utils.monthly_window_start()
        self.assertLessEqual(window, before - datetime.timedelta(days=29, hours=23))


class RebuildUserStatsForGuildTests(unittest.TestCase):
    def setUp(self):
        self.connection = FakeConnection()
        self.window = datetime.datetime(2026, 8, 9, 12, 0)

    def execute_call(self):
        return self.connection.cursors[0].executed[0]

    def test_uses_a_single_statement(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, 200, self.window)
        self.assertEqual(1, len(self.connection.queries))

    def test_passes_the_guild_and_window_as_parameters(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, 200, self.window)
        query, params = self.execute_call()

        self.assertEqual({"guild_id": 200, "monthly_window_start": self.window}, params)
        self.assertNotIn("200", query)

    def test_aggregates_and_ranks_in_the_database(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, 200, self.window)
        query, _ = self.execute_call()

        self.assertIn("COUNT(*)", query)
        self.assertIn("SUM(reaction_count)", query)
        self.assertEqual(4, query.count("ROW_NUMBER() OVER"))

    def test_writes_all_eight_stat_columns(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, 200, self.window)
        query, _ = self.execute_call()

        for column in server_user_repo.ALLOWED_STAT_FIELDS:
            self.assertIn(column, query, f"{column} is not written by the rebuild")

    def test_updates_rows_that_already_exist(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, 200, self.window)
        query, _ = self.execute_call()

        self.assertIn("ON CONFLICT (user_id, guild_id) DO UPDATE", query)

    def test_skips_guilds_that_have_no_configuration(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, 200, self.window)
        query, _ = self.execute_call()

        self.assertIn("EXISTS (SELECT 1 FROM server_configs", query)


class UpdateUserDatabaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = FakeBotWithGuilds([200, 201, 202], guild=FakeLogGuild())
        self.connection = FakeConnection()
        self.rebuilt = []

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch_rebuild(self, side_effect=None):
        def record(connection, guild_id, window_start):
            self.rebuilt.append(guild_id)
            if side_effect:
                side_effect(guild_id)

        patcher = mock.patch.object(server_user_repo, "rebuild_user_stats_for_guild", side_effect=record)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    async def test_rebuilds_every_guild_once(self):
        self.patch_rebuild()
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual([200, 201, 202], self.rebuilt)

    async def test_shares_one_window_across_every_guild(self):
        mocked = self.patch_rebuild()
        await utils.update_user_database(self.bot, self.connection)

        windows = {call.args[2] for call in mocked.call_args_list}
        self.assertEqual(1, len(windows), "each guild should be measured against the same window")

    async def test_one_failing_guild_does_not_stop_the_others(self):
        def fail_on_the_second(guild_id):
            if guild_id == 201:
                raise RuntimeError("deadlock detected")

        self.patch_rebuild(side_effect=fail_on_the_second)
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual([200, 201, 202], self.rebuilt)

    async def test_reports_a_failing_guild(self):
        def fail_on_the_second(guild_id):
            if guild_id == 201:
                raise RuntimeError("deadlock detected")

        self.patch_rebuild(side_effect=fail_on_the_second)
        await utils.update_user_database(self.bot, self.connection)

        logged = " ".join(self.bot.guild.get_channel(1344070396575617085).sent)
        self.assertIn("deadlock detected", logged)
        self.assertIn("201", logged)

    async def test_does_not_read_the_history_into_the_bot(self):
        self.patch_rebuild()
        with mock.patch.object(utils.hall_of_fame_message_repo, "get_all_hall_of_fame_messages_for_guild") as reader:
            await utils.update_user_database(self.bot, self.connection)

        reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
