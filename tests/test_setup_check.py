"""Tests for the setup check behind /check_setup, the welcome message button and the report on join.

The check exists because a board that never posts looks the same as a server where nobody reacts. So
the tests are about telling apart the channels the bot is wrongly locked out of from the staff channels
it is left out of on purpose, naming the role that fixes it, and flagging the settings that make
posting impossible.
"""

import datetime
import types
import unittest
from datetime import timezone

import discord

import commands
import setup_check
from enums import calculation_method_type, command_refs
from translations import messages

GUILD_ID = 1
BOARD_ID = 999
NOW = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def perms(view=True, history=True, **others):
    values = dict(view_channel=view, read_message_history=history, send_messages=True, embed_links=True,
                  manage_messages=True)
    values.update(others)
    return types.SimpleNamespace(**values)


class FakeRole:
    def __init__(self, role_id, name="role", position=1, managed=False, **permissions):
        self.id = role_id
        self.name = name
        self.position = position
        self.managed = managed
        self.permissions = types.SimpleNamespace(**permissions)
        self.mention = f"<@&{role_id}>"

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, FakeRole) and other.id == self.id


class FakeChannel:
    """A channel with permissions per target. Anything not named reads the channel."""

    def __init__(self, channel_id, kind=discord.ChannelType.text, bot=None, everyone=None, roles=None):
        self.id = channel_id
        self.type = kind
        self.mention = f"<#{channel_id}>"
        self.bot = bot or perms()
        self.everyone = everyone or perms()
        self.roles = roles or {}

    def permissions_for(self, target):
        if target == "bot":
            return self.bot
        if isinstance(target, FakeRole):
            if target.id == GUILD_ID:
                return self.everyone
            return self.roles.get(target.id, self.everyone)
        raise AssertionError(f"Unexpected permission target {target}")


class FakeGuild:
    def __init__(self, channels=(), roles=(), member_count=50, joined_at=None):
        self.id = GUILD_ID
        self.default_role = FakeRole(GUILD_ID, "@everyone", position=0)
        self.roles = [self.default_role, *roles]
        self.channels = list(channels)
        self.member_count = member_count
        self.me = "bot"
        if joined_at is not None:
            self.me = BotMember(joined_at)


class BotMember(str):
    """The bot's member, compared as "bot" by the fakes, with a join date."""

    def __new__(cls, joined_at):
        member = super().__new__(cls, "bot")
        member.joined_at = joined_at
        return member


def server_config(**overrides):
    values = dict(allow_messages_in_hof_channel=False, custom_emoji_check_logic=False, whitelisted_emojis=[],
                  reaction_threshold=5,
                  reaction_count_calculation_method=calculation_method_type.MOST_REACTIONS_ON_EMOJI)
    values.update(overrides)
    return types.SimpleNamespace(**values)


HIDDEN = perms(view=False)


class ChannelVisibilityTests(unittest.TestCase):
    def test_counts_every_channel_the_bot_reads(self):
        guild = FakeGuild(channels=[FakeChannel(1), FakeChannel(2), FakeChannel(3, discord.ChannelType.voice)])
        visibility = setup_check.channel_visibility(guild, BOARD_ID)

        self.assertEqual(3, len(visibility.readable))
        self.assertEqual(3, visibility.total)
        self.assertEqual([], visibility.blocked)

    def test_leaves_out_the_board_and_channels_nobody_reacts_in(self):
        guild = FakeGuild(channels=[FakeChannel(BOARD_ID), FakeChannel(1),
                                    FakeChannel(2, discord.ChannelType.category)])
        self.assertEqual(1, setup_check.channel_visibility(guild, BOARD_ID).total)

    def test_a_channel_open_to_everyone_but_not_the_bot_is_blocked(self):
        guild = FakeGuild(channels=[FakeChannel(1, bot=HIDDEN)])
        visibility = setup_check.channel_visibility(guild, BOARD_ID)

        self.assertEqual([1], [channel.id for channel in visibility.blocked])

    def test_viewing_without_reading_history_is_not_enough(self):
        """The reaction arrives, but the message it is on cannot be fetched."""
        guild = FakeGuild(channels=[FakeChannel(1, bot=perms(history=False))])
        self.assertEqual(1, len(setup_check.channel_visibility(guild, BOARD_ID).blocked))

    def test_a_channel_behind_a_member_role_is_blocked_and_names_the_role(self):
        member = FakeRole(10, "Member", position=3)
        channels = [FakeChannel(channel_id, bot=HIDDEN, everyone=HIDDEN, roles={10: perms()})
                    for channel_id in (1, 2)]
        visibility = setup_check.channel_visibility(FakeGuild(channels=channels, roles=[member]), BOARD_ID)

        self.assertEqual(2, len(visibility.blocked))
        self.assertEqual(member, visibility.suggested_role)
        self.assertEqual(2, visibility.suggested_role_opens)

    def test_a_staff_only_channel_is_private_rather_than_blocked(self):
        moderator = FakeRole(20, "Mod", position=5, manage_messages=True)
        channel = FakeChannel(1, bot=HIDDEN, everyone=HIDDEN, roles={20: perms()})
        visibility = setup_check.channel_visibility(FakeGuild(channels=[channel], roles=[moderator]), BOARD_ID)

        self.assertEqual([], visibility.blocked)
        self.assertEqual(1, len(visibility.private))
        self.assertIsNone(visibility.suggested_role)

    def test_another_bots_role_is_never_suggested(self):
        other_bot = FakeRole(30, "Other bot", managed=True)
        channel = FakeChannel(1, bot=HIDDEN, everyone=HIDDEN, roles={30: perms()})
        visibility = setup_check.channel_visibility(FakeGuild(channels=[channel], roles=[other_bot]), BOARD_ID)

        self.assertEqual(1, len(visibility.private))

    def test_suggests_the_role_that_opens_the_most_channels(self):
        member = FakeRole(10, "Member", position=2)
        artist = FakeRole(11, "Artist", position=4)
        channels = [FakeChannel(1, bot=HIDDEN, everyone=HIDDEN, roles={10: perms(), 11: perms()}),
                    FakeChannel(2, bot=HIDDEN, everyone=HIDDEN, roles={10: perms()})]
        visibility = setup_check.channel_visibility(FakeGuild(channels=channels, roles=[member, artist]), BOARD_ID)

        self.assertEqual(member, visibility.suggested_role)

    def test_skips_the_role_analysis_on_a_huge_server(self):
        roles = [FakeRole(100 + index, position=index) for index in range(250)]
        channels = [FakeChannel(index, bot=HIDDEN, everyone=HIDDEN, roles={100: perms()}) for index in range(100)]
        visibility = setup_check.channel_visibility(FakeGuild(channels=channels, roles=roles), BOARD_ID)

        self.assertIsNone(visibility.suggested_role)
        self.assertEqual(100, len(visibility.private))


class ChannelFindingTests(unittest.TestCase):
    def test_all_readable_is_fine(self):
        visibility = setup_check.ChannelVisibility(readable=[FakeChannel(1)], blocked=[], private=[])
        [finding] = setup_check.channel_findings(visibility)

        self.assertEqual(setup_check.OK, finding.level)
        self.assertEqual("Reads 1 of 1 channels", finding.title)

    def test_blocked_channels_are_listed_with_the_role_fix(self):
        visibility = setup_check.ChannelVisibility(readable=[FakeChannel(1), FakeChannel(4)], blocked=[FakeChannel(2)],
                                                   private=[FakeChannel(3)], suggested_role=FakeRole(10),
                                                   suggested_role_opens=1)
        [finding] = setup_check.channel_findings(visibility)

        self.assertEqual(setup_check.WARN, finding.level)
        self.assertEqual("Reads 2 of 4 channels", finding.title)
        self.assertIn("<#2>", finding.detail)
        self.assertIn("<@&10>", finding.detail)
        self.assertIn("1 more are hidden", finding.detail)

    def test_a_few_private_channels_are_no_problem(self):
        visibility = setup_check.ChannelVisibility(readable=[FakeChannel(1), FakeChannel(2)], blocked=[],
                                                   private=[FakeChannel(3)])
        [finding] = setup_check.channel_findings(visibility)

        self.assertEqual(setup_check.OK, finding.level)
        self.assertIn("<#3>", finding.detail)

    def test_reading_fewer_than_half_is_a_warning_even_when_they_look_private(self):
        """A new server where only the owner sees the channels looks private, but is rarely meant to be."""
        visibility = setup_check.ChannelVisibility(readable=[FakeChannel(1)], blocked=[],
                                                   private=[FakeChannel(2), FakeChannel(3), FakeChannel(4)])
        [finding] = setup_check.channel_findings(visibility)

        self.assertEqual(setup_check.WARN, finding.level)
        self.assertEqual("Reads 1 of 4 channels", finding.title)
        self.assertIn("<#2> <#3> <#4>", finding.detail)

    def test_half_is_still_fine(self):
        visibility = setup_check.ChannelVisibility(readable=[FakeChannel(1)], blocked=[], private=[FakeChannel(2)])
        self.assertEqual(setup_check.OK, setup_check.channel_findings(visibility)[0].level)

    def test_a_server_without_channels_is_fine(self):
        visibility = setup_check.ChannelVisibility(readable=[], blocked=[], private=[])
        self.assertEqual(setup_check.OK, setup_check.channel_findings(visibility)[0].level)

    def test_a_long_list_is_cut_short(self):
        listed = setup_check.list_channels([FakeChannel(index) for index in range(15)])

        self.assertEqual(10, listed.count("<#"))
        self.assertIn("and 5 more", listed)


class BoardFindingTests(unittest.TestCase):
    def test_a_missing_board_fails(self):
        [finding] = setup_check.board_findings(None, "bot", False)

        self.assertEqual(setup_check.FAIL, finding.level)
        self.assertIn(command_refs.SET_HALL_OF_FAME_CHANNEL, finding.detail)

    def test_names_every_missing_permission(self):
        board = FakeChannel(BOARD_ID, bot=perms(embed_links=False, send_messages=False))
        [finding] = setup_check.board_findings(board, "bot", False)

        self.assertEqual(setup_check.FAIL, finding.level)
        self.assertIn("Send Messages, Embed Links", finding.detail)

    def test_warns_when_the_bot_cannot_remove_chat(self):
        board = FakeChannel(BOARD_ID, bot=perms(manage_messages=False))
        levels = [finding.level for finding in setup_check.board_findings(board, "bot", False)]

        self.assertEqual([setup_check.OK, setup_check.WARN], levels)

    def test_manage_messages_is_not_needed_when_chat_is_allowed(self):
        board = FakeChannel(BOARD_ID, bot=perms(manage_messages=False))
        levels = [finding.level for finding in setup_check.board_findings(board, "bot", True)]

        self.assertEqual([setup_check.OK], levels)


class RuleFindingTests(unittest.TestCase):
    def test_an_empty_whitelist_in_whitelist_mode_fails(self):
        [finding] = setup_check.rule_findings(server_config(custom_emoji_check_logic=True), 50)
        self.assertEqual(setup_check.FAIL, finding.level)

    def test_a_whitelist_with_emojis_is_fine(self):
        self.assertEqual([], setup_check.rule_findings(
            server_config(custom_emoji_check_logic=True, whitelisted_emojis=["😂"]), 50))

    def test_warns_about_a_threshold_above_the_member_count(self):
        [finding] = setup_check.rule_findings(server_config(reaction_threshold=12), 8)

        self.assertEqual(setup_check.WARN, finding.level)
        self.assertIn("12", finding.detail)

    def test_total_reactions_can_pass_the_member_count(self):
        config = server_config(reaction_threshold=12,
                               reaction_count_calculation_method=calculation_method_type.TOTAL_REACTIONS)
        self.assertEqual([], setup_check.rule_findings(config, 8))

    def test_an_unknown_member_count_is_not_flagged(self):
        self.assertEqual([], setup_check.rule_findings(server_config(reaction_threshold=12), None))


class ActivityFindingTests(unittest.TestCase):
    @staticmethod
    def activity(total=0, latest=None, today=0):
        return {"total": total, "latest": latest, "today": today}

    def test_no_posts_shortly_after_joining_is_only_noted(self):
        [finding] = setup_check.activity_findings(self.activity(), 5, NOW - datetime.timedelta(days=2), 100, NOW)
        self.assertEqual(setup_check.INFO, finding.level)

    def test_no_posts_after_a_week_suggests_a_lower_threshold(self):
        [finding] = setup_check.activity_findings(self.activity(), 5, NOW - datetime.timedelta(days=10), 100, NOW)

        self.assertEqual(setup_check.WARN, finding.level)
        self.assertIn(command_refs.SET_REACTION_THRESHOLD, finding.detail)

    def test_shows_the_last_post(self):
        latest = NOW - datetime.timedelta(days=1)
        [finding] = setup_check.activity_findings(self.activity(total=40, latest=latest), 5, None, 100, NOW)

        self.assertEqual(setup_check.INFO, finding.level)
        self.assertIn(f"<t:{int(latest.timestamp())}:R>", finding.detail)
        self.assertIn("40 in total", finding.detail)

    def test_reads_a_stored_time_without_a_zone_as_utc(self):
        latest = datetime.datetime(2026, 10, 17, 12, 0)
        [finding] = setup_check.activity_findings(self.activity(total=1, latest=latest), 5, None, 100, NOW)

        self.assertIn(f"<t:{int(latest.replace(tzinfo=timezone.utc).timestamp())}:R>", finding.detail)

    def test_a_quiet_month_is_a_warning(self):
        latest = NOW - datetime.timedelta(days=45)
        [finding] = setup_check.activity_findings(self.activity(total=3, latest=latest), 5, None, 100, NOW)
        self.assertEqual(setup_check.WARN, finding.level)

    def test_warns_when_the_daily_limit_is_reached(self):
        findings = setup_check.activity_findings(self.activity(total=500, latest=NOW, today=100), 5, None, 100, NOW)
        self.assertEqual(messages.CHECK_DAILY_LIMIT_TITLE, findings[0].title)


class CheckServerTests(unittest.TestCase):
    def test_a_healthy_server_has_no_problems(self):
        guild = FakeGuild(channels=[FakeChannel(1)], joined_at=NOW - datetime.timedelta(days=60))
        findings = setup_check.check_server(guild, FakeChannel(BOARD_ID), server_config(),
                                            {"total": 10, "latest": NOW, "today": 1}, 100, NOW)

        self.assertEqual([], setup_check.problems(findings))

    def test_the_join_check_needs_no_database(self):
        guild = FakeGuild(channels=[FakeChannel(1, bot=HIDDEN)])
        findings = setup_check.join_findings(guild, FakeChannel(BOARD_ID), False)

        self.assertEqual(1, len(setup_check.problems(findings)))


class BuildEmbedTests(unittest.TestCase):
    def test_says_all_is_well(self):
        embed = setup_check.build_embed([setup_check.Finding(setup_check.OK, "Board", "Posting to #board.")])

        self.assertEqual(messages.CHECK_SUMMARY_OK, embed.description)
        self.assertEqual(discord.Color.green(), embed.color)
        self.assertEqual("✅ Board", embed.fields[0].name)

    def test_counts_the_problems(self):
        embed = setup_check.build_embed([setup_check.Finding(setup_check.WARN, "a", "x"),
                                         setup_check.Finding(setup_check.FAIL, "b", "y")])

        self.assertIn("2 things", embed.description)
        self.assertEqual(discord.Color.red(), embed.color)

    def test_keeps_a_field_within_the_embed_limit(self):
        embed = setup_check.build_embed([setup_check.Finding(setup_check.WARN, "a", "x" * 2000)])
        self.assertEqual(1024, len(embed.fields[0].value))


class SetupCheckViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_welcome_view_survives_a_restart(self):
        """A persistent view is what lets the button keep working on welcome messages from earlier boots."""
        view = commands.build_welcome_view()

        self.assertTrue(view.is_persistent())
        self.assertEqual(commands.CHECK_SETUP_CUSTOM_ID, view.children[0].custom_id)
        self.assertEqual(messages.CHECK_SETUP_BUTTON, view.children[0].label)

    async def test_the_join_button_is_answered_by_the_same_registered_view(self):
        view = commands.build_check_setup_view()

        self.assertTrue(view.is_persistent())
        self.assertEqual([commands.CHECK_SETUP_CUSTOM_ID], [button.custom_id for button in view.children])

    async def test_a_press_runs_the_registered_check(self):
        pressed = []

        async def handler(interaction):
            pressed.append(interaction)

        original = commands.setup_check_handler
        commands.setup_check_handler = handler
        self.addCleanup(setattr, commands, "setup_check_handler", original)

        await commands.build_welcome_view().children[0].callback("interaction")
        self.assertEqual(["interaction"], pressed)
