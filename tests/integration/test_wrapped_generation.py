"""Generating Hall of Fame Wrapped, against a real PostgreSQL database.

hof_wrapped.main reads a server's posts, counts who reacted to whom, and saves a Wrapped row per
member. It is switched off at the moment, so these tests are what says it still works before it is
switched back on for December. Discord is faked; the rows it reads and writes are real.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import json
import unittest
from unittest import mock

import hof_wrapped
import utils
from constants import version
from repositories import hall_of_fame_message_repo, hof_wrapped_repo, server_config_repo

from tests.integration.database import DatabaseTestCase, database_url, skip_without_database
from tests.integration.discord_world import Author, Bot, Guild, SourceChannel

FIRST, SECOND = 9001, 9002
ALICE, BOB, CAROL, DAVE = Author(101), Author(102), Author(103), Author(104)
IN_THE_YEAR = datetime.datetime(version.WRAPPED_YEAR, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)
YEAR_BEFORE = datetime.datetime(version.WRAPPED_YEAR - 1, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)


@skip_without_database
class WrappedGenerationTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.first = Guild(FIRST)
        self.first_channel = SourceChannel(500, self.first)
        self.second = Guild(SECOND)
        self.second_channel = SourceChannel(800, self.second)
        self.bot = Bot(self.first, self.second)
        for guild_id in (FIRST, SECOND):
            server_config_repo.insert_server_config(self.connection, guild_id)

        # FIRST: Alice has two posts, Bob one. Carol reacts but never posts, so she has no Wrapped
        self.feature(self.first_channel, 1, ALICE, {"🔥": [BOB.id, CAROL.id]})
        self.feature(self.first_channel, 2, ALICE, {"😂": [BOB.id]})
        self.feature(self.first_channel, 3, BOB, {"🔥": [ALICE.id]})
        # A post from the year before, which this year's Wrapped leaves out
        self.feature(self.first_channel, 4, BOB, {"🔥": [ALICE.id]}, created_at=YEAR_BEFORE)
        # SECOND: only Dave
        self.feature(self.second_channel, 10, DAVE, {"🔥": [ALICE.id]})

        settings = {"dsn": database_url(), "options": f"-c search_path={self.schema} -c TimeZone=UTC"}
        for target, name, value in ((hof_wrapped.environment, "database_settings", lambda: settings),
                                    (hof_wrapped, "users", {}), (hof_wrapped, "total_hall_of_fame_posts", 0),
                                    (hof_wrapped, "rankings", None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def feature(self, channel, message_id, author, reactions, created_at=IN_THE_YEAR):
        message = channel.add(message_id, author, created_at=created_at)
        for emoji, user_ids in reactions.items():
            message.react(emoji, *user_ids)
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, message_id, channel.id, channel.guild.id, 5000 + message_id, 2, author.id,
            created_at.replace(tzinfo=None))

    async def generate(self, guild_id):
        with mock.patch("builtins.print"):
            await hof_wrapped.main(guild_id, self.bot, 3, self.connection)

    def wrapped(self, guild_id, user_id):
        row = hof_wrapped_repo.get_hof_wrapped(self.connection, guild_id, user_id, version.WRAPPED_YEAR)
        if row is None:
            return None
        for column in ("fan_of_users", "users_fans", "most_used_channels", "most_used_emojis", "user_ranks"):
            row[column] = json.loads(row[column])
        return row

    async def test_saves_a_wrapped_for_every_member_who_was_featured(self):
        await self.generate(FIRST)

        self.assertEqual({ALICE.id, BOB.id}, {row[0] for row in self.rows(
            "SELECT user_id FROM hof_wrapped WHERE guild_id = %s", (FIRST,))})

    async def test_counts_each_members_posts_this_year(self):
        await self.generate(FIRST)

        self.assertEqual(2, self.wrapped(FIRST, ALICE.id)["hof_message_posts"])
        self.assertEqual(1, self.wrapped(FIRST, BOB.id)["hof_message_posts"])

    async def test_records_who_reacted_to_whom(self):
        """Carol never posted, so she is not counted as anyone's fan."""
        await self.generate(FIRST)

        self.assertEqual({str(BOB.id): 2}, self.wrapped(FIRST, ALICE.id)["users_fans"])
        self.assertEqual({str(BOB.id): 1}, self.wrapped(FIRST, ALICE.id)["fan_of_users"])
        self.assertEqual({str(ALICE.id): 1}, self.wrapped(FIRST, BOB.id)["users_fans"])

    async def test_records_the_channels_posts_came_from(self):
        await self.generate(FIRST)

        self.assertEqual({str(self.first_channel.id): 2}, self.wrapped(FIRST, ALICE.id)["most_used_channels"])

    async def test_ranks_the_members(self):
        await self.generate(FIRST)

        self.assertEqual(1, self.wrapped(FIRST, ALICE.id)["user_ranks"]["hallOfFameMessagePosts"])
        self.assertEqual(2, self.wrapped(FIRST, BOB.id)["user_ranks"]["hallOfFameMessagePosts"])

    async def test_a_second_server_gets_only_its_own_members(self):
        """Wrapped runs server after server in one process, so nothing may carry over between them."""
        await self.generate(FIRST)
        await self.generate(SECOND)

        self.assertEqual({DAVE.id}, {row[0] for row in self.rows(
            "SELECT user_id FROM hof_wrapped WHERE guild_id = %s", (SECOND,))})
        self.assertEqual(1, self.wrapped(SECOND, DAVE.id)["hof_message_posts"])

    async def test_the_first_server_is_unchanged_by_the_second(self):
        await self.generate(FIRST)
        before = self.rows("SELECT * FROM hof_wrapped WHERE guild_id = %s ORDER BY user_id", (FIRST,))
        await self.generate(SECOND)

        self.assertEqual(before, self.rows("SELECT * FROM hof_wrapped WHERE guild_id = %s ORDER BY user_id", (FIRST,)))

    async def test_generating_again_replaces_rather_than_duplicates(self):
        await self.generate(FIRST)
        await self.generate(FIRST)

        self.assertEqual([(2,)], self.rows("SELECT COUNT(*) FROM hof_wrapped WHERE guild_id = %s", (FIRST,)))
        self.assertEqual(2, self.wrapped(FIRST, ALICE.id)["hof_message_posts"])

    async def test_a_deleted_member_is_not_generated_again(self):
        """After deleting their data the member's posts have no author, so Wrapped has nobody to credit."""
        hall_of_fame_message_repo.remove_author(self.connection, ALICE.id)
        await self.generate(FIRST)

        self.assertIsNone(self.wrapped(FIRST, ALICE.id))


if __name__ == "__main__":
    unittest.main()
