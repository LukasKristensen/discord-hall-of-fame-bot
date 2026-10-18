"""Post times are UTC whatever time zone the database server uses, against a real PostgreSQL database.

created_at is a TIMESTAMP without a time zone, and PostgreSQL turns the UTC time the bot writes into
the session's local time before storing it. The bot reads it back as UTC, so every session it opens
has to run in UTC. These tests open sessions the way the bot does, and one the way it used to, which
shows what goes wrong without the setting.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import types
import unittest
from unittest import mock

import psycopg2

import environment
import utils
from repositories import hall_of_fame_message_repo

from tests.integration.database import DatabaseTestCase, database_url, skip_without_database

FEATURED = datetime.datetime(2026, 10, 18, 23, 30, tzinfo=datetime.timezone.utc)
NON_UTC_SESSION = "-c TimeZone=Europe/Copenhagen"


@skip_without_database
class TimeZoneTests(DatabaseTestCase):
    def connect(self, options):
        """A second session on this test's schema, opened with the given startup options"""
        connection = psycopg2.connect(database_url(), options=options)
        self.addCleanup(connection.close)
        cursor = connection.cursor()
        cursor.execute(f"SET search_path TO {self.schema}")
        cursor.close()
        connection.commit()
        return connection

    async def post(self, connection, message_id=1, featured=FEATURED):
        """Feature a message through the bot's own posting code, at a fixed moment"""
        async def send(*_args, **_kwargs):
            return types.SimpleNamespace(id=message_id + 5000)

        async def no_embed(*_args, **_kwargs):
            return None

        async def five(*_args, **_kwargs):
            return 5

        class FixedDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return featured if tz is not None else featured.replace(tzinfo=None)

        channel = types.SimpleNamespace(send=send)
        bot = types.SimpleNamespace(get_channel=lambda _channel_id: channel)
        message = types.SimpleNamespace(id=message_id, channel=types.SimpleNamespace(id=500),
                                        guild=types.SimpleNamespace(id=9001), author=types.SimpleNamespace(id=101))
        with mock.patch.object(utils, "create_embed", no_embed), \
                mock.patch.object(utils, "reaction_count", five), \
                mock.patch.object(utils, "check_video_extension", lambda _message: None), \
                mock.patch.object(utils.datetime, "datetime", FixedDatetime):
            await utils.post_hall_of_fame_message(message, bot, connection, 600, 5)

    def stored(self, message_id=1):
        return self.rows("SELECT created_at FROM hall_of_fame_message WHERE message_id = %s", (message_id,))[0][0]

    def test_the_bots_sessions_run_in_utc(self):
        connection = self.connect(environment.DATABASE_SESSION_OPTIONS)
        cursor = connection.cursor()
        cursor.execute("SHOW TimeZone")

        self.assertEqual("UTC", cursor.fetchone()[0])

    async def test_a_post_is_stored_at_its_utc_time(self):
        await self.post(self.connect(environment.DATABASE_SESSION_OPTIONS))

        self.assertEqual(FEATURED.replace(tzinfo=None), self.stored())

    async def test_without_the_setting_a_local_session_shifts_the_time(self):
        """What happened before: the same post, stored two hours later in a Copenhagen session."""
        await self.post(self.connect(NON_UTC_SESSION))

        self.assertEqual(FEATURED.replace(tzinfo=None) + datetime.timedelta(hours=2), self.stored())

    async def test_the_daily_limit_counts_the_utc_day(self):
        """A post at 23:30 UTC belongs to that UTC day, even where it is already the next day locally."""
        connection = self.connect(environment.DATABASE_SESSION_OPTIONS)
        today = connection.cursor()
        today.execute("SELECT DATE_TRUNC('day', NOW())")
        start_of_today = today.fetchone()[0]
        today.close()
        connection.commit()
        late_yesterday = start_of_today - datetime.timedelta(minutes=30)
        await self.post(connection, message_id=1, featured=late_yesterday)
        await self.post(connection, message_id=2, featured=start_of_today + datetime.timedelta(minutes=30))

        self.assertEqual(1, hall_of_fame_message_repo.guild_message_count_today(connection, 9001))


if __name__ == "__main__":
    unittest.main()
