"""Tests for the Why isn't this on the board? explanation.

The explanation has to match what validate_message does with the message, so it runs on the same fakes
as the gate's own tests, and the rules both share are checked from both sides.
"""

import contextlib
import datetime
import unittest

import discord
from datetime import timezone
from unittest import mock

import message_check
import utils
from enums import calculation_method_type, command_refs
from translations import messages

from tests.fakes import FakePermissions
from tests.test_validate_message import (AUTHOR_ID, GUILD_ID, HALL_OF_FAME_MESSAGE_ID, SOURCE_CHANNEL_ID,
                                         TARGET_CHANNEL_ID, FakeAttachment, FakeBot, FakeGuild, FakeMessageRepo,
                                         FakePostedMessage, FakeSourceChannel, FakeSourceMessage,
                                         FakeTargetChannel, database_row, server_config)

ASKED_BY_ID = 88


def not_found():
    """A NotFound as discord.py raises it, without building an HTTP response for it"""
    return discord.NotFound.__new__(discord.NotFound)


class FakeBoard(FakeTargetChannel):
    def __init__(self, permissions=None, posts=None):
        super().__init__(messages=posts)
        self.permissions = permissions or FakePermissions()
        self.mention = f"<#{TARGET_CHANNEL_ID}>"

    def permissions_for(self, _member):
        return self.permissions

    async def fetch_message(self, message_id):
        # A post that is not in this board, as after the board moved or the post was deleted
        if message_id not in self.messages:
            raise not_found()
        return await super().fetch_message(message_id)


class FakeChannelRef:
    """The channel as the interaction's message carries it, which the bot may not be able to read"""

    def __init__(self, channel_id=SOURCE_CHANNEL_ID):
        self.id = channel_id
        self.mention = f"<#{channel_id}>"


class ExplainTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reaction_total = 5
        self.counted = 0

        async def count_reactions(_message, _connection, _config=None):
            self.counted += 1
            return self.reaction_total

        self.opted_out = set()
        for target, name, replacement in (
            (message_check, "reaction_count", count_reactions),
            (message_check.opt_out_repo, "is_opted_out", lambda _connection, user_id: user_id in self.opted_out),
        ):
            patcher = mock.patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build(self, *, age_days=0, author_bot=False, attachments=(), read_messages=True, read_history=True,
              source_channel_missing=False, board_missing=False, board_permissions=None, db_message=None,
              messages_today=0, asked_in=SOURCE_CHANNEL_ID, post_shown=True, message_deleted=False):
        """
        :param post_shown: For a stored post, whether the board shows it (True), hid it (False) or no longer
            has it (None)
        :param message_deleted: Whether the message is gone by the time it is fetched again
        """
        guild = FakeGuild()
        self.source_message = FakeSourceMessage(guild, age_days=age_days, author_bot=author_bot,
                                                attachments=attachments)
        self.source_message.channel = FakeChannelRef(asked_in)
        source_channel = FakeSourceChannel(guild, self.source_message, read_messages=read_messages)
        source_channel.permissions.read_message_history = read_history
        if message_deleted:
            async def gone(_message_id):
                raise not_found()
            source_channel.fetch_message = gone

        channels = {}
        if not source_channel_missing:
            channels[SOURCE_CHANNEL_ID] = source_channel
        if not board_missing:
            posts = {}
            if db_message is not None and post_shown is not None:
                posts[HALL_OF_FAME_MESSAGE_ID] = FakePostedMessage(
                    HALL_OF_FAME_MESSAGE_ID, embeds=[object()] if post_shown else [])
            channels[TARGET_CHANNEL_ID] = FakeBoard(board_permissions, posts)
        self.bot = FakeBot(channels)

        self.repo = FakeMessageRepo(db_message=db_message, messages_today=messages_today)
        patcher = mock.patch.object(message_check, "hall_of_fame_message_repo", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def explain(self, config=None, asked_by=ASKED_BY_ID):
        self.borrowed = 0

        @contextlib.asynccontextmanager
        async def connect():
            self.borrowed += 1
            yield object()

        return await message_check.explain(self.source_message, asked_by, self.bot, connect,
                                           config if config is not None else server_config())


class WhereTheMessageIsTests(ExplainTestCase):
    async def test_a_message_on_the_board_itself(self):
        self.build(asked_in=TARGET_CHANNEL_ID)
        self.assertEqual(message_check.IS_BOARD, (await self.explain()).reason)

    async def test_a_channel_the_bot_cannot_see(self):
        self.build(source_channel_missing=True)
        verdict = await self.explain()

        self.assertEqual(message_check.CANNOT_READ, verdict.reason)
        self.assertIn(f"<#{SOURCE_CHANNEL_ID}>", verdict.text)
        self.assertIn(command_refs.TROUBLESHOOT, verdict.text)

    async def test_a_channel_the_bot_cannot_read(self):
        self.build(read_messages=False)
        self.assertEqual(message_check.CANNOT_READ, (await self.explain()).reason)

    async def test_seeing_a_channel_without_its_history_is_not_enough(self):
        self.build(read_history=False)
        self.assertEqual(message_check.CANNOT_READ, (await self.explain()).reason)

    async def test_a_message_deleted_since_the_menu_opened(self):
        """An ordinary event, answered plainly rather than as an error that pings the developer."""
        self.build(message_deleted=True)
        verdict = await self.explain()

        self.assertEqual(message_check.MESSAGE_GONE, verdict.reason)
        self.assertEqual(messages.WHY_MESSAGE_GONE, verdict.text)


class AlreadyOnTheBoardTests(ExplainTestCase):
    async def test_links_to_the_post(self):
        self.build(db_message=database_row())
        verdict = await self.explain()

        self.assertEqual(message_check.ALREADY_POSTED, verdict.reason)
        self.assertIn(f"/channels/{GUILD_ID}/{TARGET_CHANNEL_ID}/{HALL_OF_FAME_MESSAGE_ID}", verdict.text)

    async def test_an_old_message_already_posted_is_still_on_the_board(self):
        """validate_message keeps updating such a post, so it is not explained as too old."""
        self.build(age_days=30, db_message=database_row())
        self.assertEqual(message_check.ALREADY_POSTED, (await self.explain()).reason)

    async def test_a_hidden_post_below_the_threshold(self):
        self.reaction_total = 1
        self.build(db_message=database_row(), post_shown=False)
        verdict = await self.explain()

        self.assertEqual(message_check.HIDDEN, verdict.reason)
        self.assertIn("1 of the 3", verdict.text)

    async def test_a_post_on_the_board_is_on_the_board_whatever_its_count(self):
        """What the board shows decides, since a rule or the limit can stop a post being hidden."""
        self.reaction_total = 1
        self.build(db_message=database_row())
        verdict = await self.explain(server_config(require_image_or_video=True))

        self.assertEqual(message_check.ALREADY_POSTED, verdict.reason)
        self.assertEqual(0, self.counted, "reactions were counted when nothing depends on them")

    async def test_a_hidden_post_held_back_by_a_rule_says_the_rule(self):
        """validate_message stops at the rule, so the post is not brought back however many reactions it gets."""
        self.build(db_message=database_row(), post_shown=False)
        verdict = await self.explain(server_config(require_image_or_video=True))

        self.assertEqual(utils.RULE_NO_MEDIA, verdict.reason)

    async def test_a_hidden_post_at_the_daily_limit_says_the_limit(self):
        self.build(db_message=database_row(), post_shown=False, messages_today=utils.daily_post_limit)

        self.assertEqual(message_check.DAILY_LIMIT, (await self.explain()).reason)

    async def test_a_hidden_post_with_enough_reactions_again_comes_back_on_the_next_one(self):
        self.build(db_message=database_row(), post_shown=False)

        self.assertEqual(message_check.QUALIFIES, (await self.explain()).reason)

    async def test_a_post_no_longer_in_the_board_gets_no_dead_link(self):
        """The board may have moved since, and a link built from the new board opens nothing."""
        self.build(db_message=database_row(), post_shown=None)
        verdict = await self.explain()

        self.assertEqual(message_check.POSTED_ELSEWHERE, verdict.reason)
        self.assertNotIn(str(HALL_OF_FAME_MESSAGE_ID), verdict.text)
        self.assertIn(f"<#{TARGET_CHANNEL_ID}>", verdict.text)


class RuleTests(ExplainTestCase):
    async def test_too_old(self):
        self.build(age_days=8)
        verdict = await self.explain()

        self.assertEqual(utils.RULE_TOO_OLD, verdict.reason)
        self.assertIn("7 days", verdict.text)
        self.assertIn(command_refs.SET_POST_DUE_DATE, verdict.text)

    async def test_from_a_bot(self):
        self.build(author_bot=True)
        verdict = await self.explain()

        self.assertEqual(utils.RULE_BOT_MESSAGE, verdict.reason)
        self.assertIn(command_refs.IGNORE_BOT_MESSAGES, verdict.text)

    async def test_without_an_image_or_video(self):
        self.build()
        verdict = await self.explain(server_config(require_image_or_video=True))

        self.assertEqual(utils.RULE_NO_MEDIA, verdict.reason)
        self.assertIn(command_refs.REQUIRE_IMAGE_OR_VIDEO, verdict.text)

    async def test_with_an_image_when_one_is_required(self):
        self.build(attachments=[FakeAttachment()])
        self.assertEqual(message_check.QUALIFIES,
                         (await self.explain(server_config(require_image_or_video=True))).reason)


class BoardTests(ExplainTestCase):
    async def test_the_board_is_missing(self):
        self.build(board_missing=True)
        verdict = await self.explain()

        self.assertEqual(message_check.NO_BOARD, verdict.reason)
        self.assertIn(command_refs.SET_HALL_OF_FAME_CHANNEL, verdict.text)

    async def test_names_the_permissions_missing_on_the_board(self):
        self.build(board_permissions=FakePermissions(send_messages=False, embed_links=False))
        verdict = await self.explain()

        self.assertEqual(message_check.CANNOT_POST, verdict.reason)
        self.assertIn("Send Messages, Embed Links", verdict.text)

    async def test_read_message_history_on_the_board_is_needed_too(self):
        """The same list as /troubleshoot and /set_hall_of_fame_channel, so the three agree."""
        self.build(board_permissions=FakePermissions(read_message_history=False))
        verdict = await self.explain()

        self.assertEqual(message_check.CANNOT_POST, verdict.reason)
        self.assertIn("Read Message History", verdict.text)

    async def test_the_daily_limit(self):
        self.build(messages_today=utils.daily_post_limit)
        verdict = await self.explain()

        self.assertEqual(message_check.DAILY_LIMIT, verdict.reason)
        self.assertEqual(0, self.counted)


class ThresholdTests(ExplainTestCase):
    async def test_says_how_far_it_is_and_how_the_server_counts(self):
        self.reaction_total = 2
        self.build()
        verdict = await self.explain(server_config(
            reaction_count_calculation_method=calculation_method_type.UNIQUE_USERS))

        self.assertEqual(message_check.BELOW_THRESHOLD, verdict.reason)
        self.assertIn("2 of the 3", verdict.text)
        self.assertIn("unique members who reacted", verdict.text)

    async def test_says_when_the_authors_reaction_does_not_count(self):
        self.reaction_total = 2
        self.build()
        verdict = await self.explain(server_config(include_author_in_reaction_calculation=False))
        self.assertIn(messages.WHY_AUTHOR_NOT_COUNTED, verdict.text)

        verdict = await self.explain(server_config(include_author_in_reaction_calculation=True))
        self.assertNotIn(messages.WHY_AUTHOR_NOT_COUNTED, verdict.text)

    async def test_lists_the_whitelist_when_only_it_counts(self):
        self.reaction_total = 2
        self.build()
        whitelist = [f"<:e{index}:{1000 + index}>" for index in range(12)]
        verdict = await self.explain(server_config(custom_emoji_check_logic=True, whitelisted_emojis=whitelist))

        self.assertIn("<:e0:1000>", verdict.text)
        self.assertNotIn("<:e11:1011>", verdict.text)
        self.assertIn("2 more", verdict.text)

    async def test_lists_a_short_whitelist_in_full(self):
        self.reaction_total = 2
        self.build()
        verdict = await self.explain(server_config(custom_emoji_check_logic=True, whitelisted_emojis=["👍", "🔥"]))

        self.assertIn("👍 🔥", verdict.text)
        self.assertNotIn("more", verdict.text)

    async def test_lists_no_whitelist_when_it_is_off_or_empty(self):
        self.reaction_total = 2
        self.build()
        for config in (server_config(custom_emoji_check_logic=True, whitelisted_emojis=[]),
                       server_config(custom_emoji_check_logic=False, whitelisted_emojis=["👍"])):
            with self.subTest(config=config.custom_emoji_check_logic):
                self.assertNotIn("Only these emojis count", (await self.explain(config)).text)

    async def test_reaching_the_threshold_exactly_qualifies(self):
        self.reaction_total = 3
        self.build()
        self.assertEqual(message_check.QUALIFIES, (await self.explain()).reason)


class OptedOutAuthorTests(ExplainTestCase):
    async def test_does_not_say_why_to_someone_else(self):
        self.opted_out.add(AUTHOR_ID)
        self.build()
        verdict = await self.explain()

        self.assertEqual(message_check.CANNOT_FEATURE, verdict.reason)
        self.assertEqual(messages.WHY_CANNOT_FEATURE, verdict.text)

    async def test_tells_the_author_and_how_to_undo_it(self):
        self.opted_out.add(AUTHOR_ID)
        self.build()
        verdict = await self.explain(asked_by=AUTHOR_ID)

        self.assertIn(command_refs.MY_DATA, verdict.text)

    async def test_below_the_threshold_reads_the_same_as_for_anyone(self):
        """Otherwise the answer for a message with few reactions would give the opt-out away."""
        self.opted_out.add(AUTHOR_ID)
        self.reaction_total = 1
        self.build()
        self.assertEqual(message_check.BELOW_THRESHOLD, (await self.explain()).reason)


class RuleBlockingPostTests(unittest.TestCase):
    """The rules validate_message and the explanation share."""

    def message(self, **kwargs):
        return FakeSourceMessage(FakeGuild(), **kwargs)

    def test_names_the_first_rule_broken(self):
        message = self.message(age_days=30, author_bot=True)
        self.assertEqual(utils.RULE_TOO_OLD, utils.rule_blocking_post(message, None, server_config()))

    def test_a_stored_post_is_never_too_old(self):
        self.assertIsNone(utils.rule_blocking_post(self.message(age_days=30), database_row(), server_config()))

    def test_takes_the_time_it_is_given(self):
        message = self.message()
        later = datetime.datetime.now(timezone.utc) + datetime.timedelta(days=8)
        self.assertEqual(utils.RULE_TOO_OLD, utils.rule_blocking_post(message, None, server_config(), now=later))

    def test_a_message_breaking_no_rule(self):
        self.assertIsNone(utils.rule_blocking_post(self.message(), None, server_config()))


class MenuNameTests(unittest.TestCase):
    def test_fits_discords_limit_for_a_command_name(self):
        self.assertLessEqual(len(messages.WHY_MENU_NAME), 32)
