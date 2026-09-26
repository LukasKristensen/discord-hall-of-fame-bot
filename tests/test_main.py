"""Tests for the command entry points and the guards in front of them.

Every configuration command in the bot begins the same way: check the bot has finished loading,
then check the member is allowed to change the server's settings. Those two guards are the whole
authorisation story of the bot, and they run before every write to a server's configuration.

Importing ``main`` is what these tests need, and it is only possible because the connection pool is
opened when the bot starts rather than when the module loads.
"""

import asyncio
import types
import unittest
from unittest import mock
import discord

import main
import utils
from caches import ExpiringSet
from translations import messages

from tests.fakes import FakeConnection, FakePermissions
from tests.test_server_class import build_server

GUILD_ID = 200


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.ephemeral = []
        self.deferred = False

    async def send_message(self, content=None, embed=None, ephemeral=False):
        self.messages.append(embed if embed is not None else content)
        self.ephemeral.append(ephemeral)

    async def defer(self):
        self.deferred = True

    def is_done(self):
        return self.deferred or bool(self.messages)


class FakeFollowup:
    def __init__(self):
        self.messages = []
        self.ephemeral = []

    async def send(self, content=None, embed=None, ephemeral=False):
        self.messages.append(embed if embed is not None else content)
        self.ephemeral.append(ephemeral)


class FakeUser:
    def __init__(self, manage_guild=True, name="Member", user_id=77, bot=False):
        self.id = user_id
        self.name = name
        self.bot = bot
        self.mention = f"<@{user_id}>"
        self.guild_permissions = types.SimpleNamespace(manage_guild=manage_guild)


class FakeGuild:
    def __init__(self, guild_id=GUILD_ID, name="Test Server", emojis=()):
        self.id = guild_id
        self.name = name
        self.emojis = list(emojis)
        self.me = FakeUser(user_id=1, bot=True)


class FakeInteraction:
    def __init__(self, manage_guild=True, guild_id=GUILD_ID):
        self.guild = FakeGuild(guild_id=guild_id)
        self.guild_id = guild_id
        self.user = FakeUser(manage_guild=manage_guild)
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.command = types.SimpleNamespace(name="test_command")

    @property
    def replies(self):
        """Everything sent back, whether as the response or as a followup"""
        return self.response.messages + self.followup.messages


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

        self.given_server_configs = []

        async def record(_interaction, threshold, _connection, _method_label, server_config):
            self.recorded.append(threshold)
            self.given_server_configs.append(server_config)

        self.patch(main.commands, "set_reaction_threshold", record)

    async def test_stores_the_threshold_that_was_asked_for(self):
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, 7)

        self.assertEqual([7], self.recorded)
        # The command updates the cache itself, before it replies, so it must be given the cached config
        self.assertEqual([main.server_classes[GUILD_ID]], self.given_server_configs)

    async def test_refuses_a_threshold_of_zero(self):
        """
        A threshold of zero would send every message ever posted to the board. It is refused rather
        than quietly raised to one, so the member is not left believing zero was stored.
        """
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, 0)

        self.assertEqual([], self.recorded)
        self.assertIn("between 1 and", interaction.response.messages[0])
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_refuses_a_negative_threshold(self):
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, -5)

        self.assertEqual([], self.recorded)

    async def test_refuses_a_threshold_above_the_maximum(self):
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, main.validation.REACTION_THRESHOLD_MAX + 1)

        self.assertEqual([], self.recorded)

    async def test_says_so_when_the_threshold_is_already_set(self):
        main.server_classes[GUILD_ID].reaction_threshold = 7
        interaction = FakeInteraction()
        await main.configure_bot.callback(interaction, 7)

        self.assertEqual([], self.recorded)
        self.assertIn("already", interaction.response.messages[0])
        self.assertEqual(0, self.pool.handed_out)

    async def test_the_command_picker_enforces_the_bounds(self):
        """Discord refuses an out of range number before it ever reaches the bot."""
        option = main.configure_bot.get_parameter("reaction_threshold")

        self.assertEqual(main.validation.REACTION_THRESHOLD_MIN, option.min_value)
        self.assertEqual(main.validation.REACTION_THRESHOLD_MAX, option.max_value)

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

        embed = interaction.response.messages[0]
        self.assertIsInstance(embed, discord.Embed)
        self.assertIn("Reactions needed", " ".join(field.value for field in embed.fields))

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

        self.assertIn("😂", " ".join(field.value for field in interaction.response.messages[0].fields))


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


class OnMessageMentionTests(MainTestCase):
    """Where a ping is answered relative to the checks that were already in on_message."""

    def setUp(self):
        super().setUp()
        self.answered = []

        async def record_answer(message, _bot_user, server_config):
            self.answered.append((message.channel.id, server_config))
            return True

        self.patch(main.commands, "answer_bot_mention", record_answer)

        self.moderated = []

        async def record_moderation(message, _bot, _server_config):
            self.moderated.append(message.channel.id)

        self.patch(main.events, "on_message", record_moderation)
        self.patch(main, "bot", types.SimpleNamespace(user=FakeUser(user_id=1)))

    def message(self, channel_id=555, mentions_bot=True, content="<@1>", manage_messages=True):
        permissions = FakePermissions(manage_messages=manage_messages)
        guild = FakeGuild()
        guild.me = FakeUser(user_id=1, bot=True)
        return types.SimpleNamespace(
            author=FakeUser(user_id=77),
            guild=guild,
            channel=types.SimpleNamespace(id=channel_id, permissions_for=lambda _member: permissions),
            content=content,
            mentions=[FakeUser(user_id=1)] if mentions_bot else [],
            reference=None,
            type=None)

    async def test_answers_a_ping(self):
        self.set_server_classes([GUILD_ID])
        await main.on_message(self.message())

        self.assertEqual(1, len(self.answered))

    async def test_answers_a_ping_in_a_server_that_is_not_set_up(self):
        """This is the case a ping is most often for, so the usual guard must not swallow it."""
        self.set_server_classes([201])
        await main.on_message(self.message())

        self.assertEqual(1, len(self.answered))
        self.assertIsNone(self.answered[0][1])

    async def test_hands_the_answer_the_configuration_of_the_server(self):
        self.set_server_classes([GUILD_ID])
        await main.on_message(self.message())

        self.assertEqual(GUILD_ID, self.answered[0][1].guild_id)

    async def test_leaves_a_ping_in_a_moderated_board_to_be_deleted(self):
        """Answering there would leave the bot replying to a message that is about to vanish."""
        self.patch(main, "server_classes", {GUILD_ID: build_server(
            guild_id=GUILD_ID, hall_of_fame_channel_id=100, allow_messages_in_hof_channel=False)})
        await main.on_message(self.message(channel_id=100))

        self.assertEqual([], self.answered)
        self.assertEqual([100], self.moderated)

    async def test_answers_a_ping_in_a_board_that_allows_chat(self):
        self.patch(main, "server_classes", {GUILD_ID: build_server(
            guild_id=GUILD_ID, hall_of_fame_channel_id=100, allow_messages_in_hof_channel=True)})
        await main.on_message(self.message(channel_id=100))

        self.assertEqual(1, len(self.answered))

    async def test_answers_a_ping_in_a_closed_board_it_cannot_clear_up_after(self):
        """Without Manage Messages the ping is not deleted either, so silence would just ignore it."""
        self.patch(main, "server_classes", {GUILD_ID: build_server(
            guild_id=GUILD_ID, hall_of_fame_channel_id=100, allow_messages_in_hof_channel=False)})
        await main.on_message(self.message(channel_id=100, manage_messages=False))

        self.assertEqual(1, len(self.answered))
        self.assertEqual([], self.moderated)

    async def test_leaves_an_ordinary_message_alone(self):
        self.set_server_classes([GUILD_ID])
        await main.on_message(self.message(mentions_bot=False, content="just chatting"))

        self.assertEqual([], self.answered)
        self.assertEqual([555], self.moderated)

    async def test_does_not_moderate_the_message_it_answered(self):
        self.set_server_classes([GUILD_ID])
        await main.on_message(self.message())

        self.assertEqual([], self.moderated)

    async def test_a_failure_to_answer_does_not_escape(self):
        async def fail(*_args, **_kwargs):
            raise RuntimeError("discord said no")

        self.patch(main.commands, "answer_bot_mention", fail)
        self.set_server_classes([GUILD_ID])
        await main.on_message(self.message())

        self.assertTrue(any("Error answering a mention" in entry for entry in self.logged))


class ConnectionSlotTests(MainTestCase):
    """
    psycopg2 raises when the pool is empty rather than waiting, so the waiting is done in front of
    it. These pin that a burst queues instead of being dropped, and that a slot is always given back.
    """

    def setUp(self):
        super().setUp()
        self.pool = FakePool()
        self.patch(main, "connection_pool", self.pool)
        self.patch(main, "bot", None)

    def size_the_pool(self, size):
        self.patch(main, "connection_slots", asyncio.Semaphore(size))

    async def borrow(self, hold=0.01, in_flight=None):
        async with main.get_db_connection(self.pool):
            if in_flight is not None:
                in_flight.append(self.pool.handed_out - self.pool.returned)
            await asyncio.sleep(hold)

    async def test_hands_out_a_connection(self):
        self.size_the_pool(2)
        async with main.get_db_connection(self.pool) as connection:
            self.assertIsNotNone(connection)

        self.assertEqual(1, self.pool.handed_out)

    async def test_never_asks_the_pool_for_more_than_it_has(self):
        """This is the condition psycopg2 raises on, so it must never be reached."""
        self.size_the_pool(3)
        in_flight = []
        await asyncio.gather(*(self.borrow(in_flight=in_flight) for _ in range(20)))

        self.assertLessEqual(max(in_flight), 3)

    async def test_serves_every_caller_in_a_burst(self):
        self.size_the_pool(3)
        await asyncio.gather(*(self.borrow() for _ in range(20)))

        self.assertEqual(20, self.pool.handed_out)
        self.assertEqual(20, self.pool.returned)

    async def test_gives_the_slot_back_when_the_body_fails(self):
        self.size_the_pool(1)
        with self.assertRaises(RuntimeError):
            async with main.get_db_connection(self.pool):
                raise RuntimeError("the query failed")

        # A slot that is not returned would take a connection out of circulation permanently
        async with main.get_db_connection(self.pool):
            pass
        self.assertEqual(2, self.pool.returned)

    async def test_gives_the_slot_back_when_the_pool_itself_fails(self):
        self.size_the_pool(1)

        def refuse():
            raise RuntimeError("connection pool exhausted")

        self.pool.getconn = refuse
        with self.assertRaises(RuntimeError):
            async with main.get_db_connection(self.pool):
                pass

        self.assertFalse(main.connection_slots.locked())

    async def test_gives_up_rather_than_waiting_for_ever(self):
        self.size_the_pool(1)
        self.patch(main, "connection_wait_timeout_seconds", 0.02)

        async def hold_it():
            async with main.get_db_connection(self.pool):
                await asyncio.sleep(0.5)

        holder = asyncio.create_task(hold_it())
        await asyncio.sleep(0)
        with self.assertRaises(asyncio.TimeoutError):
            async with main.get_db_connection(self.pool):
                pass
        holder.cancel()

    async def test_reports_giving_up(self):
        self.size_the_pool(1)
        self.patch(main, "connection_wait_timeout_seconds", 0.02)

        async def hold_it():
            async with main.get_db_connection(self.pool):
                await asyncio.sleep(0.5)

        holder = asyncio.create_task(hold_it())
        await asyncio.sleep(0)
        try:
            async with main.get_db_connection(self.pool):
                pass
        except asyncio.TimeoutError:
            pass
        holder.cancel()

        self.assertTrue(any("gave up" in entry for entry in self.logged))

    async def test_the_queue_is_sized_to_the_pool_behind_it(self):
        """Longer than the pool and psycopg2 raises again; shorter and connections sit unused."""
        acquired = 0
        try:
            for _ in range(main.database_pool_size):
                await asyncio.wait_for(main.connection_slots.acquire(), 0.1)
                acquired += 1
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(main.connection_slots.acquire(), 0.02)
        finally:
            for _ in range(acquired):
                main.connection_slots.release()

        self.assertEqual(main.database_pool_size, acquired)


class CommandTestCase(MainTestCase):
    """A loaded bot with this server set up and a pool whose writes are recorded rather than run."""

    def setUp(self):
        super().setUp()
        self.set_server_classes([GUILD_ID, 201])
        self.pool = FakePool()
        self.patch(main, "connection_pool", self.pool)
        self.patch(main, "bot_loaded", True)
        self.writes = []

        def record_write(guild_id, parameter, value, _connection):
            self.writes.append((guild_id, parameter, value))

        self.patch(main.server_config_repo, "update_server_config_param", record_write)

    @property
    def server(self):
        return main.server_classes[GUILD_ID]


class UpdateSettingTests(CommandTestCase):
    async def test_stores_and_confirms_a_change(self):
        self.server.ignore_bot_messages = False
        interaction = FakeInteraction()
        changed = await main.update_setting(interaction, "ignore_bot_messages", True, "Ignore messages from bots")

        self.assertTrue(changed)
        self.assertEqual([(GUILD_ID, "ignore_bot_messages", True)], self.writes)
        self.assertTrue(self.server.ignore_bot_messages)
        self.assertEqual(["✅ Ignore messages from bots: **On**"], interaction.response.messages)

    async def test_confirms_a_change_where_the_channel_can_see_it(self):
        """A settings change affects everybody, so it is announced rather than whispered."""
        self.server.ignore_bot_messages = False
        interaction = FakeInteraction()
        await main.update_setting(interaction, "ignore_bot_messages", True, "Ignore messages from bots")

        self.assertEqual([False], interaction.response.ephemeral)

    async def test_says_so_rather_than_writing_a_value_that_is_already_set(self):
        self.server.ignore_bot_messages = True
        interaction = FakeInteraction()
        changed = await main.update_setting(interaction, "ignore_bot_messages", True, "Ignore messages from bots")

        self.assertFalse(changed)
        self.assertEqual([], self.writes)
        self.assertIn("already **On**", interaction.response.messages[0])
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_adds_the_note_to_the_confirmation(self):
        self.server.hide_hof_post_below_threshold = False
        interaction = FakeInteraction()
        await main.hide_hall_of_fame_posts_when_they_are_below_threshold.callback(interaction, True)

        self.assertIn("back above it", interaction.response.messages[0])

    async def test_answers_a_server_that_is_not_set_up(self):
        self.patch(main, "server_classes", {})
        interaction = FakeInteraction()
        changed = await main.update_setting(interaction, "ignore_bot_messages", True, "Ignore messages from bots")

        self.assertFalse(changed)
        self.assertEqual([messages.ERROR_SERVER_NOT_SETUP], interaction.response.messages)


class RefusalsAreEphemeralTests(CommandTestCase):
    async def test_a_member_without_manage_server_is_told_privately(self):
        interaction = FakeInteraction(manage_guild=False)
        await main.include_author_own_reaction_in_threshold.callback(interaction, True)

        self.assertEqual([messages.NOT_AUTHORIZED], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)
        self.assertEqual([], self.writes)

    async def test_the_leaderboard_cooldown_is_told_privately(self):
        self.patch(main, "daily_command_cooldowns", {77: ["leaderboard"]})
        interaction = FakeInteraction()
        await main.leaderboard.callback(interaction)

        self.assertEqual([messages.COMMAND_ON_COOLDOWN], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)


class PostDueDateCommandTests(CommandTestCase):
    async def test_stores_a_due_date_within_the_bounds(self):
        interaction = FakeInteraction()
        await main.set_post_due_date.callback(interaction, 14)

        self.assertEqual([(GUILD_ID, "post_due_date", 14)], self.writes)
        self.assertIn("14 days", interaction.response.messages[0])

    async def test_refuses_a_due_date_of_zero(self):
        """Zero days would stop every message from ever reaching the board."""
        interaction = FakeInteraction()
        await main.set_post_due_date.callback(interaction, 0)

        self.assertEqual([], self.writes)
        self.assertIn("between", interaction.response.messages[0])

    async def test_refuses_a_negative_due_date(self):
        interaction = FakeInteraction()
        await main.set_post_due_date.callback(interaction, -3)

        self.assertEqual([], self.writes)

    async def test_the_command_picker_enforces_the_bounds(self):
        option = main.set_post_due_date.get_parameter("post_due_date")

        self.assertEqual(main.validation.POST_DUE_DATE_MIN, option.min_value)
        self.assertEqual(main.validation.POST_DUE_DATE_MAX, option.max_value)


class WhitelistCommandTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.server.custom_emoji_check_logic = True
        self.stored_whitelist = []
        self.patch(main.server_config_repo, "get_parameter_value",
                   lambda _connection, _guild_id, _parameter: list(self.stored_whitelist))

    async def test_adds_a_valid_emoji(self):
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "❤️")

        self.assertEqual([(GUILD_ID, "whitelisted_emojis", ["❤️"])], self.writes)
        self.assertEqual(["❤️"], self.server.whitelisted_emojis)
        self.assertIn("1 in total", interaction.response.messages[0])

    async def test_stores_text_that_is_not_an_emoji_as_is(self):
        """Nothing catches this up front; it simply never matches a real reaction later."""
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "fire")

        self.assertEqual([(GUILD_ID, "whitelisted_emojis", ["fire"])], self.writes)

    async def test_stores_several_emojis_typed_together_as_one_entry(self):
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "🔥😂")

        self.assertEqual([(GUILD_ID, "whitelisted_emojis", ["🔥😂"])], self.writes)

    async def test_refuses_empty_input(self):
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "   ")

        self.assertEqual([], self.writes)
        self.assertIn("No emoji was given", interaction.response.messages[0])
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_says_so_when_the_emoji_is_already_listed(self):
        self.stored_whitelist = ["🔥"]
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "🔥")

        self.assertEqual([], self.writes)
        self.assertIn("already", interaction.response.messages[0])

    async def test_refuses_to_grow_past_the_limit(self):
        self.patch(main.validation, "WHITELIST_MAX_SIZE", 2)
        self.stored_whitelist = ["🔥", "😂"]
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "👍")

        self.assertEqual([], self.writes)
        self.assertIn("full", interaction.response.messages[0])

    async def test_points_to_the_setting_when_the_whitelist_is_off(self):
        self.server.custom_emoji_check_logic = False
        interaction = FakeInteraction()
        await main.whitelist_emoji.callback(interaction, "🔥")

        self.assertEqual([messages.CUSTOM_EMOJI_CHECK_DISABLED], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_removes_a_renamed_custom_emoji(self):
        self.stored_whitelist = ["<:old:123456789012345678>", "🔥"]
        interaction = FakeInteraction()
        await main.unwhitelist_emoji.callback(interaction, "<:new:123456789012345678>")

        self.assertEqual([(GUILD_ID, "whitelisted_emojis", ["🔥"])], self.writes)
        self.assertIn("1 left", interaction.response.messages[0])

    async def test_says_every_emoji_counts_once_the_last_one_is_removed(self):
        """An empty whitelist filters nothing out, which is easy to not expect."""
        self.stored_whitelist = ["🔥"]
        interaction = FakeInteraction()
        await main.unwhitelist_emoji.callback(interaction, "🔥")

        self.assertIn("every emoji counts", interaction.response.messages[0])

    async def test_says_so_when_removing_an_emoji_that_is_not_listed(self):
        self.stored_whitelist = ["🔥"]
        interaction = FakeInteraction()
        await main.unwhitelist_emoji.callback(interaction, "😂")

        self.assertEqual([], self.writes)
        self.assertIn("not in the whitelist", interaction.response.messages[0])
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_clearing_an_empty_whitelist_writes_nothing(self):
        self.server.whitelisted_emojis = []
        interaction = FakeInteraction()
        await main.clear_whitelist.callback(interaction)

        self.assertEqual([], self.writes)
        self.assertEqual([messages.WHITELIST_ALREADY_EMPTY], interaction.response.messages)

    async def test_turning_the_whitelist_on_warns_when_it_is_empty(self):
        self.server.custom_emoji_check_logic = False
        self.server.whitelisted_emojis = []
        interaction = FakeInteraction()
        option = types.SimpleNamespace(name="Only whitelisted emojis", value="whitelisted_emojis")
        await main.custom_emoji_check_logic.callback(interaction, option)

        self.assertEqual([(GUILD_ID, "custom_emoji_check_logic", True)], self.writes)
        self.assertIn("every emoji counts", interaction.response.messages[0])


class SetHallOfFameChannelCommandTests(CommandTestCase):
    def channel(self, channel_id=300, send_fails=False, **permissions):
        granted = FakePermissions(**permissions)
        channel = types.SimpleNamespace(id=channel_id, mention=f"<#{channel_id}>",
                                        permissions_for=lambda _member: granted, sent=[])

        async def send(content=None, **_kwargs):
            if send_fails:
                raise discord.HTTPException(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
            channel.sent.append(content)

        channel.send = send
        return channel

    async def test_names_every_permission_the_bot_is_missing(self):
        interaction = FakeInteraction()
        await main.set_hall_of_fame_channel.callback(
            interaction, self.channel(send_messages=False, embed_links=False))

        self.assertIn("Send Messages, Embed Links", interaction.response.messages[0])
        self.assertEqual([True], interaction.response.ephemeral)
        self.assertEqual([], self.writes)

    async def test_requires_embed_links(self):
        """Posts are embeds, and Discord drops an embed without it rather than failing."""
        interaction = FakeInteraction()
        await main.set_hall_of_fame_channel.callback(interaction, self.channel(embed_links=False))

        self.assertIn("Embed Links", interaction.response.messages[0])

    async def test_says_so_when_the_channel_is_already_the_board(self):
        self.server.hall_of_fame_channel_id = 300
        interaction = FakeInteraction()
        await main.set_hall_of_fame_channel.callback(interaction, self.channel(300))

        self.assertEqual([], self.writes)
        self.assertIn("already", interaction.response.messages[0])

    async def test_moves_the_board_and_confirms(self):
        self.patch(main.server_config_repo, "check_if_guild_exists", lambda _connection, _guild_id: True)
        interaction = FakeInteraction()
        await main.set_hall_of_fame_channel.callback(interaction, self.channel(300))

        self.assertTrue(interaction.response.deferred)
        self.assertEqual([(GUILD_ID, "hall_of_fame_channel_id", 300)], self.writes)
        self.assertEqual([messages.HOF_CHANNEL_SET.format(channel="<#300>")], interaction.followup.messages)
        self.assertEqual(300, self.server.hall_of_fame_channel_id)

    async def test_announces_the_move_in_the_new_channel(self):
        self.patch(main.server_config_repo, "check_if_guild_exists", lambda _connection, _guild_id: True)
        self.server.reaction_threshold = 5
        interaction = FakeInteraction()
        channel = self.channel(300)
        await main.set_hall_of_fame_channel.callback(interaction, channel)

        self.assertEqual(1, len(channel.sent))
        self.assertIn(interaction.user.mention, channel.sent[0])
        self.assertIn("**5**", channel.sent[0])

    async def test_still_confirms_the_move_when_the_announcement_cannot_be_posted(self):
        """The board has moved by then, so failing the command would tell the member the opposite."""
        self.patch(main.server_config_repo, "check_if_guild_exists", lambda _connection, _guild_id: True)
        interaction = FakeInteraction()
        await main.set_hall_of_fame_channel.callback(interaction, self.channel(300, send_fails=True))

        self.assertEqual(300, self.server.hall_of_fame_channel_id)
        self.assertEqual([messages.HOF_CHANNEL_SET_ANNOUNCEMENT_FAILED.format(channel="<#300>")],
                         interaction.followup.messages)

    async def test_first_setup_does_not_announce_twice(self):
        """Setting a server up posts its own welcome message in the channel."""
        self.patch(main, "server_classes", {201: build_server(guild_id=201)})

        async def join(*_args, **_kwargs):
            return build_server(guild_id=GUILD_ID)

        self.patch(main.events, "guild_join", join)
        interaction = FakeInteraction()
        channel = self.channel(300)
        await main.set_hall_of_fame_channel.callback(interaction, channel)

        self.assertEqual([], channel.sent)
        self.assertEqual([messages.HOF_CHANNEL_SET.format(channel="<#300>")], interaction.followup.messages)

    async def test_keeps_the_old_channel_cached_when_the_new_one_could_not_be_stored(self):
        """Otherwise reactions post to a channel the saved configuration does not know about."""
        self.patch(main.server_config_repo, "check_if_guild_exists", lambda _connection, _guild_id: True)
        self.server.hall_of_fame_channel_id = 100

        def fail_to_write(*_args):
            raise RuntimeError("database went away")

        self.patch(main.server_config_repo, "update_server_config_param", fail_to_write)
        with self.assertRaises(RuntimeError):
            await main.set_hall_of_fame_channel.callback(FakeInteraction(), self.channel(300))

        self.assertEqual(100, self.server.hall_of_fame_channel_id)

    async def test_answers_when_setting_the_server_up_fails(self):
        """This used to return without a word, leaving the command to time out."""
        self.patch(main, "server_classes", {201: build_server(guild_id=201)})

        async def fail_to_join(*_args, **_kwargs):
            return None

        self.patch(main.events, "guild_join", fail_to_join)
        interaction = FakeInteraction()
        await main.set_hall_of_fame_channel.callback(interaction, self.channel(300))

        self.assertIn("Could not set up", interaction.followup.messages[0])
        self.assertEqual([], self.writes)


class LeaderboardFailureTests(CommandTestCase):
    async def test_tells_the_member_when_the_leaderboard_fails(self):
        async def fail(interaction, *_args):
            await interaction.response.defer()
            raise RuntimeError("database went away")

        self.patch(main.commands, "server_leaderboard", fail)
        interaction = FakeInteraction()
        await main.leaderboard.callback(interaction)

        self.assertEqual([messages.COMMAND_FAILED], interaction.followup.messages)


class UserProfileCommandTests(CommandTestCase):
    async def test_a_bot_has_no_profile_to_look_up(self):
        interaction = FakeInteraction()
        await main.user_server_profile.callback(interaction, FakeUser(user_id=9, bot=True))

        self.assertEqual([messages.PROFILE_BOT_USER], interaction.response.messages)
        self.assertEqual(0, self.pool.handed_out)


class CommandErrorHandlerTests(MainTestCase):
    def invoke_error(self, message="boom"):
        command = types.SimpleNamespace(name="leaderboard", qualified_name="leaderboard")
        return discord.app_commands.CommandInvokeError(command, RuntimeError(message))

    async def test_answers_a_command_that_raised(self):
        interaction = FakeInteraction()
        await main.on_app_command_error(interaction, self.invoke_error())

        self.assertEqual([messages.COMMAND_FAILED], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_records_what_went_wrong(self):
        interaction = FakeInteraction()
        await main.on_app_command_error(interaction, self.invoke_error("the query failed"))

        self.assertTrue(any("the query failed" in entry for entry in self.logged))

    async def test_answers_with_a_followup_once_the_command_was_deferred(self):
        interaction = FakeInteraction()
        await interaction.response.defer()
        await main.on_app_command_error(interaction, self.invoke_error())

        self.assertEqual([messages.COMMAND_FAILED], interaction.followup.messages)

    async def test_explains_a_command_used_outside_a_server(self):
        interaction = FakeInteraction()
        await main.on_app_command_error(interaction, discord.app_commands.NoPrivateMessage())

        self.assertEqual([messages.GUILD_ONLY], interaction.response.messages)


class CommandContextTests(unittest.TestCase):
    def test_commands_are_only_offered_in_servers(self):
        """Every command reads the server it was used in, so in a DM it could only fail."""
        contexts = main.tree.allowed_contexts

        self.assertTrue(contexts.guild)
        self.assertFalse(contexts.dm_channel)
        self.assertFalse(contexts.private_channel)


if __name__ == "__main__":
    unittest.main()
