"""Tests for the pacing of the daily maintenance sweep.

The daily task runs once per server the bot is in, so it is the part of the bot whose cost grows
directly with how many servers there are. Three properties matter and are checked here: every
server is handled exactly once, no single server can stall the rest, and no more than a fixed
number of servers are in flight at a time.

The correctness of the statistics themselves is checked alongside the pacing, because pacing work
is exactly the kind of change that can quietly drop a server or measure two servers against
different windows.
"""

import asyncio
import unittest
from unittest import mock

import concurrency
import events
import utils
from caches import ExpiringSet
from repositories import server_config_repo, server_user_repo

from tests.fakes import FakeBotWithGuilds, FakeConnection, FakeLogGuild
from tests.test_server_class import build_server


class ConcurrencyTracker:
    """A worker that remembers what it was given and how much of it ran at once."""

    def __init__(self, delay=0):
        self.delay = delay
        self.handled = []
        self.in_flight = 0
        self.peak_in_flight = 0

    async def __call__(self, item):
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            else:
                await asyncio.sleep(0)
            self.handled.append(item)
        finally:
            self.in_flight -= 1


class RunInBatchesTests(unittest.IsolatedAsyncioTestCase):
    async def test_handles_every_item_exactly_once(self):
        worker = ConcurrencyTracker()
        outcome = await concurrency.run_in_batches(range(20), worker, limit=4)

        self.assertEqual(sorted(worker.handled), list(range(20)))
        self.assertEqual(20, len(outcome.completed))

    async def test_never_exceeds_the_limit(self):
        worker = ConcurrencyTracker(delay=0.01)
        await concurrency.run_in_batches(range(20), worker, limit=4)

        self.assertEqual(4, worker.peak_in_flight)

    async def test_a_limit_of_one_runs_them_in_order(self):
        worker = ConcurrencyTracker(delay=0.001)
        await concurrency.run_in_batches(range(5), worker, limit=1)

        self.assertEqual([0, 1, 2, 3, 4], worker.handled)
        self.assertEqual(1, worker.peak_in_flight)

    async def test_does_nothing_without_items(self):
        worker = ConcurrencyTracker()
        outcome = await concurrency.run_in_batches([], worker, limit=4)

        self.assertEqual([], worker.handled)
        self.assertEqual(0, len(outcome))

    async def test_a_failing_item_does_not_stop_the_others(self):
        async def worker(item):
            if item == 2:
                raise RuntimeError("that one is broken")

        outcome = await concurrency.run_in_batches(range(5), worker, limit=2)

        self.assertEqual([0, 1, 3, 4], sorted(outcome.completed))
        self.assertEqual([2], [item for item, _ in outcome.failed])

    async def test_a_failing_item_is_reported(self):
        reported = []

        async def worker(item):
            raise RuntimeError(f"{item} is broken")

        async def on_error(item, error):
            reported.append((item, str(error)))

        await concurrency.run_in_batches([7], worker, limit=2, on_error=on_error)

        self.assertEqual([(7, "7 is broken")], reported)

    async def test_a_failing_report_does_not_stop_the_batch(self):
        """Reporting goes over the same connection that just broke, so it can fail too."""
        async def worker(item):
            if item == 1:
                raise RuntimeError("broken")

        async def on_error(_item, _error):
            raise RuntimeError("the log channel is unreachable as well")

        outcome = await concurrency.run_in_batches(range(4), worker, limit=2, on_error=on_error)

        self.assertEqual([0, 2, 3], sorted(outcome.completed))

    async def test_abandons_an_item_that_hangs(self):
        async def worker(item):
            if item == 1:
                await asyncio.sleep(10)

        outcome = await concurrency.run_in_batches(range(3), worker, limit=3, timeout=0.02)

        self.assertEqual([1], outcome.timed_out)
        self.assertEqual([0, 2], sorted(outcome.completed))

    async def test_a_hanging_item_does_not_stop_the_others(self):
        handled = []

        async def worker(item):
            if item == 0:
                await asyncio.sleep(10)
            handled.append(item)

        await concurrency.run_in_batches(range(4), worker, limit=4, timeout=0.02)

        self.assertEqual([1, 2, 3], sorted(handled))

    async def test_the_timeout_starts_when_the_item_does(self):
        """An item waiting for a free slot must not be charged for the wait."""
        handled = []

        async def worker(item):
            await asyncio.sleep(0.03)
            handled.append(item)

        outcome = await concurrency.run_in_batches(range(4), worker, limit=1, timeout=0.1)

        self.assertEqual([0, 1, 2, 3], handled)
        self.assertEqual([], outcome.timed_out)

    async def test_reports_a_timeout_as_a_failure(self):
        reported = []

        async def worker(_item):
            await asyncio.sleep(10)

        async def on_error(item, error):
            reported.append((item, type(error)))

        outcome = await concurrency.run_in_batches([5], worker, limit=1, timeout=0.02, on_error=on_error)

        self.assertEqual(1, len(reported))
        self.assertTrue(issubclass(reported[0][1], asyncio.TimeoutError))
        self.assertEqual([5], outcome.timed_out)


class DailyTaskLeaderboardTests(unittest.IsolatedAsyncioTestCase):
    """The leaderboard sweep, which is the part of the daily task that talks to Discord."""

    def setUp(self):
        self.guild_ids = [200, 201, 202, 203, 204, 205, 206]
        self.bot = FakeBotWithGuilds(self.guild_ids, guild=FakeLogGuild())
        self.connection = FakeConnection()
        self.server_classes = {
            guild_id: build_server(guild_id=guild_id, hall_of_fame_channel_id=guild_id + 1000)
            for guild_id in self.guild_ids
        }
        self.updated = []
        self.in_flight = 0
        self.peak_in_flight = 0

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

        self.patch(server_config_repo, "get_parameter_value", self.leaderboard_is_set_up)
        self.patch(utils, "update_leaderboard", self.record_update)
        self.patch(utils, "update_user_database", self.noop_async)
        self.patch(events, "check_write_permissions_to_hall_of_fame_channel", self.noop_async)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch(self, target, name, replacement):
        patcher = mock.patch.object(target, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def leaderboard_is_set_up(self, _connection, guild_id, parameter):
        self.assertEqual("leaderboard_setup", parameter)
        return guild_id not in self.without_leaderboards

    without_leaderboards = ()

    async def noop_async(self, *args, **kwargs):
        return None

    async def record_update(self, _connection, _bot, server_class):
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.005)
            self.updated.append(server_class.guild_id)
        finally:
            self.in_flight -= 1

    async def run_daily_task(self):
        await events.daily_task(self.bot, self.connection, self.server_classes, dev_testing=True)

    async def test_updates_every_server_exactly_once(self):
        await self.run_daily_task()

        self.assertEqual(self.guild_ids, sorted(self.updated))

    async def test_keeps_the_number_of_servers_in_flight_bounded(self):
        await self.run_daily_task()

        self.assertLessEqual(self.peak_in_flight, events.daily_task_concurrency)

    async def test_does_more_than_one_server_at_a_time(self):
        """Serial updates are what the pacing replaced, so a peak of one would be a regression."""
        await self.run_daily_task()

        self.assertGreater(self.peak_in_flight, 1)

    async def test_skips_servers_without_a_leaderboard(self):
        self.without_leaderboards = (201, 203)
        await self.run_daily_task()

        self.assertEqual([200, 202, 204, 205, 206], sorted(self.updated))

    async def test_skips_servers_the_bot_has_left(self):
        self.server_classes[999] = build_server(guild_id=999)
        await self.run_daily_task()

        self.assertNotIn(999, self.updated)
        self.assertEqual(self.guild_ids, sorted(self.updated))

    async def test_one_failing_server_does_not_stop_the_others(self):
        async def fail_on_one(_connection, _bot, server_class):
            if server_class.guild_id == 202:
                raise RuntimeError("channel is gone")
            self.updated.append(server_class.guild_id)

        self.patch(utils, "update_leaderboard", fail_on_one)
        await self.run_daily_task()

        self.assertEqual([200, 201, 203, 204, 205, 206], sorted(self.updated))

    async def test_one_hanging_server_does_not_stop_the_others(self):
        async def hang_on_one(_connection, _bot, server_class):
            if server_class.guild_id == 202:
                await asyncio.sleep(30)
            self.updated.append(server_class.guild_id)

        self.patch(utils, "update_leaderboard", hang_on_one)
        self.patch(events, "daily_task_guild_timeout_seconds", 0.02)
        await self.run_daily_task()

        self.assertEqual([200, 201, 203, 204, 205, 206], sorted(self.updated))

    async def test_reports_a_hanging_server(self):
        async def hang_on_one(_connection, _bot, server_class):
            if server_class.guild_id == 202:
                await asyncio.sleep(30)

        self.patch(utils, "update_leaderboard", hang_on_one)
        self.patch(events, "daily_task_guild_timeout_seconds", 0.02)
        await self.run_daily_task()

        logged = " ".join(self.bot.guild.get_channel(1344070396575617085).sent)
        self.assertIn("Timed out updating leaderboard for server 202", logged)

    async def test_still_rebuilds_the_statistics_after_the_leaderboards(self):
        order = []

        async def record_leaderboard(_connection, _bot, server_class):
            order.append(("leaderboard", server_class.guild_id))

        async def record_stats(*_args, **_kwargs):
            order.append(("stats", None))

        self.patch(utils, "update_leaderboard", record_leaderboard)
        self.patch(utils, "update_user_database", record_stats)
        await self.run_daily_task()

        self.assertIn(("stats", None), order)
        self.assertEqual(("stats", None), order[-1])


class DailyTaskPermissionSweepTests(unittest.IsolatedAsyncioTestCase):
    """The permission sweep runs per server too, so it is paced the same way."""

    def setUp(self):
        self.guild_ids = [200, 201, 202, 203, 204, 205]
        self.server_classes = {guild_id: build_server(guild_id=guild_id) for guild_id in self.guild_ids}
        self.checked = []
        self.in_flight = 0
        self.peak_in_flight = 0

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def build_bot(self, missing_permissions_for=(), hanging_for=()):
        checked = self.checked
        test = self

        class Channel:
            def __init__(self, guild_id):
                self.id = guild_id + 1000
                self.guild_id = guild_id

            def permissions_for(self, _member):
                from tests.fakes import FakePermissions
                if self.guild_id in missing_permissions_for:
                    return FakePermissions(send_messages=False)
                return FakePermissions()

        class Guild:
            def __init__(self, guild_id):
                self.id = guild_id
                self.name = f"Server {guild_id}"
                self.me = object()

            def get_channel(self, _channel_id):
                return Channel(self.id)

        class Bot:
            def __init__(self):
                self.guilds = [Guild(guild_id) for guild_id in test.guild_ids]

            def get_guild(self, guild_id):
                return Guild(guild_id) if guild_id in test.guild_ids else None

        async def send_message(_bot, guild, _content):
            test.in_flight += 1
            test.peak_in_flight = max(test.peak_in_flight, test.in_flight)
            try:
                if guild.id in hanging_for:
                    await asyncio.sleep(30)
                await asyncio.sleep(0.005)
                checked.append(guild.id)
            finally:
                test.in_flight -= 1

        patcher = mock.patch.object(utils, "send_message_to_highest_prio_channel", send_message)
        patcher.start()
        self.addCleanup(patcher.stop)
        return Bot()

    async def test_warns_every_server_that_is_missing_a_permission(self):
        bot = self.build_bot(missing_permissions_for=self.guild_ids)
        await events.check_write_permissions_to_hall_of_fame_channel(bot, self.server_classes)

        self.assertEqual(self.guild_ids, sorted(self.checked))

    async def test_says_nothing_to_a_server_with_every_permission(self):
        bot = self.build_bot(missing_permissions_for=())
        await events.check_write_permissions_to_hall_of_fame_channel(bot, self.server_classes)

        self.assertEqual([], self.checked)

    async def test_keeps_the_number_of_servers_in_flight_bounded(self):
        bot = self.build_bot(missing_permissions_for=self.guild_ids)
        await events.check_write_permissions_to_hall_of_fame_channel(bot, self.server_classes)

        self.assertLessEqual(self.peak_in_flight, events.daily_task_concurrency)

    async def test_one_hanging_server_does_not_stop_the_others(self):
        bot = self.build_bot(missing_permissions_for=self.guild_ids, hanging_for=(202,))
        with mock.patch.object(events, "daily_task_guild_timeout_seconds", 0.05):
            await events.check_write_permissions_to_hall_of_fame_channel(bot, self.server_classes)

        self.assertEqual([200, 201, 203, 204, 205], sorted(self.checked))


class UserStatisticsSweepTests(unittest.IsolatedAsyncioTestCase):
    """Pacing the sweep must not change which servers are rebuilt or what they are measured against."""

    def setUp(self):
        self.guild_ids = list(range(200, 260))
        self.bot = FakeBotWithGuilds(self.guild_ids, guild=FakeLogGuild())
        self.connection = FakeConnection()

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch_rebuild(self, side_effect=None):
        self.rebuilt = []
        self.windows = []

        def record(_connection, guild_id, window_start):
            self.rebuilt.append(guild_id)
            self.windows.append(window_start)
            if side_effect:
                side_effect(guild_id)

        patcher = mock.patch.object(server_user_repo, "rebuild_user_stats_for_guild", record)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_rebuilds_every_server_exactly_once(self):
        self.patch_rebuild()
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual(self.guild_ids, self.rebuilt)

    async def test_measures_every_server_against_the_same_window(self):
        """Ranks are compared across servers, so a drifting window would skew the monthly counts."""
        self.patch_rebuild()
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual(1, len(set(self.windows)))

    async def test_the_window_reaches_back_thirty_days(self):
        self.patch_rebuild()
        await utils.update_user_database(self.bot, self.connection)

        expected = utils.monthly_window_start()
        self.assertAlmostEqual(0, abs((expected - self.windows[0]).total_seconds()), delta=5)

    async def test_hands_control_back_during_the_sweep(self):
        """A run of synchronous rebuilds must not hold the loop for the whole sweep."""
        interruptions = []

        async def other_work():
            for _ in range(10):
                await asyncio.sleep(0)
                interruptions.append(len(self.rebuilt))

        self.patch_rebuild()
        await asyncio.gather(utils.update_user_database(self.bot, self.connection), other_work())

        progressed_midway = [count for count in interruptions if 0 < count < len(self.guild_ids)]
        self.assertTrue(progressed_midway, "the sweep never yielded while it still had servers left")

    async def test_one_failing_server_does_not_stop_the_others(self):
        def fail_on_one(guild_id):
            if guild_id == 230:
                raise RuntimeError("deadlock detected")

        self.patch_rebuild(side_effect=fail_on_one)
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual(self.guild_ids, self.rebuilt)

    async def test_reports_what_it_managed_to_rebuild(self):
        def fail_on_one(guild_id):
            if guild_id == 230:
                raise RuntimeError("deadlock detected")

        self.patch_rebuild(side_effect=fail_on_one)
        await utils.update_user_database(self.bot, self.connection)

        logged = " ".join(self.bot.guild.get_channel(1344070396575617085).sent)
        self.assertIn(f"{len(self.guild_ids) - 1} rebuilt, 1 failed", logged)

    async def test_a_failing_server_is_still_named(self):
        def fail_on_one(guild_id):
            if guild_id == 230:
                raise RuntimeError("deadlock detected")

        self.patch_rebuild(side_effect=fail_on_one)
        await utils.update_user_database(self.bot, self.connection)

        logged = " ".join(self.bot.guild.get_channel(1344070396575617085).sent)
        self.assertIn("230", logged)
        self.assertIn("deadlock detected", logged)


if __name__ == "__main__":
    unittest.main()
