import unittest
from unittest import mock

from tests.fakes import (FakeBotWithGuildLookup, FakeChannelMessage, FakeGuildWithChannels, FakeMemberGuild,
                         FakePermissions, FakeTextChannel)
from tests.test_server_class import build_server

import events


class OnMessageTests(unittest.IsolatedAsyncioTestCase):
    HOF_CHANNEL_ID = 100

    def setUp(self):
        self.guild = FakeMemberGuild(guild_id=200)

        # No real sleeping between posting the reminder and removing it again
        sleep = mock.patch("events.asyncio.sleep", new=self.no_sleep)
        sleep.start()
        self.addCleanup(sleep.stop)

        logging = mock.patch("events.utils.logging", new=self.record_nothing)
        logging.start()
        self.addCleanup(logging.stop)

    @staticmethod
    async def no_sleep(_seconds):
        return None

    @staticmethod
    async def record_nothing(*_args, **_kwargs):
        return None

    def build(self, manage_messages=True, send_messages=True, channel_id=HOF_CHANNEL_ID,
              author_is_bot=False, allow_messages=False):
        channel = FakeTextChannel(
            channel_id=channel_id,
            permissions=FakePermissions(manage_messages=manage_messages, send_messages=send_messages))
        message = FakeChannelMessage(channel, self.guild, author_is_bot=author_is_bot)
        server = build_server(hall_of_fame_channel_id=self.HOF_CHANNEL_ID,
                              allow_messages_in_hof_channel=allow_messages)
        return message, channel, server

    async def test_removes_chat_from_the_hall_of_fame_channel(self):
        message, channel, server = self.build()
        await events.on_message(message, None, server)

        self.assertTrue(message.deleted)
        self.assertEqual(1, len(channel.sent))
        self.assertIn("Only Hall of Fame messages are allowed", channel.sent[0].content)

    async def test_removes_its_own_reminder_afterwards(self):
        message, channel, server = self.build()
        await events.on_message(message, None, server)

        self.assertTrue(channel.sent[0].deleted)

    async def test_does_not_delete_without_the_manage_messages_permission(self):
        message, channel, server = self.build(manage_messages=False)
        await events.on_message(message, None, server)

        self.assertFalse(message.deleted)
        self.assertEqual([], channel.sent)

    async def test_still_deletes_when_it_cannot_explain_why(self):
        message, channel, server = self.build(send_messages=False)
        await events.on_message(message, None, server)

        self.assertTrue(message.deleted)
        self.assertEqual([], channel.sent)

    async def test_ignores_other_channels(self):
        message, channel, server = self.build(channel_id=999)
        await events.on_message(message, None, server)

        self.assertFalse(message.deleted)
        self.assertEqual([], channel.sent)

    async def test_ignores_bots(self):
        message, channel, server = self.build(author_is_bot=True)
        await events.on_message(message, None, server)

        self.assertFalse(message.deleted)

    async def test_leaves_the_channel_alone_when_chatting_is_allowed(self):
        message, channel, server = self.build(allow_messages=True)
        await events.on_message(message, None, server)

        self.assertFalse(message.deleted)
        self.assertEqual([], channel.sent)


class DailyPermissionCheckTests(unittest.IsolatedAsyncioTestCase):
    """The daily sweep is where a server is told about a permission it is missing."""

    HOF_CHANNEL_ID = 100

    def setUp(self):
        self.warnings = []

        logging = mock.patch("events.utils.logging", new=self.record_nothing)
        logging.start()
        self.addCleanup(logging.stop)

        notify = mock.patch("events.utils.send_message_to_highest_prio_channel", new=self.record_warning)
        notify.start()
        self.addCleanup(notify.stop)

    @staticmethod
    async def record_nothing(*_args, **_kwargs):
        return None

    async def record_warning(self, _bot, guild, content):
        self.warnings.append((guild.id, content))

    async def sweep(self, permissions, allow_messages=False):
        channel = FakeTextChannel(channel_id=self.HOF_CHANNEL_ID, permissions=permissions)
        guild = FakeGuildWithChannels(guild_id=200, channels={self.HOF_CHANNEL_ID: channel})
        bot = FakeBotWithGuildLookup({200: guild})
        server = build_server(guild_id=200, hall_of_fame_channel_id=self.HOF_CHANNEL_ID,
                              allow_messages_in_hof_channel=allow_messages)
        await events.check_write_permissions_to_hall_of_fame_channel(bot, {200: server})
        return self.warnings

    async def test_says_nothing_when_every_permission_is_present(self):
        self.assertEqual([], await self.sweep(FakePermissions()))

    async def test_reports_manage_messages_when_the_channel_is_reserved(self):
        warnings = await self.sweep(FakePermissions(manage_messages=False))

        self.assertEqual(1, len(warnings))
        self.assertIn("Manage Messages", warnings[0][1])

    async def test_ignores_manage_messages_when_members_may_chat(self):
        # Nothing needs deleting, so the permission is not required
        self.assertEqual([], await self.sweep(FakePermissions(manage_messages=False), allow_messages=True))

    async def test_reports_view_channel_alongside_the_others(self):
        warnings = await self.sweep(FakePermissions(send_messages=False, view_channel=False))

        content = warnings[0][1]
        self.assertIn("Send Messages", content)
        self.assertIn("View Channel", content)


if __name__ == "__main__":
    unittest.main()
