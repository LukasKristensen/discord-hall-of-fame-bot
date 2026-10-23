"""Cleaning up servers that removed the bot while it was offline, against a real PostgreSQL database.

The cleanup deletes a whole server's data, so these tests check on real rows that the date a server
was first found missing is kept and cleared as it should be, and that only the departed server loses
its data.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import unittest
from unittest import mock

import discord

import events
import utils
from repositories import guild_lifecycle_event_repo, server_config_repo

from tests.fakes import FakeBotWithGuilds, FakeLogGuild
from tests.integration.database import DatabaseTestCase, skip_without_database

NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.timezone.utc)
DEPARTED = 9001
# Enough servers the bot is still in that one missing stays under the share that aborts the cleanup
PRESENT = list(range(9100, 9120))


class FakeResponse:
    def __init__(self, status):
        self.status = status
        self.reason = "test"


@skip_without_database
class RecordMissingGuildsTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        for guild_id in (DEPARTED, *PRESENT):
            server_config_repo.insert_server_config(self.connection, guild_id)

    def missing_since(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT guild_id, missing_since FROM server_configs WHERE missing_since IS NOT NULL")
        rows = dict(cursor.fetchall())
        cursor.close()
        return rows

    def test_marks_a_missing_server_with_the_time_it_was_first_found_missing(self):
        server_config_repo.record_missing_guilds(self.connection, [DEPARTED], NOW)

        self.assertEqual({DEPARTED: NOW}, self.missing_since())

    def test_keeps_the_first_date_while_the_server_stays_missing(self):
        server_config_repo.record_missing_guilds(self.connection, [DEPARTED], NOW)
        later = NOW + datetime.timedelta(days=3)

        returned = server_config_repo.record_missing_guilds(self.connection, [DEPARTED], later)

        self.assertEqual({DEPARTED: NOW}, returned)
        self.assertEqual({DEPARTED: NOW}, self.missing_since())

    def test_clears_the_date_once_the_server_is_back(self):
        server_config_repo.record_missing_guilds(self.connection, [DEPARTED], NOW)

        returned = server_config_repo.record_missing_guilds(self.connection, [], NOW + datetime.timedelta(days=1))

        self.assertEqual({}, returned)
        self.assertEqual({}, self.missing_since())


@skip_without_database
class CleanUpDepartedGuildsTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        for guild_id in (DEPARTED, *PRESENT):
            server_config_repo.insert_server_config(self.connection, guild_id)
            guild_lifecycle_event_repo.insert_guild_lifecycle_event(
                self.connection, guild_id, "JOIN", NOW - datetime.timedelta(days=100))
        self.server_classes = server_config_repo.get_server_classes(self.connection)
        self.bot = FakeBotWithGuilds(PRESENT, guild=FakeLogGuild())

        async def fetch_guild(_guild_id):
            raise discord.Forbidden(FakeResponse(403), "Missing Access")

        self.bot.fetch_guild = fetch_guild
        patcher = mock.patch.object(utils, "recently_logged_messages", utils.ExpiringSet(ttl_seconds=600))
        patcher.start()
        self.addCleanup(patcher.stop)

    def configured_guilds(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT guild_id FROM server_configs")
        guild_ids = {row[0] for row in cursor.fetchall()}
        cursor.close()
        return guild_ids

    async def clean_up(self, now):
        return await events.clean_up_departed_guilds(self.bot, self.connection, self.server_classes, now=now)

    async def test_deletes_only_the_departed_server_once_the_grace_period_is_over(self):
        await self.clean_up(NOW)
        self.assertIn(DEPARTED, self.configured_guilds())

        later = NOW + datetime.timedelta(days=events.departed_guild_grace_days)
        self.assertEqual([DEPARTED], await self.clean_up(later))

        self.assertEqual(set(PRESENT), self.configured_guilds())
        self.assertEqual("LEAVE", guild_lifecycle_event_repo.get_latest_event_type(self.connection, DEPARTED))
        self.assertEqual("JOIN", guild_lifecycle_event_repo.get_latest_event_type(self.connection, PRESENT[0]))

    async def test_a_server_that_comes_back_starts_the_grace_period_over(self):
        await self.clean_up(NOW)
        self.bot.guilds.append(type(self.bot.guilds[0])(DEPARTED))
        await self.clean_up(NOW + datetime.timedelta(days=1))
        self.bot.guilds.pop()

        self.assertEqual([], await self.clean_up(NOW + datetime.timedelta(days=events.departed_guild_grace_days)))
        self.assertIn(DEPARTED, self.configured_guilds())


if __name__ == "__main__":
    unittest.main()
