"""Tests for what happens when the bot joins a server, and when it leaves one.

Joining is the only part of the bot a server owner sees before anything works: a channel is created,
locked down so members cannot post in it, seeded with a threshold picked from the server's size, and
introduced with a welcome message. Leaving has to undo all of it, across every table, or a server
that removes and re-adds the bot inherits its old board.
"""

import unittest
from unittest import mock

import utils
from caches import ExpiringSet
from enums import calculation_method_type
from repositories import (hall_of_fame_message_repo, hof_wrapped_repo, server_config_repo,
                          server_user_repo)

from tests.fakes import FakeConnection, FakePermissions

GUILD_ID = 200
CHANNEL_ID = 555


class FakeCreatedChannel:
    def __init__(self, channel_id=CHANNEL_ID, name="hall-of-fame"):
        self.id = channel_id
        self.name = name
        self.edits = []
        self.permissions = []
        self.sent = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)

    async def set_permissions(self, target, **kwargs):
        self.permissions.append((target, kwargs))

    async def send(self, content=None):
        self.sent.append(content)


class FakeBotMember:
    def __init__(self, **permissions):
        self.guild_permissions = FakePermissions(**permissions)


class FakeJoinedGuild:
    def __init__(self, member_count=50, manage_channels=True, guild_id=GUILD_ID):
        self.id = guild_id
        self.name = "Test Server"
        self.member_count = member_count
        self.me = FakeBotMember(manage_channels=manage_channels)
        self.default_role = "@everyone"
        self.created_channels = []

    async def create_text_channel(self, name):
        channel = FakeCreatedChannel(name=name)
        self.created_channels.append(channel)
        return channel


class SetupTestCase(unittest.IsolatedAsyncioTestCase):
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


class CreateDatabaseContextTests(SetupTestCase):
    def setUp(self):
        super().setUp()
        self.inserted = []
        self.existing_guild = False
        self.deleted = []

        self.patch(server_config_repo, "check_if_guild_exists",
                   lambda _connection, _guild_id: self.existing_guild)
        self.patch(server_config_repo, "insert_server_with_parameters",
                   lambda *args: self.inserted.append(args))
        self.patch(server_config_repo, "delete_server_config",
                   lambda _connection, guild_id: self.deleted.append(guild_id))

    async def join(self, guild=None, custom_channel=None):
        guild = guild if guild is not None else FakeJoinedGuild()
        created = await utils.create_database_context(object(), guild, FakeConnection(), custom_channel)
        return guild, created

    async def test_creates_a_hall_of_fame_channel(self):
        guild, _ = await self.join()

        self.assertEqual(["hall-of-fame"], [channel.name for channel in guild.created_channels])

    async def test_uses_a_channel_it_was_pointed_at_instead_of_making_one(self):
        """/set_hall_of_fame_channel reuses this path, and must not leave a stray channel behind."""
        custom = FakeCreatedChannel(channel_id=777)
        guild, created = await self.join(custom_channel=custom)

        self.assertEqual([], guild.created_channels)
        self.assertEqual(777, created.hall_of_fame_channel_id)

    async def test_lets_members_read_the_board_but_not_post_in_it(self):
        guild, _ = await self.join()
        channel = guild.created_channels[0]

        everyone = [kwargs for target, kwargs in channel.permissions if target == "@everyone"][0]
        self.assertTrue(everyone["read_messages"])
        self.assertFalse(everyone["send_messages"])

    async def test_keeps_the_right_to_post_for_itself(self):
        guild, _ = await self.join()
        channel = guild.created_channels[0]

        bot_permissions = [kwargs for target, kwargs in channel.permissions if target is guild.me][0]
        self.assertTrue(bot_permissions["send_messages"])

    async def test_leaves_the_channel_untouched_without_the_permission_to_manage_it(self):
        guild, _ = await self.join(FakeJoinedGuild(manage_channels=False))
        channel = guild.created_channels[0]

        self.assertEqual([], channel.permissions)
        self.assertEqual([], channel.edits)

    async def test_introduces_itself_in_the_new_channel(self):
        guild, _ = await self.join()

        self.assertEqual(1, len(guild.created_channels[0].sent))
        self.assertIn("Welcome to the Hall of Fame", guild.created_channels[0].sent[0])

    async def test_names_the_starting_threshold_in_the_welcome_message(self):
        guild, created = await self.join(FakeJoinedGuild(member_count=30))

        self.assertEqual(5, created.reaction_threshold)
        self.assertIn("5 or more", guild.created_channels[0].sent[0])

    async def test_scales_the_starting_threshold_with_the_server(self):
        for member_count, expected in ((1, 1), (3, 2), (5, 3), (10, 4), (20, 5), (40, 6), (50, 7), (5000, 7)):
            with self.subTest(member_count=member_count):
                _, created = await self.join(FakeJoinedGuild(member_count=member_count))
                self.assertEqual(expected, created.reaction_threshold)

    async def test_records_the_server_with_the_channel_it_will_post_to(self):
        guild, _ = await self.join()

        _connection, guild_id, channel_id = self.inserted[0][:3]
        self.assertEqual(GUILD_ID, guild_id)
        self.assertEqual(guild.created_channels[0].id, channel_id)

    async def test_starts_with_the_recommended_counting_method(self):
        _, created = await self.join()

        self.assertEqual(calculation_method_type.MOST_REACTIONS_ON_EMOJI,
                         created.reaction_count_calculation_method)

    async def test_starts_with_the_leaderboard_off(self):
        """It was turned off by default because it confused first time users."""
        _, created = await self.join()

        self.assertFalse(created.leaderboard_setup)
        self.assertEqual([], created.leaderboard_message_ids)

    async def test_starts_with_chat_in_the_board_turned_off(self):
        _, created = await self.join()

        self.assertFalse(created.allow_messages_in_hof_channel)

    async def test_clears_out_a_configuration_left_from_an_earlier_visit(self):
        """A server that removed and re-added the bot must not inherit its old configuration."""
        self.existing_guild = True
        await self.join()

        self.assertEqual([GUILD_ID], self.deleted)

    async def test_says_so_when_it_replaces_an_earlier_configuration(self):
        self.existing_guild = True
        await self.join()

        self.assertTrue(any("already exists" in entry for entry in self.logged))


class DeleteDatabaseContextTests(unittest.TestCase):
    def test_removes_the_server_from_every_table(self):
        connection = FakeConnection()
        calls = []

        with mock.patch.object(hall_of_fame_message_repo, "delete_hall_of_fame_messages_for_guild",
                               lambda _c, guild_id: calls.append(("messages", guild_id))), \
             mock.patch.object(server_user_repo, "delete_server_users",
                               lambda _c, guild_id: calls.append(("users", guild_id))), \
             mock.patch.object(server_config_repo, "delete_server_config",
                               lambda _c, guild_id: calls.append(("config", guild_id))), \
             mock.patch.object(hof_wrapped_repo, "delete_hof_wrapped_for_guild",
                               lambda _c, guild_id: calls.append(("wrapped", guild_id))):
            utils.delete_database_context(GUILD_ID, connection)

        self.assertEqual([("messages", GUILD_ID), ("users", GUILD_ID),
                          ("config", GUILD_ID), ("wrapped", GUILD_ID)], calls)


class FakeHistoryMessage:
    def __init__(self, content):
        self.content = content


class FakeGuildChannel:
    def __init__(self, name, position, permissions=None, history=(), fails=False):
        self.name = name
        self.position = position
        self.permissions = permissions if permissions is not None else FakePermissions()
        self.history_messages = list(history)
        self.fails = fails
        self.sent = []

    def permissions_for(self, _member):
        return self.permissions

    def history(self, limit=None):
        messages = self.history_messages[:limit]

        async def iterator():
            for message in messages:
                yield message

        return iterator()

    async def send(self, content):
        if self.fails:
            raise RuntimeError("cannot post here after all")
        self.sent.append(content)


class FakeGuildWithTextChannels:
    def __init__(self, channels):
        self.id = GUILD_ID
        self.name = "Test Server"
        self.me = object()
        self.text_channels = channels


class SendMessageToHighestPrioChannelTests(SetupTestCase):
    async def send(self, guild, content="The bot is missing a permission", history_limit=100):
        await utils.send_message_to_highest_prio_channel(object(), guild, content, history_limit)

    async def test_posts_in_the_first_channel_it_can(self):
        first = FakeGuildChannel("general", position=0)
        second = FakeGuildChannel("random", position=1)
        await self.send(FakeGuildWithTextChannels([second, first]))

        self.assertEqual(1, len(first.sent))
        self.assertEqual([], second.sent)

    async def test_skips_a_channel_it_cannot_post_in(self):
        locked = FakeGuildChannel("rules", position=0, permissions=FakePermissions(send_messages=False))
        open_channel = FakeGuildChannel("general", position=1)
        await self.send(FakeGuildWithTextChannels([locked, open_channel]))

        self.assertEqual(1, len(open_channel.sent))

    async def test_skips_a_channel_it_cannot_read_the_history_of(self):
        unreadable = FakeGuildChannel("archive", position=0,
                                      permissions=FakePermissions(read_message_history=False))
        open_channel = FakeGuildChannel("general", position=1)
        await self.send(FakeGuildWithTextChannels([unreadable, open_channel]))

        self.assertEqual(1, len(open_channel.sent))

    async def test_says_nothing_twice_in_the_same_channel(self):
        """This runs daily, and a permission that stays missing would post every day."""
        content = "The bot is missing a permission"
        channel = FakeGuildChannel("general", position=0, history=[FakeHistoryMessage(content)])
        await self.send(FakeGuildWithTextChannels([channel]), content)

        self.assertEqual([], channel.sent)

    async def test_gives_up_rather_than_moving_on_when_it_already_warned(self):
        content = "The bot is missing a permission"
        first = FakeGuildChannel("general", position=0, history=[FakeHistoryMessage(content)])
        second = FakeGuildChannel("random", position=1)
        await self.send(FakeGuildWithTextChannels([first, second]), content)

        self.assertEqual([], second.sent)

    async def test_posts_without_checking_the_history_when_asked_not_to(self):
        content = "The bot is missing a permission"
        channel = FakeGuildChannel("general", position=0, history=[FakeHistoryMessage(content)])
        await self.send(FakeGuildWithTextChannels([channel]), content, history_limit=0)

        self.assertEqual([content], channel.sent)

    async def test_moves_on_when_a_channel_refuses_the_message(self):
        failing = FakeGuildChannel("general", position=0, fails=True)
        working = FakeGuildChannel("random", position=1)
        await self.send(FakeGuildWithTextChannels([failing, working]))

        self.assertEqual(1, len(working.sent))

    async def test_says_nothing_in_a_server_with_no_channel_it_can_use(self):
        locked = FakeGuildChannel("rules", position=0, permissions=FakePermissions(send_messages=False))
        await self.send(FakeGuildWithTextChannels([locked]))

        self.assertEqual([], locked.sent)


class PostServerPermsTests(SetupTestCase):
    async def test_records_the_permissions_it_was_given(self):
        guild = FakeJoinedGuild()
        guild.me = FakeBotMember(manage_messages=False)
        await utils.post_server_perms(object(), guild)

        self.assertEqual(1, len(self.logged))
        self.assertIn("Can manage messages: False", self.logged[0])

    async def test_records_the_size_of_the_server(self):
        await utils.post_server_perms(object(), FakeJoinedGuild(member_count=450))

        self.assertIn("Server member count: 450", self.logged[0])


if __name__ == "__main__":
    unittest.main()
