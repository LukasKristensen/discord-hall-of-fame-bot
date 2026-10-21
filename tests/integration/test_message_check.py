"""Why isn't this on the board?, against a real PostgreSQL database.

The answer has to match what validate_message did with the message. So each test takes a message
through the real reaction path first, with the rows real, and then asks the explanation about it.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
from unittest import mock

import message_check
import utils
from repositories import hall_of_fame_message_repo, opt_out_repo, server_config_repo

from tests.integration.database import DatabaseTestCase, skip_without_database
from tests.integration.discord_world import Author, Board, Bot, Guild, SourceChannel, post_embed, reaction_event
from tests.test_server_class import build_server

GUILD = 9101
AUTHOR = Author(111)
FANS = [211, 212, 213, 214]
THRESHOLD = 3


@skip_without_database
class MessageCheckTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.guild = Guild(GUILD)
        self.channel = SourceChannel(510, self.guild)
        self.board = Board(610, self.guild)
        self.bot = Bot(self.guild)
        self.config = build_server(guild_id=GUILD, hall_of_fame_channel_id=self.board.id, reaction_threshold=THRESHOLD,
                                   post_due_date=30, hide_hof_post_below_threshold=True)
        server_config_repo.insert_server_config(self.connection, GUILD)
        self.message = self.channel.add(1, AUTHOR)

        async def ignore_log(*_args, **_kwargs):
            pass

        utils.daily_limit_handled_on.clear()
        for name, value in (("create_embed", post_embed), ("logging", ignore_log)):
            patcher = mock.patch.object(utils, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def react(self, *fans, message=None):
        message = message or self.message
        message.react("🔥", *fans)
        await utils.validate_message(reaction_event(message), self.bot, self.connection, self.config)

    async def unreact(self, *fans):
        self.message.unreact("🔥", *fans)
        await utils.validate_message(reaction_event(self.message), self.bot, self.connection, self.config)

    async def explain(self, message=None, asked_by=FANS[0]):
        return await message_check.explain(message or self.message, asked_by, self.bot, self.connection, self.config)

    def stored(self, message_id=1):
        return hall_of_fame_message_repo.find_hall_of_fame_message(self.connection, GUILD, self.channel.id, message_id)


class MatchesTheReactionPathTests(MessageCheckTestCase):
    async def test_under_the_threshold(self):
        await self.react(*FANS[:2])
        verdict = await self.explain()

        self.assertIsNone(self.stored())
        self.assertEqual(message_check.BELOW_THRESHOLD, verdict.reason)
        self.assertIn("2 of the 3", verdict.text)

    async def test_on_the_board_links_to_the_stored_post(self):
        await self.react(*FANS[:3])
        verdict = await self.explain()

        post_id = self.stored()["hall_of_fame_message_id"]
        self.assertIn(post_id, self.board.posts)
        self.assertEqual(message_check.ALREADY_POSTED, verdict.reason)
        self.assertIn(f"/channels/{GUILD}/{self.board.id}/{post_id}", verdict.text)

    async def test_hidden_after_dropping_below(self):
        await self.react(*FANS[:3])
        await self.unreact(FANS[0])
        verdict = await self.explain()

        self.assertEqual([], self.board.posts[self.stored()["hall_of_fame_message_id"]].embeds)
        self.assertEqual(message_check.HIDDEN, verdict.reason)

    async def test_an_opted_out_author_is_neither_posted_nor_named(self):
        opt_out_repo.set_opted_out(self.connection, AUTHOR.id, True)
        await self.react(*FANS[:3])
        verdict = await self.explain()

        self.assertIsNone(self.stored())
        self.assertEqual(message_check.CANNOT_FEATURE, verdict.reason)
        self.assertNotIn(str(AUTHOR.id), verdict.text)

    async def test_the_author_is_told_it_was_their_choice(self):
        opt_out_repo.set_opted_out(self.connection, AUTHOR.id, True)
        await self.react(*FANS[:3])

        verdict = await self.explain(asked_by=AUTHOR.id)
        self.assertEqual(message_check.CANNOT_FEATURE, verdict.reason)
        self.assertNotEqual(message_check.messages.WHY_CANNOT_FEATURE, verdict.text)

    async def test_too_old(self):
        old = self.channel.add(2, AUTHOR, created_at=datetime.datetime.now(datetime.timezone.utc)
                                                   - datetime.timedelta(days=31))
        await self.react(*FANS[:3], message=old)
        verdict = await self.explain(old)

        self.assertIsNone(self.stored(2))
        self.assertEqual(utils.RULE_TOO_OLD, verdict.reason)

    async def test_the_daily_limit_counts_todays_rows(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for index in range(utils.daily_post_limit):
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, 10_000 + index, self.channel.id, GUILD, 20_000 + index, 5, 0, now, None)
        await self.react(*FANS[:3])
        verdict = await self.explain()

        self.assertIsNone(self.stored())
        self.assertEqual(message_check.DAILY_LIMIT, verdict.reason)

    async def test_a_channel_the_bot_cannot_read(self):
        hidden = SourceChannel(520, self.guild, readable=False)
        message = hidden.add(3, AUTHOR)
        verdict = await self.explain(message)

        self.assertEqual(message_check.CANNOT_READ, verdict.reason)
        self.assertIn("<#520>", verdict.text)
