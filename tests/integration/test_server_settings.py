"""Server settings and a few commands end to end, against a real PostgreSQL database.

Server settings are read back by column position into the in-memory configuration every reaction is
served from, so a column added in the wrong place silently swaps two settings. These tests store a
distinct value in every setting and read each one back the ways the bot does. The command tests at the
end run real commands, with Discord faked, against real rows.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import json
import types
import unittest
from unittest import mock

import discord

import main
import utils
from repositories import global_profile_repo, hall_of_fame_message_repo, server_config_repo
from translations import messages

from tests.integration.database import DatabaseTestCase, SingleConnectionPool, skip_without_database
from tests.test_server_class import build_server

GUILD = 9001
OTHER_GUILD = 9002
JOINED = datetime.datetime(2025, 3, 1, 9, 30)

# A value for every setting that differs from its default, so a swapped column cannot go unnoticed
SETTINGS = {
    "hall_of_fame_channel_id": 1234,
    "reaction_threshold": 13,
    "post_due_date": 77,
    "leaderboard_message_ids": ["11", "12"],
    "sweep_limit": 450,
    "sweep_limited": False,
    "include_author_in_reaction_calculation": False,
    "allow_messages_in_hof_channel": False,
    "custom_emoji_check_logic": True,
    "whitelisted_emojis": ["🔥", "<:custom:123456789012345678>"],
    "leaderboard_setup": True,
    "ignore_bot_messages": True,
    "server_member_count": 321,
    "reaction_count_calculation_method": "unique_users",
    "hide_hof_post_below_threshold": False,
    "require_image_or_video": True,
    "count_in_global_profiles": False,
}


@skip_without_database
class ServerSettingsTests(DatabaseTestCase):
    def insert(self, guild=GUILD, **overrides):
        values = dict(SETTINGS, **overrides)
        server_config_repo.insert_server_with_parameters(
            self.connection, guild, values["hall_of_fame_channel_id"], values["reaction_threshold"],
            values["post_due_date"], values["leaderboard_message_ids"], values["sweep_limit"], values["sweep_limited"],
            values["include_author_in_reaction_calculation"], values["allow_messages_in_hof_channel"],
            values["custom_emoji_check_logic"], values["whitelisted_emojis"], JOINED, values["leaderboard_setup"],
            values["ignore_bot_messages"], values["server_member_count"], values["reaction_count_calculation_method"],
            values["hide_hof_post_below_threshold"], values["require_image_or_video"], values["count_in_global_profiles"])

    def assert_settings(self, server, expected):
        for name, value in expected.items():
            with self.subTest(setting=name):
                self.assertEqual(value, getattr(server, name))

    def test_every_setting_is_read_back_where_it_was_stored(self):
        self.insert()

        self.assert_settings(server_config_repo.get_server_classes(self.connection)[GUILD], SETTINGS)

    def test_the_other_column_order_reads_the_same(self):
        self.insert()

        self.assert_settings(server_config_repo.get_all_server_configs(self.connection)[0], SETTINGS)

    def test_every_setting_can_be_changed_and_read_back(self):
        self.insert()
        changed = {
            "hall_of_fame_channel_id": 999, "reaction_threshold": 3, "post_due_date": 5,
            "leaderboard_message_ids": ["99"], "sweep_limit": 10, "sweep_limited": True,
            "include_author_in_reaction_calculation": True, "allow_messages_in_hof_channel": True,
            "custom_emoji_check_logic": False, "whitelisted_emojis": [], "leaderboard_setup": False,
            "ignore_bot_messages": False, "server_member_count": 12, "reaction_count_calculation_method": "total_reactions",
            "hide_hof_post_below_threshold": True, "require_image_or_video": False, "count_in_global_profiles": True,
        }
        for name, value in changed.items():
            server_config_repo.update_server_config_param(GUILD, name, value, self.connection)
            with self.subTest(setting=name):
                self.assertEqual(value, server_config_repo.get_parameter_value(self.connection, GUILD, name))

        self.assert_settings(server_config_repo.get_server_classes(self.connection)[GUILD], changed)

    def test_every_writable_setting_is_tested_here(self):
        """A new setting has to be added to SETTINGS above, so it is checked for a swapped column too."""
        self.assertEqual(server_config_repo.ALLOWED_COLUMNS - {"joined_date"}, set(SETTINGS))

    def test_changing_a_setting_leaves_other_servers_alone(self):
        self.insert()
        self.insert(guild=OTHER_GUILD)
        server_config_repo.update_server_config_param(GUILD, "reaction_threshold", 2, self.connection)

        self.assertEqual(13, server_config_repo.get_parameter_value(self.connection, OTHER_GUILD, "reaction_threshold"))

    def test_refuses_a_column_that_is_not_a_setting(self):
        self.insert()

        with self.assertRaises(ValueError):
            server_config_repo.update_server_config_param(GUILD, "guild_id", 1, self.connection)
        with self.assertRaises(ValueError):
            server_config_repo.get_parameter_value(self.connection, GUILD, "missing_since")
        self.assertTrue(server_config_repo.check_if_guild_exists(self.connection, GUILD))

    def test_a_server_added_with_only_its_id_gets_the_table_defaults(self):
        server_config_repo.insert_server_config(self.connection, GUILD)
        server = server_config_repo.get_server_classes(self.connection)[GUILD]

        self.assert_settings(server, {"reaction_threshold": 5, "post_due_date": 30, "require_image_or_video": False,
                                      "count_in_global_profiles": True, "custom_emoji_check_logic": False})

    def test_adding_a_server_twice_keeps_the_first(self):
        self.insert()
        self.insert(reaction_threshold=2)

        self.assertEqual(13, server_config_repo.get_parameter_value(self.connection, GUILD, "reaction_threshold"))

    def test_the_reaction_settings_in_one_read(self):
        self.insert()

        self.assertEqual({"reaction_count_calculation_method": "unique_users",
                          "include_author_in_reaction_calculation": False, "custom_emoji_check_logic": True,
                          "whitelisted_emojis": ["🔥", "<:custom:123456789012345678>"]},
                         server_config_repo.get_reaction_config(self.connection, GUILD))

    def test_the_reaction_settings_of_an_unknown_server(self):
        self.assertEqual({column: None for column in server_config_repo.REACTION_CONFIG_COLUMNS},
                         server_config_repo.get_reaction_config(self.connection, GUILD))

    def test_servers_with_a_leaderboard(self):
        self.insert()
        self.insert(guild=OTHER_GUILD, leaderboard_setup=False)

        self.assertEqual({GUILD}, server_config_repo.get_guild_ids_with_leaderboard(self.connection))

    def test_deleting_a_server_leaves_other_servers_alone(self):
        self.insert()
        self.insert(guild=OTHER_GUILD)
        server_config_repo.delete_server_config(self.connection, GUILD)

        self.assertFalse(server_config_repo.check_if_guild_exists(self.connection, GUILD))
        self.assertTrue(server_config_repo.check_if_guild_exists(self.connection, OTHER_GUILD))


class FakeResponse:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.deferred = False

    async def send_message(self, content=None, embed=None, ephemeral=False, view=None):
        self.sent.append((content, ephemeral))

    async def edit_message(self, content=None, view=None):
        self.edits.append((content, view))

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = True

    def is_done(self):
        return self.deferred or bool(self.sent)


class FakeFollowup:
    def __init__(self):
        self.sent = []
        self.views = []

    async def send(self, content=None, embed=None, ephemeral=False, file=None, files=None, view=None):
        self.sent.append((content, ephemeral, list(files or []) + ([file] if file is not None else [])))
        self.views.append(view)


def interaction(user_id=101, manage_guild=True):
    user = types.SimpleNamespace(id=user_id, name="Member", bot=False,
                                 guild_permissions=types.SimpleNamespace(manage_guild=manage_guild))
    edits = []

    async def edit_original_response(content=None, view=None):
        edits.append((content, view))

    return types.SimpleNamespace(user=user, guild=types.SimpleNamespace(id=GUILD, name="Server"), guild_id=GUILD,
                                 channel_id=555, response=FakeResponse(), followup=FakeFollowup(),
                                 command=types.SimpleNamespace(name="test"), original_edits=edits,
                                 edit_original_response=edit_original_response,
                                 is_guild_integration=lambda: True)


@skip_without_database
class CommandsEndToEndTests(DatabaseTestCase):
    """Real commands, real rows: the command, the repository and the table have to agree."""

    def setUp(self):
        super().setUp()
        server_config_repo.insert_server_config(self.connection, GUILD)
        server_config_repo.insert_server_config(self.connection, OTHER_GUILD)

        async def no_log(*_args, **_kwargs):
            pass

        for target, name, value in ((utils, "logging", no_log),
                                    (main, "connection_pool", SingleConnectionPool(self.connection)),
                                    (main, "bot_loaded", True),
                                    (main, "daily_command_cooldowns", {}),
                                    (main, "server_classes", {GUILD: build_server(guild_id=GUILD),
                                                              OTHER_GUILD: build_server(guild_id=OTHER_GUILD)})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_a_setting_command_writes_the_table_and_the_cache(self):
        await main.count_in_global_profiles.callback(interaction(), False)

        self.assertFalse(server_config_repo.get_parameter_value(self.connection, GUILD, "count_in_global_profiles"))
        self.assertFalse(main.server_classes[GUILD].count_in_global_profiles)
        self.assertTrue(server_config_repo.get_parameter_value(self.connection, OTHER_GUILD, "count_in_global_profiles"))

    async def test_a_member_without_manage_server_changes_nothing(self):
        await main.count_in_global_profiles.callback(interaction(manage_guild=False), False)

        self.assertTrue(server_config_repo.get_parameter_value(self.connection, GUILD, "count_in_global_profiles"))

    async def open_my_data(self, user_id=101):
        command = interaction(user_id=user_id)
        await main.my_data.callback(command)
        return command, command.followup.views[0]

    async def test_the_totals_button_stores_and_clears_the_choice(self):
        _command, view = await self.open_my_data()
        await view.totals_button.callback(interaction())
        self.assertTrue(global_profile_repo.is_hidden(self.connection, 101))

        await view.totals_button.callback(interaction())
        self.assertFalse(global_profile_repo.is_hidden(self.connection, 101))

    async def test_my_data_exports_the_real_rows(self):
        posted = datetime.datetime(2026, 9, 1, 12, 0)
        hall_of_fame_message_repo.insert_hall_of_fame_message(self.connection, 1, 500, GUILD, 5001, 9, 101, posted)
        hall_of_fame_message_repo.insert_hall_of_fame_message(self.connection, 2, 500, GUILD, 5002, 4, 202, posted)
        command, view = await self.open_my_data()
        self.assertIn("1 featured post,", command.followup.sent[0][0])
        pressed = interaction()
        await view.download_button.callback(pressed)

        content, ephemeral, files = pressed.followup.sent[0]
        self.assertEqual(1, len(files))
        export = json.loads(files[0].fp.read())
        self.assertTrue(ephemeral)
        self.assertEqual(["1"], [post["message_id"] for post in export["featured_posts"]])
        self.assertEqual(str(posted), export["featured_posts"][0]["created_at"])
        self.assertEqual("101", export["user_id"])

    async def test_my_data_for_a_member_with_nothing_stored(self):
        command, view = await self.open_my_data(user_id=777)

        content, ephemeral, files = command.followup.sent[0]
        self.assertIn(messages.MY_DATA_NOTHING_AT_ALL, content)
        self.assertEqual([], files)
        self.assertTrue(ephemeral)
        self.assertTrue(view.download_button.disabled)
        self.assertTrue(view.delete_button.disabled)


if __name__ == "__main__":
    unittest.main()
