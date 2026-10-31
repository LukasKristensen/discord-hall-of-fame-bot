"""The bot's main job, from a reaction to the board, against a real PostgreSQL database.

utils.validate_message is what every reaction ends in. These tests take one message through its life
with Discord faked and the rows real: under the threshold, onto the board, more reactions, under the
threshold again so the post hides, and back. At each step they check both what the board shows and
what the database holds, since the two must not drift apart.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import unittest
from unittest import mock

import utils
from enums import calculation_method_type
from repositories import hall_of_fame_message_repo, server_config_repo

from tests.integration.database import DatabaseTestCase, skip_without_database
from tests.integration.discord_world import Author, Board, Bot, Guild, SourceChannel, post_embed, reaction_event
from tests.test_server_class import build_server

GUILD = 9001
AUTHOR = Author(101)
FANS = [201, 202, 203, 204, 205, 206]
THRESHOLD = 3


@skip_without_database
class ReactionPathTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.guild = Guild(GUILD)
        self.channel = SourceChannel(500, self.guild)
        self.board = Board(600, self.guild)
        self.bot = Bot(self.guild)
        self.config = build_server(guild_id=GUILD, hall_of_fame_channel_id=self.board.id, reaction_threshold=THRESHOLD,
                                   post_due_date=30, hide_hof_post_below_threshold=True,
                                   include_author_in_reaction_calculation=True)
        server_config_repo.insert_server_config(self.connection, GUILD)
        self.message = self.channel.add(1, AUTHOR)

        self.logged = []

        async def record_log(_bot, message, *args, **kwargs):
            self.logged.append(str(message))

        utils.daily_limit_handled_on.clear()
        for target, name, value in ((utils, "create_embed", post_embed), (utils, "logging", record_log)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def react(self, *fans, emoji="🔥", message=None):
        message = message or self.message
        message.react(emoji, *fans)
        await utils.validate_message(reaction_event(message), self.bot, self.connection, self.config)

    async def unreact(self, *fans, emoji="🔥"):
        self.message.unreact(emoji, *fans)
        await utils.validate_message(reaction_event(self.message), self.bot, self.connection, self.config)

    def stored(self, message_id=1):
        return hall_of_fame_message_repo.find_hall_of_fame_message(self.connection, GUILD, self.channel.id, message_id)

    def board_post(self):
        return self.board.posts[self.stored()["hall_of_fame_message_id"]]


class ReachingTheBoardTests(ReactionPathTestCase):
    async def test_under_the_threshold_nothing_is_stored_or_posted(self):
        await self.react(*FANS[:2])

        self.assertIsNone(self.stored())
        self.assertEqual([], self.board.sent)

    async def test_reaching_the_threshold_posts_and_stores_once(self):
        await self.react(*FANS[:3])

        stored = self.stored()
        self.assertEqual((AUTHOR.id, 3, GUILD), (stored["author_id"], stored["reaction_count"], stored["guild_id"]))
        self.assertEqual([stored["hall_of_fame_message_id"]], [post.id for post in self.board.sent])

    async def test_more_reactions_update_the_same_post(self):
        await self.react(*FANS[:3])
        await self.react(*FANS[3:5])

        self.assertEqual(5, self.stored()["reaction_count"])
        self.assertEqual(1, len(self.board.sent))
        self.assertEqual([(1,)], self.rows("SELECT COUNT(*) FROM hall_of_fame_message"))

    async def test_the_board_shows_the_new_count(self):
        await self.react(*FANS[:3])
        await self.react(*FANS[3:5])

        self.assertIn("5", self.board_post().embeds[0].fields[0].value)

    async def test_counts_the_most_used_emoji_by_default(self):
        """With the default method, three different emojis from three members are not three of one."""
        self.message.react("😂", FANS[0])
        self.message.react("❤️", FANS[1])
        await self.react(FANS[2])

        self.assertIsNone(self.stored())

    async def test_unique_members_counts_every_emoji_once_per_member(self):
        self.config.reaction_count_calculation_method = calculation_method_type.UNIQUE_USERS
        self.message.react("😂", FANS[0])
        self.message.react("❤️", FANS[1])
        await self.react(FANS[2])

        self.assertEqual(3, self.stored()["reaction_count"])

    async def test_the_authors_own_reaction_can_be_left_out(self):
        self.config.include_author_in_reaction_calculation = False
        await self.react(AUTHOR.id, *FANS[:2])

        self.assertIsNone(self.stored())

    async def test_another_servers_posts_are_not_touched(self):
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, 99, 800, 9002, 5099, 7, 300, datetime.datetime(2026, 9, 1))
        await self.react(*FANS[:4])

        self.assertEqual([(99, 7)], self.rows("SELECT message_id, reaction_count FROM hall_of_fame_message "
                                              "WHERE guild_id = 9002"))


class HidingAndRestoringTests(ReactionPathTestCase):
    async def test_dropping_under_the_threshold_hides_the_post_but_keeps_the_row(self):
        await self.react(*FANS[:3])
        await self.unreact(FANS[0])

        self.assertEqual([], self.board_post().embeds)
        self.assertIsNotNone(self.stored())

    async def test_without_hiding_the_post_stays_up(self):
        self.config.hide_hof_post_below_threshold = False
        await self.react(*FANS[:3])
        await self.unreact(FANS[0])

        self.assertEqual(1, len(self.board_post().embeds))

    async def test_climbing_back_restores_the_same_post(self):
        await self.react(*FANS[:3])
        await self.unreact(FANS[0])
        await self.react(FANS[0], FANS[3])

        self.assertEqual(1, len(self.board.sent))
        self.assertEqual(1, len(self.board_post().embeds))

    async def test_a_restored_post_stores_its_new_count(self):
        """The board and the leaderboards read the stored count, so it must follow the restored post."""
        await self.react(*FANS[:3])
        await self.unreact(FANS[0])
        await self.react(FANS[0], FANS[3])

        self.assertEqual(4, self.stored()["reaction_count"])


class GateTests(ReactionPathTestCase):
    async def test_an_old_message_is_not_featured(self):
        old = self.channel.add(2, AUTHOR, created_at=datetime.datetime.now(datetime.timezone.utc)
                               - datetime.timedelta(days=40))
        await self.react(*FANS[:5], message=old)

        self.assertIsNone(self.stored(2))

    async def test_an_old_message_already_on_the_board_still_updates(self):
        await self.react(*FANS[:3])
        self.message.created_at -= datetime.timedelta(days=40)
        await self.react(FANS[3])

        self.assertEqual(4, self.stored()["reaction_count"])

    async def test_a_channel_the_bot_cannot_read_is_left_alone(self):
        self.channel.readable = False
        await self.react(*FANS[:5])

        self.assertIsNone(self.stored())

    async def test_a_server_at_its_daily_limit_gets_no_new_posts(self):
        today = self.rows("SELECT DATE_TRUNC('day', NOW())::timestamp")[0][0]
        for message_id in range(1000, 1000 + utils.daily_post_limit):
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, message_id, 500, GUILD, message_id + 5000, 5, 300, today)
        await self.react(*FANS[:4])
        await self.react(FANS[4])

        self.assertIsNone(self.stored())
        announcements = [post for post in self.board.sent if "limit" in post.content]
        self.assertEqual(1, len(announcements), "the limit is announced once a day, not on every reaction")

    async def test_the_limit_counts_only_this_server(self):
        today = self.rows("SELECT DATE_TRUNC('day', NOW())::timestamp")[0][0]
        for message_id in range(1000, 1000 + utils.daily_post_limit):
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, message_id, 800, 9002, message_id + 5000, 5, 300, today)
        await self.react(*FANS[:3])

        self.assertIsNotNone(self.stored())


if __name__ == "__main__":
    unittest.main()
