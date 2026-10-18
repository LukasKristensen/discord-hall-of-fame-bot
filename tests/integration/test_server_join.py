"""A server adding the bot, against a real PostgreSQL database.

utils.create_database_context stores a new server's configuration and returns the in-memory copy that
every reaction is then served from. The two are written separately, so these tests check that they
agree setting by setting, along with the starting threshold, re-joining, and the start-up sweep that
sets up servers which added the bot while it was offline.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import unittest
from unittest import mock

import events
import utils
from repositories import server_config_repo

from tests.integration.database import DatabaseTestCase, skip_without_database
from tests.integration.discord_world import Board, Bot, Guild

# Every setting the in-memory configuration carries, compared against what was stored
SETTINGS = ("hall_of_fame_channel_id", "guild_id", "reaction_threshold", "post_due_date", "sweep_limit",
            "sweep_limited", "include_author_in_reaction_calculation", "allow_messages_in_hof_channel",
            "custom_emoji_check_logic", "whitelisted_emojis", "leaderboard_setup", "ignore_bot_messages",
            "reaction_count_calculation_method", "hide_hof_post_below_threshold", "server_member_count",
            "require_image_or_video", "count_in_global_profiles")


@skip_without_database
class ServerJoinTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.logged = []

        async def record_log(_bot, message, *args, **kwargs):
            self.logged.append(str(message))

        patcher = mock.patch.object(utils, "logging", record_log)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def join(self, guild, custom_channel=None):
        return await utils.create_database_context(Bot(guild), guild, self.connection, custom_channel)

    def stored(self, guild_id):
        return server_config_repo.get_server_classes(self.connection).get(guild_id)

    async def test_the_stored_configuration_matches_the_one_in_memory(self):
        """Reactions are served from memory, so a difference here is a setting that changes on restart."""
        in_memory = await self.join(Guild(9001, member_count=30))
        stored = self.stored(9001)

        for setting in SETTINGS:
            with self.subTest(setting=setting):
                self.assertEqual(getattr(stored, setting), getattr(in_memory, setting))

    async def test_creates_a_board_and_stores_it(self):
        guild = Guild(9001)
        await self.join(guild)

        self.assertEqual(guild.created_channels[0].id, self.stored(9001).hall_of_fame_channel_id)

    async def test_uses_a_channel_it_was_given(self):
        guild = Guild(9001)
        board = Board(4242, guild, name="best-of")
        await self.join(guild, custom_channel=board)

        self.assertEqual(4242, self.stored(9001).hall_of_fame_channel_id)
        self.assertEqual([], guild.created_channels)

    async def test_the_starting_threshold_follows_the_member_count(self):
        for members, threshold in ((1, 1), (3, 2), (5, 3), (10, 4), (20, 5), (40, 6), (50, 7), (5000, 7)):
            with self.subTest(members=members):
                guild_id = 9100 + members
                await self.join(Guild(guild_id, member_count=members))
                self.assertEqual(threshold, self.stored(guild_id).reaction_threshold)

    async def test_new_servers_count_toward_totals_across_servers(self):
        await self.join(Guild(9001))

        self.assertTrue(self.stored(9001).count_in_global_profiles)

    async def test_rejoining_starts_from_a_clean_configuration(self):
        await self.join(Guild(9001, member_count=30))
        server_config_repo.update_server_config_param(9001, "reaction_threshold", 99, self.connection)
        await self.join(Guild(9001, member_count=30))

        self.assertEqual(5, self.stored(9001).reaction_threshold)
        self.assertEqual([(1,)], self.rows("SELECT COUNT(*) FROM server_configs WHERE guild_id = 9001"))

    async def test_other_servers_are_untouched(self):
        await self.join(Guild(9002))
        before = self.rows("SELECT * FROM server_configs WHERE guild_id = 9002")
        await self.join(Guild(9001))

        self.assertEqual(before, self.rows("SELECT * FROM server_configs WHERE guild_id = 9002"))

    async def test_a_failed_setup_stores_nothing(self):
        guild = Guild(9001)

        async def refuse(_name):
            raise RuntimeError("Missing Permissions")

        guild.create_text_channel = refuse
        result = await events.guild_join(guild, self.connection, Bot(guild))

        self.assertIsNone(result)
        self.assertIsNone(self.stored(9001))

    async def test_the_start_up_sweep_sets_up_servers_added_while_offline(self):
        known, new = Guild(9001), Guild(9002)
        await self.join(known)
        before = self.rows("SELECT * FROM server_configs WHERE guild_id = 9001")

        created = await events.check_for_new_server_classes(Bot(known, new), self.connection)

        self.assertEqual({9002}, set(created))
        self.assertIsNotNone(self.stored(9002))
        self.assertEqual(before, self.rows("SELECT * FROM server_configs WHERE guild_id = 9001"))

    async def test_the_start_up_sweep_skips_servers_it_cannot_set_up(self):
        no_permission = Guild(9003, manage_channels=False)
        created = await events.check_for_new_server_classes(Bot(no_permission), self.connection)

        self.assertEqual({}, created)
        self.assertIsNone(self.stored(9003))


if __name__ == "__main__":
    unittest.main()
