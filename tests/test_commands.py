"""Tests for the embeds the slash commands reply with.

These are what a member actually sees, and they are built from database rows that may be missing,
partial, or point at members who have since left the server. The tests here are mostly about those
edges: a member with no history, a leaderboard entry whose member is gone, and the ranks and totals
landing in the reply rather than being quietly dropped.
"""

import types
import unittest
from unittest import mock

import discord

import commands
from constants import version
from repositories import server_config_repo, server_user_repo

MONTH_EMOJI = "<:month:1>"
ALL_TIME_EMOJI = "<:all_time:2>"


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.deferred = False

    async def send_message(self, content=None, embed=None, ephemeral=False):
        self.messages.append(embed if embed is not None else content)

    async def defer(self):
        self.deferred = True


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, embed=None):
        self.messages.append(embed if embed is not None else content)


class FakeMember:
    def __init__(self, user_id, name):
        self.id = user_id
        self.name = name
        self.display_avatar = types.SimpleNamespace(url=f"https://cdn.example/{user_id}.png")


class FakeGuild:
    def __init__(self, members=None, guild_id=200, name="Test Server"):
        self.id = guild_id
        self.name = name
        self.members = members if members is not None else {}

    async def fetch_member(self, user_id):
        if user_id not in self.members:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Member")
        return self.members[user_id]


class FakeInteraction:
    def __init__(self, guild=None):
        self.guild = guild if guild is not None else FakeGuild()
        self.guild_id = self.guild.id
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.user = FakeMember(77, "Author")


def field_named(embed, fragment):
    """The first field whose name contains the fragment, so tests do not depend on ordering."""
    for field in embed.fields:
        if fragment in (field.name or ""):
            return field
    return None


class GetHelpTests(unittest.IsolatedAsyncioTestCase):
    async def test_replies_with_an_embed(self):
        interaction = FakeInteraction()
        await commands.get_help(interaction)

        self.assertEqual(1, len(interaction.response.messages))
        self.assertIsInstance(interaction.response.messages[0], discord.Embed)

    async def test_names_the_version_it_is_running(self):
        interaction = FakeInteraction()
        await commands.get_help(interaction)

        self.assertIn(version.VERSION, interaction.response.messages[0].footer.text)

    async def test_lists_the_recognition_commands(self):
        """The commands that make the bot more than a board are the ones worth discovering."""
        interaction = FakeInteraction()
        await commands.get_help(interaction)

        listed = " ".join(field.name or "" for field in interaction.response.messages[0].fields)
        for command in ("leaderboard", "user_profile", "hof_wrapped", "server_hof_wrapped"):
            with self.subTest(command=command):
                self.assertIn(command, listed)

    async def test_points_at_the_support_server(self):
        interaction = FakeInteraction()
        await commands.get_help(interaction)

        values = " ".join(field.value or "" for field in interaction.response.messages[0].fields)
        self.assertIn("discord.gg", values)


class SetReactionThresholdTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_the_threshold_for_the_server_it_was_used_in(self):
        interaction = FakeInteraction()
        with mock.patch.object(server_config_repo, "update_server_config_param") as update:
            await commands.set_reaction_threshold(interaction, 7, connection=object())

        self.assertEqual((200, "reaction_threshold", 7), update.call_args.args[:3])

    async def test_confirms_the_new_threshold(self):
        interaction = FakeInteraction()
        with mock.patch.object(server_config_repo, "update_server_config_param"):
            await commands.set_reaction_threshold(interaction, 7, connection=object())

        self.assertIn("set to 7", interaction.response.messages[0])


class UserServerProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.interaction = FakeInteraction()
        self.user = FakeMember(77, "Champion")
        self.stats = {
            "this_month_hall_of_fame_messages": 4,
            "total_hall_of_fame_messages": 40,
            "this_month_hall_of_fame_message_reactions": 60,
            "total_hall_of_fame_message_reactions": 600,
            "monthly_message_rank": 2,
            "total_message_rank": 1,
            "monthly_reaction_rank": 3,
            "total_reaction_rank": 5,
        }

    def patch_top_of_stat(self, monthly=False, all_time=False):
        def is_top(_connection, _user_id, _guild_id, stat):
            if stat == "this_month_hall_of_fame_messages":
                return monthly
            return all_time

        patcher = mock.patch.object(server_user_repo, "check_if_user_is_top_of_stat", is_top)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def run_command(self, stats):
        await commands.user_server_profile(self.interaction, self.user, stats, object(),
                                           MONTH_EMOJI, ALL_TIME_EMOJI)
        return self.interaction.response.messages[0]

    async def test_shows_the_totals_and_the_ranks(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("40", field_named(embed, "Total Hall of Fame Messages").value)
        self.assertIn("Rank: 1", field_named(embed, "Total Hall of Fame Messages").value)

    async def test_shows_the_monthly_standing(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("4", field_named(embed, "This Month's Hall of Fame Messages").value)
        self.assertIn("Rank: 2", field_named(embed, "This Month's Hall of Fame Messages").value)

    async def test_shows_the_reactions_earned(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("600", field_named(embed, "Total Reactions Received").value)

    async def test_crowns_the_monthly_champion(self):
        self.patch_top_of_stat(monthly=True)
        embed = await self.run_command(self.stats)

        self.assertIsNotNone(field_named(embed, "Monthly Hall of Fame Champion"))

    async def test_crowns_the_all_time_champion(self):
        self.patch_top_of_stat(all_time=True)
        embed = await self.run_command(self.stats)

        self.assertIsNotNone(field_named(embed, "All-Time Hall of Fame Champion"))

    async def test_crowns_nobody_who_is_not_first(self):
        self.patch_top_of_stat(monthly=False, all_time=False)
        embed = await self.run_command(self.stats)

        self.assertIsNone(field_named(embed, "Champion"))

    async def test_shows_zeros_for_a_member_with_no_history(self):
        """A member who has never been featured still gets a profile rather than an error."""
        self.patch_top_of_stat()
        embed = await self.run_command(None)

        self.assertIn("0", field_named(embed, "Total Hall of Fame Messages").value)

    async def test_does_not_crown_a_member_with_no_history(self):
        self.patch_top_of_stat(monthly=True, all_time=True)
        embed = await self.run_command(None)

        self.assertIsNone(field_named(embed, "Champion"))

    async def test_shows_the_member_it_was_asked_about(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("Champion", embed.title)
        self.assertEqual(self.user.display_avatar.url, embed.thumbnail.url)

    async def test_says_when_the_figures_were_last_worked_out(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("24 hours", embed.footer.text)


class ServerLeaderboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.members = {77: FakeMember(77, "Champion"), 88: FakeMember(88, "Runner Up")}
        self.interaction = FakeInteraction(guild=FakeGuild(members=self.members))

    def patch_top_users(self, rows_by_stat=None):
        rows_by_stat = rows_by_stat if rows_by_stat is not None else {}
        default = [
            {"user_id": 77, "this_month_hall_of_fame_messages": 4, "total_hall_of_fame_messages": 40,
             "this_month_hall_of_fame_message_reactions": 60, "total_hall_of_fame_message_reactions": 600},
            {"user_id": 88, "this_month_hall_of_fame_messages": 2, "total_hall_of_fame_messages": 20,
             "this_month_hall_of_fame_message_reactions": 30, "total_hall_of_fame_message_reactions": 300},
        ]

        def get_top(_connection, _guild_id, stat, limit=10):
            return rows_by_stat.get(stat, default)

        patcher = mock.patch.object(server_user_repo, "get_top_users_by_stat", get_top)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def run_command(self):
        await commands.server_leaderboard(self.interaction, object(), MONTH_EMOJI, ALL_TIME_EMOJI)
        return self.interaction.followup.messages[0]

    async def test_answers_before_building_the_board(self):
        """Fetching members takes long enough that the interaction times out without this."""
        self.patch_top_users()
        await self.run_command()

        self.assertTrue(self.interaction.response.deferred)

    async def test_sends_the_board_as_a_follow_up(self):
        self.patch_top_users()
        embed = await self.run_command()

        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual([], self.interaction.response.messages)

    async def test_ranks_the_members(self):
        self.patch_top_users()
        board = field_named(await self.run_command(), "Leaderboard").value

        self.assertIn("1. Champion: 4 messages", board)
        self.assertIn("2. Runner Up: 2 messages", board)

    async def test_shows_all_four_boards(self):
        self.patch_top_users()
        board = field_named(await self.run_command(), "Leaderboard").value

        self.assertIn("Top 5 This Month's Hall of Fame Messages", board)
        self.assertIn("Top 5 All-Time Hall of Fame Messages", board)
        self.assertIn("Top 5 This Month's Reactions", board)
        self.assertIn("Top 5 All-Time Reactions", board)

    async def test_counts_reactions_separately_from_messages(self):
        self.patch_top_users()
        board = field_named(await self.run_command(), "Leaderboard").value

        self.assertIn("600 reactions", board)
        self.assertIn("40 messages", board)

    async def test_keeps_a_member_who_has_left_the_server(self):
        """The standing was earned, so it stays on the board under a placeholder name."""
        self.patch_top_users(rows_by_stat={"this_month_hall_of_fame_messages": [
            {"user_id": 999, "this_month_hall_of_fame_messages": 9}]})
        board = field_named(await self.run_command(), "Leaderboard").value

        self.assertIn("1. Unknown Member: 9 messages", board)

    async def test_builds_an_empty_board_for_a_server_with_no_history(self):
        self.patch_top_users(rows_by_stat={stat: [] for stat in server_user_repo.ALLOWED_STAT_FIELDS})
        board = field_named(await self.run_command(), "Leaderboard").value

        self.assertIn("Top 5 This Month's Hall of Fame Messages", board)

    async def test_names_the_server(self):
        self.patch_top_users()
        embed = await self.run_command()

        self.assertIn("Test Server", embed.title)


if __name__ == "__main__":
    unittest.main()
