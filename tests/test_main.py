"""Tests for the command entry points and the guards in front of them.

Every configuration command in the bot begins the same way: check the bot has finished loading,
then check the member is allowed to change the server's settings. Those two guards are the whole
authorisation story of the bot, and they run before every write to a server's configuration.

Importing ``main`` is what these tests need, and it is only possible because the connection pool is
opened when the bot starts rather than when the module loads.
"""

import types
import unittest
from unittest import mock

import main
import utils
from caches import ExpiringSet
from translations import messages

from tests.fakes import FakeConnection
from tests.test_server_class import build_server

GUILD_ID = 200


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, embed=None, ephemeral=False):
        self.messages.append(embed if embed is not None else content)


class FakeUser:
    def __init__(self, manage_guild=True, name="Member", user_id=77):
        self.id = user_id
        self.name = name
        self.guild_permissions = types.SimpleNamespace(manage_guild=manage_guild)


class FakeGuild:
    def __init__(self, guild_id=GUILD_ID, name="Test Server"):
        self.id = guild_id
        self.name = name


class FakeInteraction:
    def __init__(self, manage_guild=True, guild_id=GUILD_ID):
        self.guild = FakeGuild(guild_id=guild_id)
        self.guild_id = guild_id
        self.user = FakeUser(manage_guild=manage_guild)
        self.response = FakeResponse()


class FakePool:
    """Hands out one connection, in the shape the pool the bot runs on does."""

    def __init__(self, connection=None):
        self.connection = connection if connection is not None else FakeConnection()
        self.handed_out = 0
        self.returned = 0

    def getconn(self):
        self.handed_out += 1
        return self.connection

    def putconn(self, _connection):
        self.returned += 1


class MainTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logged = []

        async def record_log(_bot, message, *args, **kwargs):
            self.logged.append(str(message))

        self.patch(utils, "logging", record_log)

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch(self, target, name, replacement):
        patcher = mock.patch.object(target, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_server_classes(self, guild_ids):
        self.patch(main, "server_classes", {guild_id: build_server(guild_id=guild_id) for guild_id in guild_ids})


class ManageServerPermissionTests(MainTestCase):
    """The gate every command that changes a server's configuration sits behind."""

    async def test_lets_a_server_manager_through(self):
        self.set_server_classes([GUILD_ID, 201])
        interaction = FakeInteraction(manage_guild=True)

        self.assertTrue(await main.check_if_user_has_manage_server_permission(interaction))

    async def test_turns_away_a_member_without_manage_server(self):
        self.set_server_classes([GUILD_ID, 201])
        interaction = FakeInteraction(manage_guild=False)

        self.assertFalse(await main.check_if_user_has_manage_server_permission(interaction))

    async def test_tells_the_member_why_they_were_turned_away(self):
        self.set_server_classes([GUILD_ID, 201])
        interaction = FakeInteraction(manage_guild=False)
        await main.check_if_user_has_manage_server_permission(interaction)

        self.assertEqual([messages.NOT_AUTHORIZED], interaction.response.messages)

    async def test_records_the_refusal(self):
        self.set_server_classes([GUILD_ID, 201])
        interaction = FakeInteraction(manage_guild=False)
        await main.check_if_user_has_manage_server_permission(interaction)

        self.assertTrue(any("does not have manage server permission" in entry for entry in self.logged))

    async def test_turns_away_a_server_that_is_not_set_up(self):
        self.set_server_classes([201, 202])
        interaction = FakeInteraction(manage_guild=True, guild_id=GUILD_ID)

        self.assertFalse(await main.check_if_user_has_manage_server_permission(interaction))
        self.assertEqual([messages.ERROR_SERVER_NOT_SETUP], interaction.response.messages)

    async def test_skips_the_setup_check_when_the_caller_is_setting_the_server_up(self):
        """/set_hall_of_fame_channel is how a server gets set up, so it cannot require being set up."""
        self.set_server_classes([201, 202])
        interaction = FakeInteraction(manage_guild=True, guild_id=GUILD_ID)

        self.assertTrue(await main.check_if_user_has_manage_server_permission(
            interaction, check_server_set_up=False))

    async def test_still_refuses_a_member_without_manage_server_when_setting_up(self):
        self.set_server_classes([201, 202])
        interaction = FakeInteraction(manage_guild=False, guild_id=GUILD_ID)

        self.assertFalse(await main.check_if_user_has_manage_server_permission(
            interaction, check_server_set_up=False))

    async def test_a_server_holding_no_configuration_is_treated_as_not_set_up(self):
        self.patch(main, "server_classes", {GUILD_ID: None, 201: build_server(guild_id=201)})
        interaction = FakeInteraction(manage_guild=True, guild_id=GUILD_ID)

        self.assertFalse(await main.check_if_user_has_manage_server_permission(interaction))


class BotLoadingTests(MainTestCase):
    async def test_holds_commands_back_while_the_bot_is_still_starting(self):
        self.patch(main, "bot_loaded", False)
        interaction = FakeInteraction()

        self.assertFalse(await main.ensure_bot_is_loaded(interaction))

    async def test_says_so_rather_than_leaving_the_command_to_time_out(self):
        self.patch(main, "bot_loaded", False)
        interaction = FakeInteraction()
        await main.ensure_bot_is_loaded(interaction)

        self.assertEqual([messages.BOT_LOADING], interaction.response.messages)

    async def test_lets_commands_through_once_the_bot_is_ready(self):
        self.patch(main, "bot_loaded", True)
        interaction = FakeInteraction()

        self.assertTrue(await main.ensure_bot_is_loaded(interaction))
        self.assertEqual([], interaction.response.messages)


class SetupDatabasesTests(unittest.TestCase):
    def test_creates_every_table_the_bot_reads(self):
        connection = FakeConnection()
        main.setup_databases(connection)

        created = [query for query in connection.queries if "CREATE TABLE IF NOT EXISTS" in query]
        self.assertEqual(7, len(created))

    def test_creates_each_table_only_if_it_is_missing(self):
        """This runs on every start, so it must never drop or recreate a table that holds data."""
        connection = FakeConnection()
        main.setup_databases(connection)

        for query in connection.queries:
            with self.subTest(query=query.strip()[:40]):
                self.assertNotIn("DROP TABLE", query)


class CommandTreeTests(unittest.TestCase):
    def test_registers_every_command(self):
        names = {command.name for command in main.tree.get_commands()}

        for expected in ("help", "leaderboard", "user_profile", "hof_wrapped", "server_hof_wrapped",
                         "set_reaction_threshold", "set_hall_of_fame_channel", "calculation_method",
                         "get_server_config", "feedback", "invite", "vote"):
            with self.subTest(command=expected):
                self.assertIn(expected, names)

    def test_every_command_describes_itself(self):
        """Discord shows the description in the command picker and rejects an empty one."""
        for command in main.tree.get_commands():
            with self.subTest(command=command.name):
                self.assertTrue(command.description)

    def test_no_command_is_registered_twice(self):
        names = [command.name for command in main.tree.get_commands()]

        self.assertEqual(len(names), len(set(names)))


class SetReactionThresholdCommandTests(MainTestCase):
    def setUp(self):
        super().setUp()
        self.set_server_classes([GUILD_ID, 201])
        self.pool = FakePool()
        self.patch(main, "connection_pool", self.pool)
        self.patch(main, "bot_loaded", True)
        self.recorded = []

        async def record(_interaction, threshold, _connection):
            self.recorded.append(threshold)

        self.patch(main.commands, "set_reaction_threshold", record)

    async def test_stores_the_threshold_that_was_asked_for(self):
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, 7)

        self.assertEqual([7], self.recorded)
        self.assertEqual(7, main.server_classes[GUILD_ID].reaction_threshold)

    async def test_raises_a_threshold_of_zero_to_one(self):
        """A threshold of zero would send every message ever posted to the board."""
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, 0)

        self.assertEqual([1], self.recorded)

    async def test_raises_a_negative_threshold_to_one(self):
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, -5)

        self.assertEqual([1], self.recorded)

    async def test_changes_nothing_for_a_member_without_manage_server(self):
        interaction = FakeInteraction(manage_guild=False)
        await main.configure_bot.callback(interaction, 7)

        self.assertEqual([], self.recorded)

    async def test_returns_the_connection_to_the_pool(self):
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, 7)

        self.assertEqual(self.pool.handed_out, self.pool.returned)


class GetServerConfigCommandTests(MainTestCase):
    def setUp(self):
        super().setUp()
        self.patch(main, "bot_loaded", True)

    async def test_reports_the_configuration_of_a_server_that_has_one(self):
        self.set_server_classes([GUILD_ID])
        interaction = FakeInteraction()
        await main.get_server_config.callback(interaction)

        self.assertIn("Reaction Threshold", interaction.response.messages[0])

    async def test_says_a_server_is_not_set_up_rather_than_failing(self):
        """Answering a command with an error is worse than answering it with the reason."""
        self.set_server_classes([201])
        interaction = FakeInteraction(guild_id=GUILD_ID)
        await main.get_server_config.callback(interaction)

        self.assertEqual([messages.ERROR_SERVER_NOT_SETUP], interaction.response.messages)

    async def test_lists_the_whitelist_only_when_the_whitelist_is_in_use(self):
        self.patch(main, "server_classes", {
            GUILD_ID: build_server(guild_id=GUILD_ID, custom_emoji_check_logic=True,
                                   whitelisted_emojis=["😂", "🔥"])})
        interaction = FakeInteraction()
        await main.get_server_config.callback(interaction)

        self.assertIn("😂", interaction.response.messages[0])


class PostApiBotStatsTests(MainTestCase):
    async def test_says_nothing_to_the_listing_sites_from_the_development_bot(self):
        self.patch(main, "dev_test", True)
        with mock.patch.object(main.topgg_api, "post_bot_stats") as topgg:
            await main.post_api_bot_stats()

        topgg.assert_not_called()

    async def test_reports_the_server_count_to_both_sites(self):
        self.patch(main, "dev_test", False)
        self.patch(main, "bot", types.SimpleNamespace(guilds=[FakeGuild(), FakeGuild(201)]))
        with mock.patch.object(main.topgg_api, "post_bot_stats", return_value=(200, {})) as topgg, \
                mock.patch.object(main.discordbotlist_api, "post_bot_stats", return_value=(200, {})) as dbl:
            await main.post_api_bot_stats()

        self.assertEqual(2, topgg.call_args.args[0])
        self.assertEqual(2, dbl.call_args.args[0])

    async def test_one_unreachable_site_does_not_stop_the_other(self):
        self.patch(main, "dev_test", False)
        self.patch(main, "bot", types.SimpleNamespace(guilds=[FakeGuild()]))
        with mock.patch.object(main.topgg_api, "post_bot_stats", side_effect=RuntimeError("down")), \
                mock.patch.object(main.discordbotlist_api, "post_bot_stats", return_value=(200, {})) as dbl:
            await main.post_api_bot_stats()

        dbl.assert_called_once()


if __name__ == "__main__":
    unittest.main()
