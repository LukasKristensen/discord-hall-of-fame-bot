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
import datetime
import unittest
from contextlib import asynccontextmanager
from unittest import mock

import discord

import concurrency
import events
import utils
from caches import ExpiringSet
from repositories import guild_lifecycle_event_repo, server_config_repo, server_user_repo

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

    async def test_a_stalled_report_does_not_hold_a_slot(self):
        """With one slot, a report that hangs while holding it would keep every other item waiting."""
        started = []

        async def worker(item):
            started.append(item)
            if item == 0:
                raise RuntimeError("broken")

        report_may_finish = asyncio.Event()

        async def on_error(_item, _error):
            await report_may_finish.wait()

        batch = asyncio.create_task(concurrency.run_in_batches(range(3), worker, limit=1, on_error=on_error))
        await asyncio.sleep(0.01)

        self.assertEqual([0, 1, 2], started)
        report_may_finish.set()
        await batch

    async def test_a_report_that_hangs_is_abandoned_like_the_work(self):
        async def worker(_item):
            raise RuntimeError("broken")

        async def on_error(_item, _error):
            await asyncio.sleep(30)

        outcome = await asyncio.wait_for(
            concurrency.run_in_batches([1], worker, limit=1, timeout=0.02, on_error=on_error), 1)

        self.assertEqual(1, len(outcome.failed))

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
        self.borrowed = []
        self.returned = []

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

        self.patch(server_config_repo, "get_guild_ids_with_leaderboard", self.guilds_with_leaderboards)
        self.patch(utils, "update_leaderboard", self.record_update)
        self.patch(utils, "update_user_database", self.noop_async)
        self.patch(events, "check_write_permissions_to_hall_of_fame_channel", self.noop_async)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch(self, target, name, replacement):
        patcher = mock.patch.object(target, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def guilds_with_leaderboards(self, _connection):
        self.leaderboard_lookups += 1
        return {guild_id for guild_id in self.guild_ids if guild_id not in self.without_leaderboards}

    leaderboard_lookups = 0

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

    @asynccontextmanager
    async def borrow_connection(self):
        """Stands in for the pool, handing out a fresh connection and noting when it comes back."""
        connection = FakeConnection()
        self.borrowed.append(connection)
        try:
            yield connection
        finally:
            self.returned.append(connection)

    async def run_daily_task(self):
        await events.daily_task(self.bot, self.connection, self.server_classes, dev_testing=True,
                                borrow_connection=self.borrow_connection)

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

    async def test_looks_up_which_servers_have_a_leaderboard_once_rather_than_per_server(self):
        await self.run_daily_task()

        self.assertEqual(1, self.leaderboard_lookups)

    async def test_gives_every_server_a_connection_of_its_own(self):
        """On a shared connection one server's database error aborts the transaction of the rest."""
        used = {}

        async def record_connection(connection, _bot, server_class):
            used[server_class.guild_id] = connection

        self.patch(utils, "update_leaderboard", record_connection)
        await self.run_daily_task()

        self.assertEqual(self.guild_ids, sorted(used))
        self.assertEqual(len(self.guild_ids), len({id(connection) for connection in used.values()}))
        self.assertNotIn(self.connection, used.values())

    async def test_gives_back_every_connection_even_when_a_server_fails(self):
        async def fail_on_one(_connection, _bot, server_class):
            if server_class.guild_id == 202:
                raise RuntimeError("database went away")

        self.patch(utils, "update_leaderboard", fail_on_one)
        await self.run_daily_task()

        self.assertEqual(len(self.guild_ids), len(self.borrowed))
        self.assertEqual(sorted(map(id, self.borrowed)), sorted(map(id, self.returned)))

    async def test_limits_how_long_each_statement_may_run_and_resets_it_afterwards(self):
        """A blocking query stalls the event loop, so only the database can stop one that hangs."""
        seen = []

        async def record_queries_so_far(connection, _bot, _server_class):
            seen.append(list(connection.queries))

        self.patch(utils, "update_leaderboard", record_queries_so_far)
        await self.run_daily_task()

        for queries_during_update, connection in zip(seen, self.borrowed):
            self.assertEqual(["SET statement_timeout = %s"], queries_during_update)
            self.assertEqual("RESET statement_timeout", connection.queries[-1])
        self.assertEqual([(events.daily_task_statement_timeout_ms,)], self.borrowed[0].parameters[:1])

    async def test_rolls_back_a_failed_server_before_resetting_its_timeout(self):
        async def fail(_connection, _bot, _server_class):
            raise RuntimeError("canceling statement due to statement timeout")

        self.patch(utils, "update_leaderboard", fail)
        await self.run_daily_task()

        for connection in self.borrowed:
            self.assertEqual(1, connection.rollbacks)
            self.assertEqual("RESET statement_timeout", connection.queries[-1])


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

        warned = mock.patch.object(events, "permission_warnings_sent", {})
        warned.start()
        self.addCleanup(warned.stop)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def build_bot(self, missing_permissions_for=(), hanging_for=()):
        checked = self.checked
        test = self

        class Channel:
            def __init__(self, guild_id):
                self.id = guild_id + 1000
                self.guild_id = guild_id
                self.topic = None

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
                return True
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

    async def test_every_rebuild_runs_under_a_statement_timeout(self):
        """A rebuild blocks the event loop, so only the database can stop one that stalls."""
        queries_at_first_rebuild = []

        def note_queries(_guild_id):
            if not queries_at_first_rebuild:
                queries_at_first_rebuild.extend(self.connection.queries)

        self.patch_rebuild(side_effect=note_queries)
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual(["SET statement_timeout = %s"], queries_at_first_rebuild)
        self.assertEqual([(utils.user_stats_statement_timeout_ms,)], self.connection.parameters[:1])
        self.assertEqual("RESET statement_timeout", self.connection.queries[-1])

    async def test_a_cancelled_rebuild_does_not_stop_the_sweep(self):
        def time_out_on_one(guild_id):
            if guild_id == 230:
                raise RuntimeError("canceling statement due to statement timeout")

        self.patch_rebuild(side_effect=time_out_on_one)
        await utils.update_user_database(self.bot, self.connection)

        self.assertEqual(self.guild_ids, self.rebuilt)
        self.assertEqual("RESET statement_timeout", self.connection.queries[-1])


class FakeResponse:
    """What discord.HTTPException reads from a failed request."""

    def __init__(self, status):
        self.status = status
        self.reason = "test"


class DepartedGuildCleanupTests(unittest.IsolatedAsyncioTestCase):
    """Deleting a server's data cannot be undone, so every guard against a false positive is checked."""

    NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.timezone.utc)

    def setUp(self):
        # Twenty servers the bot is in, so one or two missing stay under the share that aborts the cleanup
        self.present = list(range(200, 220))
        self.departed = 999
        self.bot = FakeBotWithGuilds(self.present, guild=FakeLogGuild())
        self.fetch_results = {}
        self.fetched = []
        self.bot.fetch_guild = self.fetch_guild
        self.server_classes = {guild_id: build_server(guild_id=guild_id)
                               for guild_id in self.present + [self.departed]}
        self.connection = FakeConnection()
        self.missing_since = {self.departed: self.NOW - datetime.timedelta(days=events.departed_guild_grace_days)}
        self.recorded = []
        self.deleted = []
        self.lifecycle = []
        self.latest_event = "JOIN"

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

        self.patch(server_config_repo, "record_missing_guilds", self.record_missing)
        self.patch(utils, "delete_database_context", lambda guild_id, _connection: self.deleted.append(guild_id))
        self.patch(guild_lifecycle_event_repo, "get_latest_event_type",
                   lambda _connection, _guild_id: self.latest_event)
        self.patch(guild_lifecycle_event_repo, "insert_guild_lifecycle_event",
                   lambda _connection, guild_id, event_type, occurred_at:
                   self.lifecycle.append((guild_id, event_type, occurred_at)))

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch(self, target, name, replacement):
        patcher = mock.patch.object(target, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def record_missing(self, _connection, missing_guild_ids, now):
        self.recorded.append((list(missing_guild_ids), now))
        return {guild_id: since for guild_id, since in self.missing_since.items() if guild_id in missing_guild_ids}

    async def fetch_guild(self, guild_id):
        self.fetched.append(guild_id)
        result = self.fetch_results.get(guild_id, discord.Forbidden(FakeResponse(403), "Missing Access"))
        if isinstance(result, BaseException):
            raise result
        return result

    async def clean_up(self):
        return await events.clean_up_departed_guilds(self.bot, self.connection, self.server_classes, now=self.NOW)

    def logged(self):
        return " ".join(message for channel in self.bot.guild.channels.values() for message in channel.sent)

    async def test_deletes_a_server_missing_for_the_whole_grace_period_that_discord_confirms_is_gone(self):
        deleted = await self.clean_up()

        self.assertEqual([self.departed], deleted)
        self.assertEqual([self.departed], self.deleted)
        self.assertNotIn(self.departed, self.server_classes)

    async def test_a_deleted_server_unknown_to_discord_counts_as_gone(self):
        self.fetch_results[self.departed] = discord.NotFound(FakeResponse(404), "Unknown Guild")

        self.assertEqual([self.departed], await self.clean_up())

    async def test_records_the_leave_for_the_server_statistics_dated_when_it_was_first_missing(self):
        await self.clean_up()

        self.assertEqual([(self.departed, "LEAVE", self.missing_since[self.departed])], self.lifecycle)

    async def test_records_no_leave_without_a_join_to_match_it(self):
        for latest_event in (None, "LEAVE"):
            self.lifecycle.clear()
            self.server_classes[self.departed] = build_server(guild_id=self.departed)
            self.latest_event = latest_event
            await self.clean_up()

            self.assertEqual([], self.lifecycle)

    async def test_keeps_a_server_that_has_not_been_missing_long_enough(self):
        self.missing_since[self.departed] = self.NOW - datetime.timedelta(
            days=events.departed_guild_grace_days, seconds=-1)

        self.assertEqual([], await self.clean_up())
        self.assertEqual([], self.deleted)
        self.assertEqual([], self.fetched)
        self.assertIn(self.departed, self.server_classes)

    async def test_keeps_a_server_found_missing_for_the_first_time(self):
        del self.missing_since[self.departed]

        self.assertEqual([], await self.clean_up())
        self.assertIn(f"Could not find server {self.departed}", self.logged())

    async def test_keeps_a_server_discord_still_gives_the_bot_access_to(self):
        """A server missing from the cache but returned by the API means the cache is wrong, not that it left."""
        self.fetch_results[self.departed] = object()

        self.assertEqual([], await self.clean_up())
        self.assertEqual([], self.deleted)
        self.assertIn("still gives the bot access", self.logged())

    async def test_keeps_a_server_when_discord_fails_to_answer(self):
        self.fetch_results[self.departed] = discord.HTTPException(FakeResponse(503), "Service Unavailable")

        self.assertEqual([], await self.clean_up())
        self.assertEqual([], self.deleted)
        self.assertIn(self.departed, self.server_classes)

    async def test_keeps_a_server_when_discord_does_not_answer_in_time(self):
        async def hang(_guild_id):
            await asyncio.sleep(30)

        self.bot.fetch_guild = hang
        self.patch(events, "departed_guild_fetch_timeout_seconds", 0.02)

        self.assertEqual([], await self.clean_up())
        self.assertEqual([], self.deleted)

    async def test_deletes_nothing_when_too_many_servers_are_missing_at_once(self):
        """Discord leaving servers out of the guild list must not look like a wave of servers leaving."""
        self.bot.guilds = self.bot.guilds[:5]
        for guild_id in self.present:
            self.missing_since[guild_id] = self.missing_since[self.departed]

        self.assertEqual([], await self.clean_up())
        self.assertEqual([], self.deleted)
        self.assertEqual([], self.recorded)
        self.assertIn("Not cleaning up any server today", self.logged())

    async def test_deletes_nothing_when_the_bot_sees_no_guilds_at_all(self):
        self.bot.guilds = []

        self.assertEqual([], await self.clean_up())
        self.assertEqual([], self.recorded)

    async def test_deletes_nothing_when_nothing_is_missing(self):
        del self.server_classes[self.departed]

        self.assertEqual([], await self.clean_up())

    async def test_clears_the_missing_dates_when_nothing_is_missing(self):
        """A server that came back has to start its grace period over, even when no other is missing."""
        del self.server_classes[self.departed]
        await self.clean_up()

        self.assertEqual([([], self.NOW)], self.recorded)

    async def test_only_marks_the_servers_that_are_missing(self):
        await self.clean_up()

        self.assertEqual([([self.departed], self.NOW)], self.recorded)

    async def test_one_failing_server_does_not_stop_the_others(self):
        other = 998
        self.server_classes[other] = build_server(guild_id=other)
        self.missing_since[other] = self.missing_since[self.departed]

        def fail_on_one(guild_id, _connection):
            if guild_id == other:
                raise RuntimeError("database went away")
            self.deleted.append(guild_id)

        self.patch(utils, "delete_database_context", fail_on_one)

        self.assertEqual([self.departed], await self.clean_up())
        self.assertIn(other, self.server_classes)
        self.assertEqual(1, self.connection.rollbacks)

    async def test_the_daily_task_skips_the_cleanup_on_the_development_bot(self):
        cleanups = []

        async def record_cleanup(*_args, **_kwargs):
            cleanups.append(True)

        async def noop(*_args, **_kwargs):
            return None

        self.patch(events, "clean_up_departed_guilds", record_cleanup)
        self.patch(server_config_repo, "get_guild_ids_with_leaderboard", lambda _connection: set())
        self.patch(utils, "update_user_database", noop)
        self.patch(events, "check_write_permissions_to_hall_of_fame_channel", noop)

        await events.daily_task(self.bot, self.connection, self.server_classes, dev_testing=True,
                                borrow_connection=None)
        self.assertEqual([], cleanups)

        await events.daily_task(self.bot, self.connection, self.server_classes, dev_testing=False,
                                borrow_connection=None)
        self.assertEqual([True], cleanups)



class StartupJoinRecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_join_that_cannot_be_recorded_does_not_stop_the_startup(self):
        """A server added while the bot was offline is still set up when recording its join fails."""
        logged = []

        async def record_log(_bot, message, *args, **kwargs):
            logged.append(str(message))

        def fail(*_args):
            raise RuntimeError("database went away")

        guild = mock.Mock(id=4242)
        guild.name = "Offline Server"
        guild.me.guild_permissions.manage_channels = False
        bot = mock.Mock(guilds=[guild])
        connection = FakeConnection()
        with mock.patch.object(events.server_config_repo, "check_if_guild_exists", lambda *_args: False), \
                mock.patch.object(events, "record_guild_join", fail), \
                mock.patch.object(events.utils, "logging", record_log):
            found = await events.check_for_new_server_classes(bot, connection)

        self.assertEqual({}, found)
        self.assertEqual(1, connection.rollbacks)
        self.assertTrue(any("Could not record the join" in entry for entry in logged))




class StartupSetupFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_server_that_cannot_be_set_up_is_logged_and_skipped(self):
        logged = []

        async def record_log(_bot, message, *args, **kwargs):
            logged.append(str(message))

        async def fail(*_args):
            raise RuntimeError("Missing Permissions")

        guild = mock.Mock(id=4242)
        guild.me.guild_permissions.manage_channels = True
        with mock.patch.object(events.server_config_repo, "check_if_guild_exists", lambda *_args: False), \
                mock.patch.object(events, "record_guild_join", lambda *_args: None), \
                mock.patch.object(events.utils, "create_database_context", fail), \
                mock.patch.object(events.utils, "logging", record_log):
            found = await events.check_for_new_server_classes(mock.Mock(guilds=[guild]), FakeConnection())

        self.assertEqual({}, found)
        self.assertTrue(any("Failed to create the database context" in entry for entry in logged))



if __name__ == "__main__":
    unittest.main()
