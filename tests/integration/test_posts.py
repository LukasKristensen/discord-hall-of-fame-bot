"""Storing Hall of Fame posts and the daily limit, against a real PostgreSQL database.

Every post on every board goes through these statements, and the daily limit is checked on every
reaction, so these tests check the rows themselves: what is stored, what an update touches, and which
posts count as today's.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import types
import unittest
from unittest import mock

import utils
from repositories import hall_of_fame_message_repo

from tests.integration.database import DatabaseTestCase, skip_without_database

GUILD = 9001
OTHER_GUILD = 9002
MEMBER, OTHER_MEMBER = 101, 102
CHANNEL = 500
POSTED = datetime.datetime(2026, 9, 1, 12, 0)

COLUMNS = ("message_id", "channel_id", "guild_id", "hall_of_fame_message_id", "reaction_count", "author_id",
           "created_at", "video_link_message_id")


@skip_without_database
class PostsTestCase(DatabaseTestCase):
    def insert(self, message_id, reactions=5, author=MEMBER, guild=GUILD, created_at=POSTED, video=None):
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, message_id, CHANNEL, guild, message_id + 5000, reactions, author, created_at, video)

    def all_posts(self):
        return self.rows(f"SELECT {', '.join(COLUMNS)} FROM hall_of_fame_message ORDER BY message_id")

    def start_of_today(self):
        return self.rows("SELECT DATE_TRUNC('day', NOW())::timestamp")[0][0]


class StoringPostsTests(PostsTestCase):
    def test_stores_every_field(self):
        self.insert(1, reactions=9, video=77)

        self.assertEqual([(1, CHANNEL, GUILD, 5001, 9, MEMBER, POSTED, 77)], self.all_posts())

    def test_finds_a_post_by_server_channel_and_message(self):
        self.insert(1)

        found = hall_of_fame_message_repo.find_hall_of_fame_message(self.connection, GUILD, CHANNEL, 1)
        self.assertEqual(dict(zip(COLUMNS, (1, CHANNEL, GUILD, 5001, 5, MEMBER, POSTED, None))), found)

    def test_finds_nothing_in_the_wrong_server_or_channel(self):
        self.insert(1)

        self.assertIsNone(hall_of_fame_message_repo.find_hall_of_fame_message(self.connection, OTHER_GUILD, CHANNEL, 1))
        self.assertIsNone(hall_of_fame_message_repo.find_hall_of_fame_message(self.connection, GUILD, 999, 1))

    def test_storing_the_same_message_again_updates_it(self):
        """A post that is reposted, for example after it was hidden, must not count twice."""
        self.insert(1, reactions=5)
        self.insert(1, reactions=8)

        self.assertEqual([(1, CHANNEL, GUILD, 5001, 8, MEMBER, POSTED, None)], self.all_posts())

    def test_updating_a_field_changes_only_that_post(self):
        self.insert(1)
        self.insert(2)
        hall_of_fame_message_repo.update_field_for_message(self.connection, GUILD, CHANNEL, 1, "reaction_count", 12)

        self.assertEqual([(1, 12), (2, 5)], self.rows(
            "SELECT message_id, reaction_count FROM hall_of_fame_message ORDER BY message_id"))

    def test_updating_needs_the_right_server_and_channel(self):
        self.insert(1)
        hall_of_fame_message_repo.update_field_for_message(self.connection, OTHER_GUILD, CHANNEL, 1, "reaction_count", 12)
        hall_of_fame_message_repo.update_field_for_message(self.connection, GUILD, 999, 1, "reaction_count", 12)

        self.assertEqual([(5,)], self.rows("SELECT reaction_count FROM hall_of_fame_message"))

    def test_refuses_to_update_a_field_it_does_not_know(self):
        self.insert(1)
        before = self.all_posts()

        with self.assertRaises(ValueError):
            hall_of_fame_message_repo.update_field_for_message(
                self.connection, GUILD, CHANNEL, 1, "reaction_count = 0, author_id", 0)
        self.assertEqual(before, self.all_posts())

    def test_deleting_a_servers_posts_leaves_other_servers_alone(self):
        self.insert(1)
        self.insert(2, guild=OTHER_GUILD)
        hall_of_fame_message_repo.delete_hall_of_fame_messages_for_guild(self.connection, GUILD)

        self.assertEqual([(2,)], self.rows("SELECT message_id FROM hall_of_fame_message"))

    def test_lists_each_author_once(self):
        self.insert(1)
        self.insert(2)
        self.insert(3, author=OTHER_MEMBER)
        self.insert(4, author=OTHER_MEMBER, guild=OTHER_GUILD)

        self.assertEqual({MEMBER, OTHER_MEMBER},
                         set(hall_of_fame_message_repo.find_members_for_guild(self.connection, GUILD)))

    def test_top_posts_are_ordered_by_reactions_and_limited(self):
        for message_id, reactions in ((1, 3), (2, 9), (3, 6), (4, 1)):
            self.insert(message_id, reactions=reactions)
        self.insert(5, reactions=50, guild=OTHER_GUILD)

        top = hall_of_fame_message_repo.find_top_messages_by_reaction_count(self.connection, GUILD, limit=2)
        self.assertEqual([2, 3], [post["message_id"] for post in top])

    def test_counts_a_servers_posts(self):
        self.insert(1)
        self.insert(2)
        self.insert(3, guild=OTHER_GUILD)

        self.assertEqual(2, hall_of_fame_message_repo.count_messages_for_guild(self.connection, GUILD))

    def test_monthly_counts_include_the_start_and_exclude_the_end(self):
        start, end = datetime.datetime(2026, 9, 1), datetime.datetime(2026, 10, 1)
        self.insert(1, created_at=start)
        self.insert(2, created_at=end - datetime.timedelta(seconds=1))
        self.insert(3, created_at=end)
        self.insert(4, created_at=start, guild=OTHER_GUILD)

        counts = hall_of_fame_message_repo.get_monthly_message_counts_by_guild(self.connection, start, end)
        self.assertEqual([{"guild_id": GUILD, "message_count": 2}, {"guild_id": OTHER_GUILD, "message_count": 1}],
                         counts)


class DailyLimitTests(PostsTestCase):
    def test_counts_only_todays_posts(self):
        today = self.start_of_today()
        self.insert(1, created_at=today)
        self.insert(2, created_at=today + datetime.timedelta(hours=1))
        self.insert(3, created_at=today - datetime.timedelta(seconds=1))

        self.assertEqual(2, hall_of_fame_message_repo.guild_message_count_today(self.connection, GUILD))

    def test_counts_only_the_servers_own_posts(self):
        today = self.start_of_today()
        self.insert(1, created_at=today)
        self.insert(2, created_at=today, guild=OTHER_GUILD)

        self.assertEqual(1, hall_of_fame_message_repo.guild_message_count_today(self.connection, GUILD))

    def test_a_server_with_no_posts_has_none_today(self):
        self.assertEqual(0, hall_of_fame_message_repo.guild_message_count_today(self.connection, GUILD))

    def test_post_activity_for_the_setup_check(self):
        today = self.start_of_today()
        self.insert(1, created_at=today - datetime.timedelta(days=3))
        self.insert(2, created_at=today + datetime.timedelta(minutes=5))
        self.insert(3, created_at=today, guild=OTHER_GUILD)

        activity = hall_of_fame_message_repo.get_post_activity(self.connection, GUILD)
        self.assertEqual({"total": 2, "latest": today + datetime.timedelta(minutes=5), "today": 1}, activity)

    def test_post_activity_for_a_server_without_posts(self):
        self.assertEqual({"total": 0, "latest": None, "today": 0},
                         hall_of_fame_message_repo.get_post_activity(self.connection, GUILD))


class PostingTests(PostsTestCase):
    """The bot's own posting code, with the Discord side faked and the database real."""

    async def post(self, message_id=1, author=MEMBER, video_link=None):
        sent = []

        async def send(content=None, **_kwargs):
            sent.append(content)
            return types.SimpleNamespace(id=message_id + 5000 + len(sent))

        async def no_embed(*_args, **_kwargs):
            return None

        async def seven(*_args, **_kwargs):
            return 7

        channel = types.SimpleNamespace(send=send)
        bot = types.SimpleNamespace(get_channel=lambda _channel_id: channel)
        message = types.SimpleNamespace(id=message_id, channel=types.SimpleNamespace(id=CHANNEL),
                                        guild=types.SimpleNamespace(id=GUILD), author=types.SimpleNamespace(id=author))
        with mock.patch.object(utils, "create_embed", no_embed), \
                mock.patch.object(utils, "reaction_count", seven), \
                mock.patch.object(utils, "check_video_extension", lambda _message: video_link):
            await utils.post_hall_of_fame_message(message, bot, self.connection, 600, 5)
        return sent

    async def test_stores_the_post_with_its_author_and_count(self):
        await self.post()

        self.assertEqual([(1, CHANNEL, GUILD, 5002, 7, MEMBER, None)], self.rows(
            "SELECT message_id, channel_id, guild_id, hall_of_fame_message_id, reaction_count, author_id, "
            "video_link_message_id FROM hall_of_fame_message"))

    async def test_stores_the_time_it_was_featured_as_utc(self):
        before = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        await self.post()
        after = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        created_at = self.rows("SELECT created_at FROM hall_of_fame_message")[0][0]
        self.assertTrue(before - datetime.timedelta(seconds=1) <= created_at <= after + datetime.timedelta(seconds=1))

    async def test_a_video_post_stores_both_messages(self):
        sent = await self.post(video_link="https://example.com/clip.mp4")

        # The video goes first, so it gets the first message ID (5002) and the embed the second (5003)
        self.assertEqual("https://example.com/clip.mp4", sent[0])
        self.assertEqual([(5003, 5002)], self.rows(
            "SELECT hall_of_fame_message_id, video_link_message_id FROM hall_of_fame_message"))

    async def test_a_new_post_counts_toward_todays_limit(self):
        await self.post(1)
        await self.post(2)

        self.assertEqual(2, hall_of_fame_message_repo.guild_message_count_today(self.connection, GUILD))


if __name__ == "__main__":
    unittest.main()
