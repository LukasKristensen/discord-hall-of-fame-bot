import unittest

from tests.fakes import FakeBot, FakeLogGuild

import utils
from caches import ExpiringSet
from enums import log_type

DEVELOPER_MENTION = "<@230698327589650432>"
CRITICAL_CHANNEL_ID = 1439692415454675045
ERROR_CHANNEL_ID = 1344070396575617085


class LoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = FakeLogGuild()
        self.bot = FakeBot(guild=self.guild)
        # Each test starts with an empty duplicate window
        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def sent_to(self, channel_id):
        return self.guild.get_channel(channel_id).sent

    async def test_writes_the_message_to_the_error_channel(self):
        await utils.logging(self.bot, "something went wrong")

        self.assertEqual(1, len(self.sent_to(ERROR_CHANNEL_ID)))
        self.assertIn("something went wrong", self.sent_to(ERROR_CHANNEL_ID)[0])

    async def test_pings_the_developer_on_a_critical_message(self):
        await utils.logging(self.bot, "the database is gone", log_level=log_type.CRITICAL)

        self.assertTrue(self.sent_to(CRITICAL_CHANNEL_ID)[0].startswith(DEVELOPER_MENTION))

    async def test_does_not_ping_the_developer_on_a_regular_error(self):
        await utils.logging(self.bot, "a smaller problem", log_level=log_type.ERROR)

        self.assertNotIn(DEVELOPER_MENTION, self.sent_to(ERROR_CHANNEL_ID)[0])

    async def test_includes_the_server_id_and_the_new_value(self):
        await utils.logging(self.bot, "threshold changed", server_id=99, new_value=7)

        logged = self.sent_to(ERROR_CHANNEL_ID)[0]
        self.assertIn("[Server ID: 99]", logged)
        self.assertIn("[Value: 7]", logged)

    async def test_suppresses_a_repeated_message(self):
        await utils.logging(self.bot, "repeated failure", validate_for_duplicates=True)
        await utils.logging(self.bot, "repeated failure", validate_for_duplicates=True)

        self.assertEqual(1, len(self.sent_to(ERROR_CHANNEL_ID)))

    async def test_keeps_repeated_messages_when_duplicates_are_allowed(self):
        await utils.logging(self.bot, "heartbeat")
        await utils.logging(self.bot, "heartbeat")

        self.assertEqual(2, len(self.sent_to(ERROR_CHANNEL_ID)))

    async def test_the_same_text_from_a_different_server_is_not_a_duplicate(self):
        # Two servers hitting the same error must both be visible, not silently collapsed into one
        await utils.logging(self.bot, "channel is gone", server_id=200, validate_for_duplicates=True)
        await utils.logging(self.bot, "channel is gone", server_id=201, validate_for_duplicates=True)

        logged = self.sent_to(ERROR_CHANNEL_ID)
        self.assertEqual(2, len(logged))
        self.assertIn("[Server ID: 200]", logged[0])
        self.assertIn("[Server ID: 201]", logged[1])

    async def test_the_same_text_from_the_same_server_is_a_duplicate(self):
        await utils.logging(self.bot, "channel is gone", server_id=200, validate_for_duplicates=True)
        await utils.logging(self.bot, "channel is gone", server_id=200, validate_for_duplicates=True)

        self.assertEqual(1, len(self.sent_to(ERROR_CHANNEL_ID)))

    async def test_the_same_text_at_a_different_level_is_not_a_duplicate(self):
        await utils.logging(self.bot, "shared text", log_level=log_type.ERROR, validate_for_duplicates=True)
        await utils.logging(self.bot, "shared text", log_level=log_type.CRITICAL, validate_for_duplicates=True)

        self.assertEqual(1, len(self.sent_to(ERROR_CHANNEL_ID)))
        self.assertEqual(1, len(self.sent_to(CRITICAL_CHANNEL_ID)))

    async def test_uses_the_testing_channels_for_the_development_bot(self):
        development_bot = FakeBot(guild=self.guild, application_id=1)
        await utils.logging(development_bot, "development only")

        self.assertEqual([], self.sent_to(ERROR_CHANNEL_ID))
        self.assertEqual(1, len(self.sent_to(1383834395726577765)))


if __name__ == "__main__":
    unittest.main()
