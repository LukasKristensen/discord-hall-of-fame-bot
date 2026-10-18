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
import hof_wrapped
from constants import version
from repositories import server_config_repo, server_user_repo, hall_of_fame_message_repo
from translations import messages

MONTH_EMOJI = "<:month:1>"
ALL_TIME_EMOJI = "<:all_time:2>"


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.views = []
        self.deferred = False

    async def send_message(self, content=None, embed=None, ephemeral=False, view=None):
        self.messages.append(embed if embed is not None else content)
        self.views.append(view)

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

        listed = field_named(interaction.response.messages[0], "For everyone").value
        for command in ("leaderboard", "user_profile", "hof_wrapped", "server_hof_wrapped"):
            with self.subTest(command=command):
                self.assertIn(command, listed)

    async def test_lists_every_setting_command(self):
        embed = commands.build_help_embed()

        listed = embed.description + " ".join(field.value for field in embed.fields)
        for command in ("set_hall_of_fame_channel", "set_reaction_threshold", "calculation_method",
                        "get_server_config", "set_post_due_date", "include_authors_reaction",
                        "ignore_bot_messages", "require_image_or_video", "allow_messages_in_hof_channel",
                        "hide_hof_post_below_threshold", "custom_emoji_check_logic", "whitelist_emoji",
                        "unwhitelist_emoji", "clear_whitelist", "feedback"):
            with self.subTest(command=command):
                self.assertIn(f"</{command}:", listed)

    async def test_fits_within_discords_embed_limits(self):
        embed = commands.build_help_embed()

        self.assertLessEqual(len(embed), 6000)
        for field in embed.fields:
            with self.subTest(field=field.name):
                self.assertLessEqual(len(field.value), 1024)

    async def test_points_at_the_support_server(self):
        interaction = FakeInteraction()
        await commands.get_help(interaction)

        values = " ".join(field.value or "" for field in interaction.response.messages[0].fields)
        self.assertIn("discord.gg", values)

    async def test_offers_invite_vote_and_support_buttons(self):
        interaction = FakeInteraction()
        await commands.get_help(interaction)

        self.assertEqual([messages.INVITE_URL, messages.VOTE_URL, messages.SUPPORT_SERVER_URL],
                         [button.url for button in interaction.response.views[0].children])


class InviteUrlTests(unittest.TestCase):
    """The install link everything shares. Without scopes and permissions it relied on portal defaults."""

    def test_asks_for_exactly_the_permissions_the_bot_uses(self):
        expected = discord.Permissions(view_channel=True, send_messages=True, read_message_history=True,
                                       embed_links=True, use_external_emojis=True, manage_messages=True,
                                       manage_channels=True, manage_roles=True, attach_files=True,
                                       add_reactions=True, send_messages_in_threads=True)
        self.assertEqual(expected.value, messages.INVITE_PERMISSIONS)
        self.assertIn(f"permissions={expected.value}", messages.INVITE_URL)

    def test_installs_the_bot_and_its_commands_to_a_server(self):
        self.assertIn("scope=bot+applications.commands", messages.INVITE_URL)
        self.assertIn("integration_type=0", messages.INVITE_URL)
        self.assertIn("client_id=1177041673352663070", messages.INVITE_URL)


class BoardTopicTests(unittest.TestCase):
    def test_carries_the_install_link(self):
        self.assertIn(messages.APP_DIRECTORY_URL, messages.HOF_CHANNEL_TOPIC)

    def test_keeps_the_link_short(self):
        # The full OAuth link took up most of the channel header
        self.assertNotIn("oauth2", messages.HOF_CHANNEL_TOPIC)

    def test_fits_in_a_channel_topic(self):
        self.assertLessEqual(len(messages.HOF_CHANNEL_TOPIC), 1024)

    def test_is_not_mistaken_for_an_old_topic(self):
        # Otherwise the daily sweep would rewrite the current topic every day
        self.assertNotIn(messages.HOF_CHANNEL_TOPIC, messages.LEGACY_HOF_CHANNEL_TOPICS)


def link_buttons(view):
    return [(button.label, button.url) for button in view.children]


class LinkButtonTests(unittest.IsolatedAsyncioTestCase):
    """The buttons under /invite, /vote and /help. Views need a running event loop, hence async tests."""

    async def test_invite_offers_the_install_link_first_then_support(self):
        self.assertEqual([(messages.INVITE_BUTTON, messages.INVITE_URL),
                          (messages.SUPPORT_SERVER_BUTTON, messages.SUPPORT_SERVER_URL)],
                         link_buttons(commands.build_invite_view()))

    async def test_vote_offers_only_the_vote_link(self):
        self.assertEqual([(messages.VOTE_BUTTON, messages.VOTE_URL)], link_buttons(commands.build_vote_view()))

    async def test_buttons_are_links_that_never_expire(self):
        """A non-link button would need a callback, and a timeout would grey the buttons out."""
        for view in (commands.build_invite_view(), commands.build_vote_view(), commands.build_help_view()):
            with self.subTest(view=link_buttons(view)):
                self.assertIsNone(view.timeout)
                for button in view.children:
                    self.assertEqual(discord.ButtonStyle.link, button.style)
                    self.assertTrue(button.url.startswith("https://"))

    async def test_labels_fit_discords_button_limit(self):
        for label in (messages.INVITE_BUTTON, messages.VOTE_BUTTON, messages.SUPPORT_SERVER_BUTTON):
            with self.subTest(label=label):
                self.assertLessEqual(len(label), 80)


def server_config(**overrides):
    config = {
        "hall_of_fame_channel_id": 555,
        "reaction_threshold": 7,
        "post_due_date": 30,
        "include_author_in_reaction_calculation": True,
        "allow_messages_in_hof_channel": False,
        "custom_emoji_check_logic": False,
        "whitelisted_emojis": [],
        "ignore_bot_messages": True,
        "reaction_count_calculation_method": "unique_users",
        "hide_hof_post_below_threshold": False,
        "require_image_or_video": False,
        "count_in_global_profiles": True,
    }
    config.update(overrides)
    return types.SimpleNamespace(**config)


class BuildServerConfigEmbedTests(unittest.TestCase):
    def test_shows_the_board_channel_threshold_and_counting_method(self):
        embed = commands.build_server_config_embed(FakeGuild(), server_config())
        board = field_named(embed, "Board").value

        self.assertIn("<#555>", board)
        self.assertIn("7", board)
        self.assertIn("Unique members who reacted", board)

    def test_marks_each_toggle_on_or_off(self):
        embed = commands.build_server_config_embed(FakeGuild(), server_config())
        qualifies = field_named(embed, "What qualifies").value

        self.assertIn("✅ Author's own reaction counts", qualifies)
        self.assertIn("❌ Only posts with an image or video", qualifies)

    def test_keeps_the_values_in_a_single_column(self):
        """A thumbnail narrows the text and a command link per row wraps the values, so the reply
        reads worse than the plain code block it replaced. Both are deliberately left out."""
        embed = commands.build_server_config_embed(FakeGuild(), server_config())

        self.assertIsNone(embed.thumbnail.url)
        for field in embed.fields[:3]:
            with self.subTest(field=field.name):
                self.assertNotIn("</", field.value)

    def test_says_the_whitelist_is_off_when_every_emoji_counts(self):
        embed = commands.build_server_config_embed(FakeGuild(), server_config(whitelisted_emojis=["😂"]))

        self.assertIsNotNone(field_named(embed, "whitelist · off"))
        self.assertNotIn("😂", field_named(embed, "whitelist").value)

    def test_lists_the_whitelisted_emojis_when_the_whitelist_is_on(self):
        embed = commands.build_server_config_embed(
            FakeGuild(), server_config(custom_emoji_check_logic=True, whitelisted_emojis=["😂", "🔥"]))

        self.assertIn("😂 🔥", field_named(embed, "whitelist · on").value)

    def test_keeps_a_long_whitelist_within_discords_field_limit(self):
        """Discord rejects the whole reply when one field is too long, so the command would fail."""
        emojis = [f"<:custom_emoji_{index}:{10**17 + index}>" for index in range(100)]
        embed = commands.build_server_config_embed(
            FakeGuild(), server_config(custom_emoji_check_logic=True, whitelisted_emojis=emojis))
        value = field_named(embed, "whitelist").value

        self.assertLessEqual(len(value), 1024)
        self.assertIn("more", value)


class SetReactionThresholdTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_the_threshold_for_the_server_it_was_used_in(self):
        interaction = FakeInteraction()
        with mock.patch.object(server_config_repo, "update_server_config_param") as update:
            await commands.set_reaction_threshold(interaction, 7, object(), "total reactions",
                                                  types.SimpleNamespace(reaction_threshold=5))

        self.assertEqual((200, "reaction_threshold", 7), update.call_args.args[:3])

    async def test_confirms_the_new_threshold(self):
        interaction = FakeInteraction()
        with mock.patch.object(server_config_repo, "update_server_config_param"):
            await commands.set_reaction_threshold(interaction, 7, object(), "total reactions",
                                                  types.SimpleNamespace(reaction_threshold=5))

        self.assertIn("**7**", interaction.response.messages[0])

    async def test_says_how_the_threshold_is_counted(self):
        """The same number means different things under each calculation method."""
        interaction = FakeInteraction()
        with mock.patch.object(server_config_repo, "update_server_config_param"):
            await commands.set_reaction_threshold(interaction, 7, object(), "total reactions",
                                                  types.SimpleNamespace(reaction_threshold=5))

        self.assertIn("7 reactions, counted as: total reactions", interaction.response.messages[0])

    async def test_does_not_pluralise_a_single_reaction(self):
        interaction = FakeInteraction()
        with mock.patch.object(server_config_repo, "update_server_config_param"):
            await commands.set_reaction_threshold(interaction, 1, object(), "total reactions",
                                                  types.SimpleNamespace(reaction_threshold=5))

        self.assertIn("1 reaction,", interaction.response.messages[0])

    async def test_updates_the_cached_threshold_before_replying(self):
        """Reactions handled while the reply is sent, or after it fails, must use the new threshold."""
        server_config = types.SimpleNamespace(reaction_threshold=5)
        interaction = FakeInteraction()
        seen_when_replying = []

        async def reply(*_args, **_kwargs):
            seen_when_replying.append(server_config.reaction_threshold)
            raise RuntimeError("interaction expired")

        interaction.response.send_message = reply
        with mock.patch.object(server_config_repo, "update_server_config_param"):
            with self.assertRaises(RuntimeError):
                await commands.set_reaction_threshold(interaction, 7, object(), "total reactions", server_config)

        self.assertEqual([7], seen_when_replying)
        self.assertEqual(7, server_config.reaction_threshold)


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
        # The highlights read the database too; these tests are about the columns and the crowns
        for target, name, replacement in (
                (hall_of_fame_message_repo, "get_member_highlights",
                 lambda *_args: {"best_post": None, "last_featured": None}),
                (hall_of_fame_message_repo, "get_member_badge_facts",
                 lambda *_args: {"posts_by_month": [], "first_featured": None, "biggest_post": 0,
                                 "champion_months": 0}),
                (server_user_repo, "get_stat_at_rank", lambda *_args: None)):
            patcher = mock.patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

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

        self.assertIn("**40** posts · #1", field_named(embed, "All time").value)

    async def test_shows_the_monthly_standing(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("**4** posts · #2", field_named(embed, "This month").value)
        self.assertIn("**60** reactions · #3", field_named(embed, "This month").value)

    async def test_shows_no_monthly_rank_for_a_member_with_nothing_this_month(self):
        self.patch_top_of_stat()
        stats = dict(self.stats, this_month_hall_of_fame_messages=0, monthly_message_rank=None,
                     this_month_hall_of_fame_message_reactions=0, monthly_reaction_rank=None)
        embed = await self.run_command(stats)

        self.assertIn("**0** posts · -", field_named(embed, "This month").value)
        self.assertIn("**0** reactions · -", field_named(embed, "This month").value)

    async def test_shows_the_reactions_earned(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("**600** reactions · #5", field_named(embed, "All time").value)

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

        self.assertIn("**0** posts", field_named(embed, "All time").value)

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

    async def test_points_at_the_invite_command(self):
        self.patch_top_of_stat()
        embed = await self.run_command(self.stats)

        self.assertIn("/invite", embed.footer.text)


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

    async def test_footer_says_when_it_updates_and_points_at_the_invite_command(self):
        self.patch_top_users()
        footer = (await self.run_command()).footer.text

        self.assertIn("24 hours", footer)
        self.assertIn("/invite", footer)

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


class HofWrappedEmbedTests(unittest.IsolatedAsyncioTestCase):
    """The card /hof_wrapped answers with, built from a member's precomputed Wrapped row."""

    def wrapped_row(self):
        return {"reaction_count": 12, "hof_message_posts": 3, "fan_of_users": "{}", "users_fans": "{}",
                "most_used_channels": "{}", "most_used_emojis": "{}",
                "user_ranks": '{"hallOfFameMessagePosts": 1, "mostUsedChannels": 2, "mostUsedEmojis": 3, '
                              '"usersFans": 4, "fanOfUsers": 5}',
                "most_reacted_post_message_id": None, "most_reacted_post_channel_id": None,
                "most_reacted_post_reaction_count": 0}

    async def test_footer_points_at_the_invite_command(self):
        member = types.SimpleNamespace(id=77, mention="<@77>", avatar=None,
                                       default_avatar=types.SimpleNamespace(url="https://cdn.example/0.png"))
        embed = await hof_wrapped.create_embed(member, self.wrapped_row(), bot=None)

        self.assertEqual(messages.INVITE_FOOTER, embed.footer.text)
