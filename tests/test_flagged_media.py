"""Tests for taking down board posts whose media Discord's content scanning flagged.

Scanning can finish after a message is sent, and Discord delivers the result as an edit. So besides the
check before posting, which test_validate_message covers, the bot looks at its own board posts again
when they are edited, and these tests are about that second look: which edits it acts on, and what it
does to the post.
"""

import types
import unittest
from unittest import mock

import discord

import events
import utils

from tests.test_message_check import not_found
from tests.test_validate_message import (BOT_USER_ID, GUILD_ID, HALL_OF_FAME_MESSAGE_ID, SOURCE_CHANNEL_ID,
                                         TARGET_CHANNEL_ID, FakeAuthor, FakeBot, FakeEmbed, FakePostedMessage,
                                         FakeTargetChannel)


def board_post(flags=None, author_id=BOT_USER_ID):
    return FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[FakeEmbed(embed_type="image", flags=flags)],
                             author_id=author_id)


class TakeDownTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logged = []

        async def record_log(_bot, message, server_id=None, *args, **kwargs):
            self.logged.append((str(message), server_id))

        patcher = mock.patch.object(utils, "logging", record_log)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.board = FakeTargetChannel()
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.board})


class TakeDownFlaggedPostTests(TakeDownTestCase):
    async def test_blanks_a_post_whose_media_was_flagged(self):
        post = board_post(flags=utils.GORE_CONTENT)
        self.assertTrue(await utils.take_down_flagged_post(post, self.board, self.bot, GUILD_ID))
        self.assertEqual([{"content": "** **", "embed": None}], post.edits)

    async def test_logs_the_server_and_nothing_about_the_member(self):
        await utils.take_down_flagged_post(board_post(flags=utils.SELF_HARM_CONTENT), self.board, self.bot, GUILD_ID)
        [(text, server_id)] = self.logged
        self.assertEqual(GUILD_ID, server_id)
        self.assertNotIn(str(BOT_USER_ID), text)

    async def test_leaves_a_post_without_flags_alone(self):
        post = board_post()
        self.assertFalse(await utils.take_down_flagged_post(post, self.board, self.bot, GUILD_ID))
        self.assertEqual([], post.edits)
        self.assertEqual([], self.logged)

    async def test_keeps_explicit_media_on_an_age_restricted_board(self):
        post = board_post(flags=utils.EXPLICIT_CONTENT)
        board = FakeTargetChannel(nsfw=True)
        self.assertFalse(await utils.take_down_flagged_post(post, board, self.bot, GUILD_ID))

    async def test_takes_explicit_media_off_a_board_that_is_not_age_restricted(self):
        post = board_post(flags=utils.EXPLICIT_CONTENT)
        self.assertTrue(await utils.take_down_flagged_post(post, self.board, self.bot, GUILD_ID))

    async def test_a_post_deleted_meanwhile_is_not_an_error(self):
        post = board_post(flags=utils.GORE_CONTENT)

        async def gone(**_kwargs):
            raise not_found()
        post.edit = gone
        self.assertFalse(await utils.take_down_flagged_post(post, self.board, self.bot, GUILD_ID))


class MessageEditTests(TakeDownTestCase):
    def setUp(self):
        super().setUp()
        self.config = types.SimpleNamespace(hall_of_fame_channel_id=TARGET_CHANNEL_ID)

    async def edit(self, post, channel_id=TARGET_CHANNEL_ID):
        payload = types.SimpleNamespace(channel_id=channel_id, guild_id=GUILD_ID, message=post)
        await events.on_raw_message_edit(payload, self.bot, self.config)

    async def test_takes_down_the_bots_own_post_once_it_is_flagged(self):
        post = board_post(flags=utils.GORE_CONTENT)
        await self.edit(post)
        self.assertEqual([{"content": "** **", "embed": None}], post.edits)

    async def test_ignores_edits_outside_the_board(self):
        post = board_post(flags=utils.GORE_CONTENT)
        await self.edit(post, channel_id=SOURCE_CHANNEL_ID)
        self.assertEqual([], post.edits)

    async def test_ignores_messages_of_others_on_the_board(self):
        """A member's chat or another bot's message is not the bot's to take down."""
        post = board_post(flags=utils.GORE_CONTENT, author_id=12345)
        await self.edit(post)
        self.assertEqual([], post.edits)

    async def test_an_edit_without_flags_changes_nothing(self):
        post = board_post()
        await self.edit(post)
        self.assertEqual([], post.edits)


class ContentScanFlagTests(unittest.TestCase):
    def test_reads_real_discord_embeds(self):
        message = types.SimpleNamespace(attachments=[],
                                        embeds=[discord.Embed(), discord.Embed.from_dict({"flags": utils.GORE_CONTENT})])
        self.assertEqual(utils.GORE_CONTENT, utils.content_scan_flags(message))

    def test_keeps_only_the_scanning_flags(self):
        attachment = types.SimpleNamespace(flags=discord.AttachmentFlags._from_value((1 << 3) | utils.EXPLICIT_CONTENT))
        message = types.SimpleNamespace(attachments=[attachment], embeds=[])
        self.assertEqual(utils.EXPLICIT_CONTENT, utils.content_scan_flags(message))

    def test_a_message_without_media_has_none(self):
        self.assertEqual(0, utils.content_scan_flags(types.SimpleNamespace(author=FakeAuthor())))


if __name__ == "__main__":
    unittest.main()
