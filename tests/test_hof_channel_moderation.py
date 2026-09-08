import unittest
from unittest import mock

from tests.fakes import (FakeChannelMessage, FakeMemberGuild, FakePermissions, FakeTextChannel)
from tests.test_server_class import build_server

import events
from caches import ExpiringSet
from translations import messages


class OnMessageTests(unittest.IsolatedAsyncioTestCase):
    HOF_CHANNEL_ID = 100

    def setUp(self):
        self.guild = FakeMemberGuild(guild_id=200)
        self.warnings = []

        # No real sleeping between posting the reminder and removing it again
        sleep = mock.patch("events.asyncio.sleep", new=self.no_sleep)
        sleep.start()
        self.addCleanup(sleep.stop)

        logging = mock.patch("events.utils.logging", new=self.record_nothing)
        logging.start()
        self.addCleanup(logging.stop)

        notify = mock.patch("events.utils.send_message_to_highest_prio_channel", new=self.record_warning)
        notify.start()
        self.addCleanup(notify.stop)

        events.missing_delete_permission_warnings = ExpiringSet(ttl_seconds=60)

    @staticmethod
    async def no_sleep(_seconds):
        return None

    @staticmethod
    async def record_nothing(*_args, **_kwargs):
        return None

    async def record_warning(self, _bot, guild, content, _history_limit):
        self.warnings.append((guild.id, content))

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

    async def test_does_not_warn_when_the_permission_is_present(self):
        message, _, server = self.build()
        await events.on_message(message, None, server)

        self.assertEqual([], self.warnings)


class MissingPermissionMessageTests(unittest.TestCase):
    def test_names_the_channel_and_the_way_out(self):
        content = messages.MISSING_MANAGE_MESSAGES.format(channel="<#100>")

        self.assertIn("<#100>", content)
        self.assertIn("Manage Messages", content)
        self.assertIn("allow_messages_in_hof_channel", content)


if __name__ == "__main__":
    unittest.main()
