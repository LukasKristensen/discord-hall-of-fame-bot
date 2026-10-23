"""Tests for what members can do with their own data: see it, delete it, and the global profile.

These commands are where the privacy policy's promises are kept, so the tests pin the promises
themselves: the global profile never shows a server, a hidden profile cannot be told apart from an
empty one, an export goes only to the member it describes, and a deletion survives the daily rebuild.
"""

import asyncio
import datetime
import json
import types
import unittest
import unittest.mock

import discord

import main
import commands
from enums import command_refs
from commands import (ConfirmDeleteView, ExportTooLarge, MyDataView, StopFeaturingView, batch_export_files,
                      build_my_data_document, build_my_data_export, split_my_data_export)
from repositories import (
    global_profile_repo,
    hall_of_fame_message_repo,
    hof_wrapped_repo,
    opt_out_repo,
    server_config_repo,
    server_user_repo,
)
from translations import messages

from tests.fakes import FakeConnection
from tests.test_main import CommandTestCase, FakeInteraction, FakeUser, GUILD_ID
from tests.test_server_config_repo import config_row

PROFILE = {"posts": 47, "reactions": 1382, "servers": 3, "biggest_post": 120, "best_month": 11, "top_of_board": 2,
           "other_servers": 2}


class GlobalProfileRepoTests(unittest.TestCase):
    def test_maps_the_totals_by_name(self):
        connection = FakeConnection(row=(47, 1382, 3, 120, 11, 2, 2))

        self.assertEqual(PROFILE, global_profile_repo.get_global_profile(connection, 77))

    def test_a_member_with_nothing_gets_zeros(self):
        connection = FakeConnection(row=(0, None, 0, None, None, 0, 0))

        self.assertEqual({field: 0 for field in global_profile_repo.PROFILE_FIELDS},
                         global_profile_repo.get_global_profile(connection, 77))

    def test_returns_totals_only(self):
        """Nothing that could name or point to a server may leave the query."""
        connection = FakeConnection(row=(1, 5, 1, 5, 1, 0, 1))
        profile = global_profile_repo.get_global_profile(connection, 77)

        self.assertEqual(set(global_profile_repo.PROFILE_FIELDS), set(profile))
        self.assertNotIn("guild", " ".join(profile))

    def test_leaves_out_servers_that_opted_out(self):
        connection = FakeConnection(row=(0, 0, 0, 0, 0, 0, 0))
        global_profile_repo.get_global_profile(connection, 77)

        query = " ".join(connection.queries[0].split())
        self.assertIn("count_in_global_profiles", query)
        self.assertEqual({"user_id": 77, "guild_id": None}, connection.parameters[0])

    def test_other_servers_leaves_out_the_server_it_is_looked_up_in(self):
        connection = FakeConnection(row=(0, 0, 0, 0, 0, 0, 0))
        global_profile_repo.get_global_profile(connection, 77, 200)

        self.assertEqual({"user_id": 77, "guild_id": 200}, connection.parameters[0])
        self.assertIn("IS DISTINCT FROM %(guild_id)s", connection.queries[0])

    def test_counts_every_post_so_the_totals_match_the_server_profiles(self):
        """No size or reaction filter, or a member's servers would not add up to their global card."""
        connection = FakeConnection(row=(0, 0, 0, 0, 0, 0, 0))
        global_profile_repo.get_global_profile(connection, 77)

        query = " ".join(connection.queries[0].split())
        self.assertNotIn("member_count", query)
        self.assertNotIn("reaction_count >=", query)

    def test_hiding_and_showing(self):
        connection = FakeConnection()
        global_profile_repo.set_hidden(connection, 77, True)
        global_profile_repo.set_hidden(connection, 77, False)

        self.assertIn("INSERT INTO hidden_global_profile", connection.queries[0])
        self.assertIn("DELETE FROM hidden_global_profile", connection.queries[1])

    def test_is_hidden_reads_the_row(self):
        self.assertTrue(global_profile_repo.is_hidden(FakeConnection(row=(1,)), 77))
        self.assertFalse(global_profile_repo.is_hidden(FakeConnection(row=None), 77))


class OptOutWriteGuardTests(unittest.TestCase):
    """
    Every repository function that writes a member's user ID, and why it cannot store data about a member
    who asked not to be featured. A new one fails this test until it is added here with its reason, and
    tests for that reason are added in tests/integration/test_member_data_deletion.py (OptedOutMemberTests)
    """

    REVIEWED = {
        # Stores author 0 for an opted-out member, in the same statement as the insert
        ("hall_of_fame_message_repo", "insert_hall_of_fame_message"),
        # Only ever replaces a member's ID with 0
        ("hall_of_fame_message_repo", "remove_author"),
        # Saves nothing for an opted-out member and strips them from the fan lists, in the same statement
        ("hof_wrapped_repo", "insert_hof_wrapped"),
        # Only ever removes a member's ID from fan lists
        ("hof_wrapped_repo", "remove_from_fan_lists"),
        # Worked out from stored posts alone, and every post credited to an opted-out member was stored
        # before they asked. Those earlier posts keep counting until the member deletes them, as /my_data
        # tells them, so their standing can still be written or move as reactions come in, but no new post
        # adds to it
        ("server_user_repo", "rebuild_user_stats_for_guild"),
        # A choice the member makes about themselves, which limits what is shown of them, so an opted-out
        # member must be able to make it too. /my_data offers it only while they have totals to hide
        ("global_profile_repo", "set_hidden"),
        # The opt-out itself, the one record the bot keeps to honour it
        ("opt_out_repo", "set_opted_out"),
    }

    def test_every_write_of_a_member_id_is_reviewed(self):
        import ast
        import pathlib
        import re

        found = set()
        for path in sorted((pathlib.Path(__file__).parent.parent / "src" / "repositories").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.FunctionDef):
                    body = ast.get_source_segment(source, node)
                    if (re.search(r"\b(INSERT\s+INTO|UPDATE)\b", body, re.IGNORECASE)
                            and re.search(r"\b(user_id|author_id)\b", body)):
                        found.add((path.stem, node.name))

        self.assertEqual(self.REVIEWED, found)

    def test_no_update_can_set_a_posts_author(self):
        """A post's author is only set when it is stored, where an opted-out member is left out."""
        with self.assertRaises(ValueError):
            hall_of_fame_message_repo.update_field_for_message(FakeConnection(), 1, 2, 3, "author_id", 77)

    def test_storing_a_post_looks_up_the_opt_out_in_the_same_statement(self):
        connection = FakeConnection()
        hall_of_fame_message_repo.insert_hall_of_fame_message(connection, 1, 2, 3, 4, 5, 77, datetime.datetime(2026, 1, 1))

        self.assertIn("opted_out_member", connection.queries[0])

    def test_saving_a_wrapped_looks_up_the_opt_out_in_the_same_statement(self):
        connection = FakeConnection()
        hof_wrapped_repo.insert_hof_wrapped(connection, 1, 77, 2025, 0, 0, "{}", "{}", None, None, 0, "{}", "{}", "{}")

        self.assertEqual(3, connection.queries[0].count("opted_out_member"))


class MemberDataRepoTests(unittest.TestCase):
    def test_each_deletion_step_can_leave_the_commit_to_the_caller(self):
        """Deleting a member's data runs them as one transaction, so none of them may commit on its own."""
        steps = (lambda c: opt_out_repo.set_opted_out(c, 77, True, commit=False),
                 lambda c: hall_of_fame_message_repo.remove_author(c, 77, commit=False),
                 lambda c: server_user_repo.delete_server_users_for_user(c, 77, commit=False),
                 lambda c: hof_wrapped_repo.delete_hof_wrapped_for_user(c, 77, commit=False),
                 lambda c: global_profile_repo.delete_for_user(c, 77, commit=False))
        for step in steps:
            connection = FakeConnection()
            step(connection)
            self.assertEqual(0, connection.commits)

    def test_detached_posts_bring_no_member_into_wrapped(self):
        """Wrapped makes a member of every author it finds, and author 0 is nobody."""
        connection = FakeConnection(rows=[])
        hall_of_fame_message_repo.find_members_for_guild(connection, 200)

        self.assertIn("author_id <> %s", connection.queries[0])
        self.assertEqual((200, hall_of_fame_message_repo.NO_AUTHOR_ID), connection.parameters[0])

    def test_removing_an_author_uses_the_id_the_rebuild_skips(self):
        """The daily rebuild leaves author 0 out, so the member drops off every leaderboard for good."""
        connection = FakeConnection()
        hall_of_fame_message_repo.remove_author(connection, 77)

        self.assertIn("UPDATE hall_of_fame_message SET author_id", connection.queries[0])
        self.assertEqual((hall_of_fame_message_repo.NO_AUTHOR_ID, 77), connection.parameters[0])
        self.assertEqual(0, hall_of_fame_message_repo.NO_AUTHOR_ID)

    def test_reads_a_members_posts_by_author(self):
        connection = FakeConnection(rows=[(200, 300, 400, 500, 9, "2026-01-01")])
        posts = hall_of_fame_message_repo.get_messages_by_author(connection, 77)

        self.assertEqual([{"guild_id": 200, "channel_id": 300, "message_id": 400, "hall_of_fame_message_id": 500,
                           "reaction_count": 9, "created_at": "2026-01-01"}], posts)
        self.assertEqual((77,), connection.parameters[0])

    def test_deleting_wrapped_also_clears_the_member_from_other_fan_lists(self):
        connection = FakeConnection()
        hof_wrapped_repo.delete_hof_wrapped_for_user(connection, 77)

        self.assertIn("DELETE FROM hof_wrapped WHERE user_id", connection.queries[0])
        updated = [" ".join(query.split()) for query in connection.queries[1:]]
        self.assertTrue(any("SET fan_of_users" in query for query in updated))
        self.assertTrue(any("SET users_fans" in query for query in updated))
        # json.dumps writes the integer keys as strings, which is the form removed
        self.assertEqual(("77", '%"77"%'), connection.parameters[1])

    def test_reads_and_deletes_a_members_standing_in_every_guild(self):
        connection = FakeConnection(rows=[], description=["user_id", "guild_id"])
        server_user_repo.get_server_users_for_user(connection, 77)
        server_user_repo.delete_server_users_for_user(connection, 77)

        self.assertIn("WHERE user_id = %s", connection.queries[0])
        self.assertIn("DELETE FROM server_user WHERE user_id", connection.queries[1])

    def test_member_lookups_are_indexed(self):
        connection = FakeConnection()
        hof_wrapped_repo.create_hof_wrapped_table(connection)

        self.assertTrue(any("ON hof_wrapped (user_id)" in query for query in connection.queries))


class CountInGlobalProfilesColumnTests(unittest.TestCase):
    def test_reads_the_setting(self):
        row = config_row() + (False,)
        server = server_config_repo.get_server_classes(FakeConnection(rows=[row]))[200]

        self.assertFalse(server.count_in_global_profiles)

    def test_a_row_from_before_the_column_counts(self):
        server = server_config_repo.get_server_classes(FakeConnection(rows=[config_row()]))[200]

        self.assertTrue(server.count_in_global_profiles)

    def test_the_column_is_added_to_existing_tables_switched_on(self):
        connection = FakeConnection()
        server_config_repo.create_server_config_table(connection)

        self.assertTrue(any("ADD COLUMN IF NOT EXISTS count_in_global_profiles BOOLEAN DEFAULT TRUE" in query
                            for query in connection.queries))

    def test_the_setting_can_be_written(self):
        self.assertIn("count_in_global_profiles", server_config_repo.ALLOWED_COLUMNS)


class GlobalProfileSectionTests(unittest.TestCase):
    def test_shows_the_totals(self):
        value = commands.global_profile_column_value(PROFILE)

        self.assertIn("**47** posts", value)
        self.assertIn("**1,382** reactions", value)
        self.assertIn("**3** servers · #1 in 2", value)

    def test_leaves_out_a_title_the_member_does_not_have(self):
        value = commands.global_profile_column_value(dict(PROFILE, top_of_board=0))

        self.assertNotIn("#1", value)

    def test_only_shown_when_it_says_more_than_the_server_profile(self):
        """When every post is from this server, the section would only repeat the card."""
        self.assertFalse(commands.global_profile_adds_something(dict(PROFILE, servers=1, other_servers=0)))
        self.assertTrue(commands.global_profile_adds_something(PROFILE))

    def test_shown_when_the_counts_match_but_the_posts_are_from_elsewhere(self):
        """Five posts here and five in a server that counts: equal numbers, but not the same posts."""
        self.assertTrue(commands.global_profile_adds_something(dict(PROFILE, posts=5, servers=1, other_servers=1)))

    def test_not_shown_without_totals(self):
        self.assertFalse(commands.global_profile_adds_something(None))
        self.assertFalse(commands.global_profile_adds_something(dict(PROFILE, posts=0)))


class MyDataExportTests(unittest.TestCase):
    def test_writes_ids_as_text_so_none_lose_digits(self):
        posts = [{"guild_id": 123456789012345678, "message_id": 987654321098765432, "reaction_count": 9,
                  "created_at": "2026-01-01"}]
        export = json.loads(build_my_data_export(77, posts, [], [], False))

        self.assertEqual("123456789012345678", export["featured_posts"][0]["guild_id"])
        self.assertEqual(9, export["featured_posts"][0]["reaction_count"])
        self.assertEqual("77", export["user_id"])

    def test_includes_every_kind_of_data(self):
        export = json.loads(build_my_data_export(77, [], [{"guild_id": 1}], [{"guild_id": 1, "year": 2025}], True))

        self.assertEqual({"user_id", "about", "global_profile_hidden", "not_counted", "featured_posts",
                          "server_statistics", "wrapped"}, set(export))
        self.assertTrue(export["global_profile_hidden"])
        self.assertIn(messages.PRIVACY_POLICY_URL, export["about"])


class ConfirmDeleteViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_member_who_asked_can_confirm(self):
        view = ConfirmDeleteView(77, on_confirm=None)
        stranger = FakeInteraction()
        stranger.user = FakeUser(user_id=99)

        self.assertFalse(await view.interaction_check(stranger))
        self.assertEqual([messages.MY_DATA_NOT_YOURS], stranger.response.messages)

    async def test_cancelling_deletes_nothing(self):
        confirmed = []

        async def on_confirm(interaction):
            confirmed.append(interaction)

        view = ConfirmDeleteView(77, on_confirm)
        interaction = FakeInteraction()
        await view.cancel(interaction)

        self.assertEqual([], confirmed)
        self.assertEqual([(messages.DELETE_MY_DATA_CANCELLED, None)], interaction.response.edits)


class HighlightsTests(unittest.TestCase):
    STATS = {"this_month_hall_of_fame_messages": 5, "monthly_message_rank": 3,
             "total_hall_of_fame_messages": 40, "total_message_rank": 1}

    def at_rank(self, counts):
        return lambda _stat, rank_field, rank: counts.get((rank_field, rank))

    def test_says_how_far_behind_the_next_place_this_month(self):
        line = commands.rank_gap_line(self.STATS, self.at_rank({("monthly_message_rank", 2): 7}))

        self.assertEqual("🎯 2 posts behind #2 this month", line)

    def test_says_level_when_tied_with_the_next_place(self):
        line = commands.rank_gap_line(self.STATS, self.at_rank({("monthly_message_rank", 2): 5}))

        self.assertEqual("🎯 Level with #2 this month", line)

    def test_says_the_lead_when_first(self):
        stats = dict(self.STATS, monthly_message_rank=1)
        line = commands.rank_gap_line(stats, self.at_rank({("monthly_message_rank", 2): 4}))

        self.assertEqual("🎯 Leading this month by 1 post", line)

    def test_falls_back_to_all_time_without_a_rank_this_month(self):
        stats = dict(self.STATS, monthly_message_rank=None)
        line = commands.rank_gap_line(stats, self.at_rank({("total_message_rank", 2): 30}))

        self.assertEqual("🎯 Leading all time by 10 posts", line)

    def test_says_nothing_without_anyone_to_compare_with(self):
        stats = dict(self.STATS, monthly_message_rank=1)

        self.assertIsNone(commands.rank_gap_line(stats, self.at_rank({})))

    def test_links_the_best_post_and_times_the_last_feature(self):
        highlights = {"best_post": {"channel_id": 300, "message_id": 400, "reaction_count": 4},
                      "last_featured": datetime.datetime(2026, 10, 16, 12, 0)}
        value = commands.highlights_value(200, highlights, "🎯 line")

        self.assertIn("4 reactions · [Jump to it](https://discord.com/channels/200/300/400)", value)
        self.assertIn("<t:1792152000:R>", value)
        self.assertTrue(value.endswith("🎯 line"))

    def test_leaves_out_lines_with_nothing_to_say(self):
        self.assertEqual("", commands.highlights_value(200, {"best_post": None, "last_featured": None}, None))


NOW = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=datetime.timezone.utc)
NO_FACTS = {"posts_by_month": [], "first_featured": None, "biggest_post": 0, "champion_months": 0}
EMPTY_PROFILE = {field: 0 for field in global_profile_repo.PROFILE_FIELDS}


def months(*pairs):
    """(year, month, posts) triples as the (month start, posts) pairs the badge facts hold"""
    return [(datetime.datetime(year, month, 1), posts) for year, month, posts in pairs]


class EarnedBadgesTests(unittest.TestCase):
    def badges(self, global_profile=EMPTY_PROFILE, **facts):
        return commands.earned_badges(dict(NO_FACTS, **facts), global_profile, now=NOW)

    def test_nothing_earned_means_no_badges(self):
        self.assertEqual([], self.badges())
        self.assertEqual([], self.badges(global_profile=None))

    def test_monthly_champion(self):
        self.assertEqual([messages.BADGE_MONTHLY_CHAMPION], self.badges(champion_months=2))

    def test_post_count_shows_the_highest_tier_only(self):
        for posts, expected in ((9, None), (10, 10), (49, 10), (50, 50), (100, 100), (499, 100), (500, 500)):
            with self.subTest(posts=posts):
                # Spread over two months that are not in a row, so no other badge is earned
                earned = self.badges(posts_by_month=months((2026, 1, posts - posts // 2), (2026, 5, posts // 2)))
                posts_badges = [badge for badge in earned if badge.startswith("📈")]
                self.assertEqual([messages.BADGE_POSTS.format(posts=expected)] if expected else [], posts_badges)

    def test_streak_counts_calendar_months_in_a_row(self):
        streak = months((2025, 11, 1), (2025, 12, 1), (2026, 1, 1), (2026, 3, 1))
        self.assertIn(messages.BADGE_STREAK.format(months=3), self.badges(posts_by_month=streak))

    def test_no_streak_badge_for_two_months_in_a_row(self):
        two = months((2026, 1, 1), (2026, 2, 1), (2026, 4, 1), (2026, 5, 1))
        self.assertEqual([], self.badges(posts_by_month=two))

    def test_shows_the_longest_streak(self):
        streak = months((2025, 1, 1), (2025, 2, 1), (2025, 3, 1), (2025, 4, 1), (2025, 9, 1), (2025, 10, 1))
        self.assertIn(messages.BADGE_STREAK.format(months=4), self.badges(posts_by_month=streak))

    def test_featured_for_a_year(self):
        a_year_ago = datetime.datetime(2025, 10, 18, 12, 0)
        just_under = datetime.datetime(2025, 10, 19, 12, 0)

        self.assertEqual([messages.BADGE_VETERAN], self.badges(first_featured=a_year_ago))
        self.assertEqual([], self.badges(first_featured=just_under))

    def test_hundred_reaction_post_here(self):
        self.assertEqual([messages.BADGE_BIG_POST], self.badges(global_profile=None, biggest_post=100))
        self.assertEqual([], self.badges(global_profile=None, biggest_post=99))

    def test_hundred_reaction_post_elsewhere_only_counts_when_totals_are_shown(self):
        elsewhere = dict(EMPTY_PROFILE, biggest_post=150, posts=1, servers=1)

        self.assertEqual([messages.BADGE_BIG_POST], self.badges(global_profile=elsewhere))
        self.assertEqual([], self.badges(global_profile=None))

    def test_ten_post_month_here(self):
        self.assertIn(messages.BADGE_BIG_MONTH, self.badges(global_profile=None, posts_by_month=months((2026, 2, 10))))
        self.assertNotIn(messages.BADGE_BIG_MONTH,
                         self.badges(global_profile=None, posts_by_month=months((2026, 2, 9), (2026, 4, 9))))

    def test_ten_post_month_elsewhere_only_counts_when_totals_are_shown(self):
        elsewhere = dict(EMPTY_PROFILE, best_month=12, posts=12, servers=1)

        self.assertEqual([messages.BADGE_BIG_MONTH], self.badges(global_profile=elsewhere))
        self.assertEqual([], self.badges(global_profile=None))

    def test_servers_badge_from_five_servers(self):
        """The every-server column already shows the count, so the badge is kept for a real milestone."""
        self.assertEqual([messages.BADGE_SERVERS.format(servers=5)],
                         self.badges(global_profile=dict(EMPTY_PROFILE, servers=5)))
        self.assertEqual([], self.badges(global_profile=dict(EMPTY_PROFILE, servers=4)))

    def test_hidden_totals_leave_every_other_server_out(self):
        """global_profile is None when the member hid their totals."""
        local = dict(posts_by_month=months((2026, 2, 3)), biggest_post=40)
        self.assertEqual([], self.badges(global_profile=None, **local))

    def test_no_badge_names_or_points_to_a_server(self):
        everything = dict(PROFILE, servers=12)
        earned = self.badges(global_profile=everything, champion_months=1, biggest_post=500,
                             first_featured=datetime.datetime(2020, 1, 1),
                             posts_by_month=months((2026, 1, 200), (2026, 2, 200), (2026, 3, 200)))

        self.assertEqual(7, len(earned))
        for badge in earned:
            self.assertNotIn("discord.com", badge)
            self.assertNotIn("<#", badge)
            self.assertNotIn(str(GUILD_ID), badge)


class UserProfileTotalsTests(CommandTestCase):
    """/user_profile ends with the member's totals across servers, unless they hid them."""

    def setUp(self):
        super().setUp()
        self.hidden = set()
        self.profile_reads = []
        self.given = []
        self.patch(main.server_user_repo, "get_server_user",
                   lambda *_args: {"total_hall_of_fame_messages": 40})
        self.patch(global_profile_repo, "is_hidden", lambda _connection, user_id: user_id in self.hidden)

        def read_profile(_connection, user_id, guild_id=None):
            self.profile_reads.append(user_id)
            return dict(PROFILE)

        self.patch(global_profile_repo, "get_global_profile", read_profile)

        async def record(_interaction, _user, _stats, _connection, _month, _all_time, global_profile=None):
            self.given.append(global_profile)

        self.patch(main.commands, "user_server_profile", record)

    async def test_hands_the_totals_to_the_profile(self):
        await main.user_server_profile.callback(FakeInteraction(), FakeUser(user_id=88))

        self.assertEqual([PROFILE], self.given)

    async def test_queries_run_under_a_statement_timeout(self):
        """The badges read every post in the server, so a slow lookup is cut off instead of stalling the bot."""
        await main.user_server_profile.callback(FakeInteraction(), FakeUser(user_id=88))

        timeouts = [query for query in self.pool.connection.queries if query.startswith("SET statement_timeout")]
        self.assertEqual(2, len(timeouts))

    async def test_answers_before_reading_the_database(self):
        """The queries can outlast the three seconds Discord waits for an answer."""
        interaction = FakeInteraction()
        deferred_first = []
        self.patch(main.server_user_repo, "get_server_user",
                   lambda *_args: deferred_first.append(interaction.response.deferred) or None)
        await main.user_server_profile.callback(interaction, FakeUser(user_id=88))

        self.assertEqual([True], deferred_first)
        self.assertFalse(interaction.response.deferred_ephemeral)

    async def test_reads_the_totals_for_the_server_it_is_used_in(self):
        """So the totals can tell posts from other servers apart from this one's."""
        servers = []
        self.patch(global_profile_repo, "get_global_profile",
                   lambda _connection, _user_id, guild_id=None: servers.append(guild_id) or dict(PROFILE))
        await main.user_server_profile.callback(FakeInteraction(), FakeUser(user_id=88))

        self.assertEqual([GUILD_ID], servers)

    async def test_leaves_hidden_totals_out_without_reading_them(self):
        self.hidden.add(88)
        await main.user_server_profile.callback(FakeInteraction(), FakeUser(user_id=88))

        self.assertEqual([None], self.given)
        self.assertEqual([], self.profile_reads)

    async def test_leaves_hidden_totals_out_of_the_members_own_profile_too(self):
        """The profile is posted in the channel, so showing them to the member shows them to everyone."""
        self.hidden.add(77)
        await main.user_server_profile.callback(FakeInteraction(), None)

        self.assertEqual([None], self.given)

    async def test_a_member_featured_only_elsewhere_still_gets_a_card(self):
        self.patch(main.server_user_repo, "get_server_user", lambda *_args: None)
        interaction = FakeInteraction()
        await main.user_server_profile.callback(interaction, FakeUser(user_id=88))

        self.assertEqual([PROFILE], self.given)
        self.assertEqual([], interaction.followup.messages)

    async def test_no_data_anywhere_still_says_so(self):
        self.patch(main.server_user_repo, "get_server_user", lambda *_args: None)
        self.patch(global_profile_repo, "get_global_profile",
                   lambda *_args: {field: 0 for field in global_profile_repo.PROFILE_FIELDS})
        interaction = FakeInteraction()
        await main.user_server_profile.callback(interaction, FakeUser(user_id=88))

        self.assertEqual([messages.PROFILE_NO_DATA], interaction.followup.messages)
        self.assertEqual([], self.given)

    async def test_hidden_totals_do_not_make_a_card_for_a_member_with_no_data_here(self):
        """Otherwise an empty card would reveal that the member was featured somewhere else."""
        self.patch(main.server_user_repo, "get_server_user", lambda *_args: None)
        self.hidden.add(88)
        interaction = FakeInteraction()
        await main.user_server_profile.callback(interaction, FakeUser(user_id=88))

        self.assertEqual([messages.PROFILE_NO_DATA], interaction.followup.messages)

    async def test_has_no_scope_option(self):
        names = [parameter.name for parameter in main.user_server_profile.parameters]

        self.assertEqual(["specific_user"], names)


class UserProfileEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, global_profile, total=40):
        interaction = FakeInteraction()
        connection = FakeConnection(row=None)
        user = FakeUser(user_id=88, name="maya")
        user.display_avatar = types.SimpleNamespace(url="https://example.com/a.png")
        await commands.user_server_profile(interaction, user, {"total_hall_of_fame_messages": total},
                                           connection, ":m:", ":a:", global_profile)
        return interaction.followup.messages[0]

    async def test_shows_three_columns_side_by_side(self):
        embed = await self.build(PROFILE)

        self.assertEqual(["🏆 This month", "🌟 All time", messages.GLOBAL_PROFILE_HEADING],
                         [field.name for field in embed.fields][:3])
        self.assertTrue(all(field.inline for field in embed.fields[:3]))

    async def test_badges_sit_under_the_columns_in_one_field(self):
        embed = await self.build(dict(PROFILE, servers=5))
        badges = embed.fields[3]

        self.assertEqual(messages.BADGES_HEADING, badges.name)
        self.assertFalse(badges.inline)
        self.assertEqual(" · ".join([messages.BADGE_BIG_POST, messages.BADGE_BIG_MONTH,
                                     messages.BADGE_SERVERS.format(servers=5)]), badges.value)

    async def test_hidden_totals_leave_out_the_badges_from_other_servers(self):
        """Nothing featured here, so every badge PROFILE would earn comes from another server."""
        embed = await self.build(None)

        self.assertNotIn(messages.BADGES_HEADING, [field.name for field in embed.fields])

    async def test_asks_for_the_install_once(self):
        """The footer carries the ask, so the column does not repeat it."""
        embed = await self.build(PROFILE)

        self.assertEqual(messages.GLOBAL_STATS_FOOTER, embed.footer.text)
        self.assertNotIn("/invite", embed.fields[-1].value)

    async def test_leaves_the_column_out_when_hidden(self):
        embed = await self.build(None)

        self.assertEqual(["🏆 This month", "🌟 All time"], [field.name for field in embed.fields])
        self.assertEqual(messages.STATS_FOOTER, embed.footer.text)

    async def test_a_member_without_a_rank_this_month_gets_a_dash(self):
        interaction = FakeInteraction()
        user = FakeUser(user_id=88)
        user.display_avatar = types.SimpleNamespace(url="https://example.com/a.png")
        await commands.user_server_profile(interaction, user, {"total_hall_of_fame_messages": 7,
                                                               "total_message_rank": 2},
                                           FakeConnection(row=None), ":m:", ":a:", None)
        fields = {field.name: field.value for field in interaction.followup.messages[0].fields}

        self.assertIn("**0** posts · -", fields["🏆 This month"])
        self.assertIn("**7** posts · #2", fields["🌟 All time"])


class CountInGlobalProfilesCommandTests(CommandTestCase):
    async def test_stores_the_setting(self):
        interaction = FakeInteraction()
        await main.count_in_global_profiles.callback(interaction, False)

        self.assertEqual([(GUILD_ID, "count_in_global_profiles", False)], self.writes)
        self.assertFalse(self.server.count_in_global_profiles)

    async def test_needs_manage_server(self):
        interaction = FakeInteraction(manage_guild=False)
        await main.count_in_global_profiles.callback(interaction, False)

        self.assertEqual([], self.writes)


# When the member made a choice, shown on /my_data as a Discord timestamp
CHOSEN = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.timezone.utc)
CHOSEN_SHOWN = f"<t:{int(CHOSEN.timestamp())}:D>"


SAMPLE_POST = {"guild_id": 1234567890123456789, "channel_id": 1234567890123456789, "message_id": 0,
               "hall_of_fame_message_id": 1234567890123456789, "reaction_count": 12, "created_at": "2026-01-01 12:00:00"}


class SplitExportTests(unittest.TestCase):
    def document(self, posts=200, standings=20, wrapped=5):
        return build_my_data_document(
            77, [dict(SAMPLE_POST, message_id=number) for number in range(posts)],
            [{"guild_id": number, "total_hall_of_fame_messages": 9} for number in range(standings)],
            [{"guild_id": number, "year": 2025, "fan_of_users": "{}"} for number in range(wrapped)], True, False)

    def test_one_file_when_it_fits(self):
        document = self.document()
        files = split_my_data_export(document, max_bytes=10_000_000)

        self.assertEqual([build_my_data_export(77, document["featured_posts"], document["server_statistics"],
                                               document["wrapped"], True, False)], files)

    def test_every_part_fits_and_is_complete_json(self):
        files = split_my_data_export(self.document(), max_bytes=8_000)

        self.assertGreater(len(files), 1)
        for number, data in enumerate(files, start=1):
            with self.subTest(part=number):
                self.assertLessEqual(len(data), 8_000)
                part = json.loads(data)
                self.assertEqual(f"{number} of {len(files)}", part["part"])
                self.assertEqual("77", part["user_id"])
                self.assertTrue(part["global_profile_hidden"])

    def test_the_parts_hold_every_row_once_in_order(self):
        document = self.document()
        parts = [json.loads(data) for data in split_my_data_export(document, max_bytes=8_000)]

        for section in ("featured_posts", "server_statistics", "wrapped"):
            with self.subTest(section=section):
                self.assertEqual(document[section], [row for part in parts for row in part[section]])

    def test_a_row_bigger_than_a_file_cannot_be_sent(self):
        """A Wrapped row from a huge server can carry a fan list of hundreds of thousands of IDs."""
        document = self.document(posts=1, standings=0, wrapped=0)
        document["wrapped"] = [{"guild_id": "1", "fan_of_users": "x" * 10_000}]

        with self.assertRaises(ExportTooLarge):
            split_my_data_export(document, max_bytes=5_000)

    def test_an_empty_export_is_one_file(self):
        self.assertEqual(1, len(split_my_data_export(self.document(0, 0, 0), max_bytes=1_000)))


class BatchExportFilesTests(unittest.TestCase):
    def test_keeps_each_message_within_the_size_budget(self):
        self.assertEqual([[0, 1], [2], [3]], batch_export_files([b"a" * 4, b"b" * 5, b"c" * 8, b"d" * 3], max_bytes=10))

    def test_keeps_each_message_within_the_attachment_count(self):
        self.assertEqual([[0, 1], [2, 3], [4]], batch_export_files([b"x"] * 5, max_bytes=100, per_message=2))

    def test_one_file_is_one_message(self):
        self.assertEqual([[0]], batch_export_files([b"x"]))


class MyDataPanelTestCase(CommandTestCase):
    """/my_data with what is stored faked, and its buttons pressed the way Discord would."""

    def setUp(self):
        super().setUp()
        self.patch(main, "daily_command_cooldowns", {})
        self.posts = [{"guild_id": 200, "message_id": 400, "reaction_count": 9, "created_at": "2026-01-01"}]
        self.standings = [{"guild_id": 200}]
        self.wrapped = []
        self.hidden = set()
        self.opted_out = set()
        self.calls = []
        self.patch(hall_of_fame_message_repo, "count_messages_by_author", lambda *_args: len(self.posts))
        self.patch(server_user_repo, "count_server_users_for_user", lambda *_args: len(self.standings))
        self.patch(hof_wrapped_repo, "count_hof_wrapped_for_user", lambda *_args: len(self.wrapped))
        self.patch(hall_of_fame_message_repo, "get_messages_by_author", lambda *_args: self.posts)
        self.patch(server_user_repo, "get_server_users_for_user", lambda *_args: self.standings)
        self.patch(hof_wrapped_repo, "get_hof_wrapped_for_user", lambda *_args: self.wrapped)
        self.patch(global_profile_repo, "is_hidden", lambda _c, user_id: user_id in self.hidden)
        self.patch(opt_out_repo, "is_opted_out", lambda _c, user_id: user_id in self.opted_out)
        self.patch(global_profile_repo, "hidden_since", lambda _c, user_id: CHOSEN if user_id in self.hidden else None)
        self.patch(opt_out_repo, "opted_out_since",
                   lambda _c, user_id: CHOSEN if user_id in self.opted_out else None)

        def set_hidden(_c, user_id, hidden, commit=True):
            (self.hidden.add if hidden else self.hidden.discard)(user_id)

        def set_opted_out(_c, user_id, opted_out, commit=True):
            self.calls.append(("opt_out", opted_out))
            (self.opted_out.add if opted_out else self.opted_out.discard)(user_id)

        self.patch(global_profile_repo, "set_hidden", set_hidden)
        self.patch(opt_out_repo, "set_opted_out", set_opted_out)
        self.patch(hall_of_fame_message_repo, "remove_author", lambda *_args, **_kw: self.calls.append("posts") or 3)
        self.patch(server_user_repo, "delete_server_users_for_user", lambda *_args, **_kw: self.calls.append("stats"))
        self.patch(hof_wrapped_repo, "delete_hof_wrapped_for_user", lambda *_args, **_kw: self.calls.append("wrapped"))
        self.patch(global_profile_repo, "delete_for_user", lambda *_args, **_kw: self.calls.append("privacy"))

    async def open_panel(self):
        interaction = FakeInteraction()
        await main.my_data.callback(interaction)
        return interaction, interaction.followup.views[0]

    @staticmethod
    async def press(button):
        interaction = FakeInteraction()
        await button.callback(interaction)
        return interaction

    async def ask_to_delete(self):
        """Open /my_data and press Delete, which swaps the summary for the confirmation"""
        _interaction, panel = await self.open_panel()
        pressed = await self.press(panel.delete_button)
        return pressed.original_edits[0][1]


class MyDataPanelTests(MyDataPanelTestCase):
    async def test_answers_privately_with_a_summary_and_buttons(self):
        interaction, view = await self.open_panel()

        self.assertTrue(interaction.response.deferred_ephemeral)
        self.assertEqual([True], interaction.followup.ephemeral)
        self.assertIn("1 featured post,", interaction.followup.messages[0])
        self.assertIsInstance(view, MyDataView)
        self.assertEqual([None], interaction.followup.files)

    async def test_large_counts_are_written_with_thousands_separators(self):
        self.patch(hall_of_fame_message_repo, "count_messages_by_author", lambda *_args: 2_450_000)
        interaction, _view = await self.open_panel()

        self.assertIn("2,450,000 featured posts", interaction.followup.messages[0])

    async def test_the_summary_does_not_read_the_rows_themselves(self):
        """The full export is the expensive part, so only the Download button reads it."""
        def must_not_run(*_args):
            raise AssertionError("the summary read every post")

        self.patch(hall_of_fame_message_repo, "get_messages_by_author", must_not_run)
        await self.open_panel()

    async def test_says_so_when_nothing_is_stored(self):
        self.posts, self.standings = [], []
        interaction, view = await self.open_panel()

        self.assertIn(messages.MY_DATA_NOTHING_AT_ALL, interaction.followup.messages[0])
        # Still there, so the panel looks the same for everyone, but greyed out
        self.assertIn(view.download_button, view.children)
        self.assertTrue(view.download_button.disabled)
        self.assertIn(view.delete_button, view.children)
        self.assertTrue(view.delete_button.disabled)

    async def test_a_stored_choice_can_be_downloaded_and_deleted(self):
        """A choice is data about the member too, so both buttons work for it."""
        self.posts, self.standings = [], []
        self.hidden.add(77)
        interaction, view = await self.open_panel()

        self.assertFalse(view.download_button.disabled)
        self.assertFalse(view.delete_button.disabled)
        self.assertIn(messages.MY_DATA_TOTALS_HIDDEN.format(since=CHOSEN_SHOWN), interaction.followup.messages[0])
        # A choice is stored, so it must not say there is nothing to delete
        self.assertIn(messages.MY_DATA_NOTHING_STORED, interaction.followup.messages[0])
        self.assertNotIn(messages.MY_DATA_NOTHING_AT_ALL, interaction.followup.messages[0])

    async def test_without_credited_posts_there_are_no_totals_to_show_yet(self):
        """Right after a deletion the member's posts are on boards but credited to nobody."""
        self.posts, self.standings = [], []
        interaction, _view = await self.open_panel()

        self.assertIn(messages.MY_DATA_TOTALS_SHOWN_ONCE_FEATURED, interaction.followup.messages[0])
        self.assertNotIn(messages.MY_DATA_TOTALS_SHOWN, interaction.followup.messages[0].split("\n"))

    async def test_opening_it_again_is_not_limited(self):
        await self.open_panel()
        again, _view = await self.open_panel()

        self.assertIn("1 featured post,", again.followup.messages[0])

    async def test_queries_run_under_a_statement_timeout(self):
        await self.open_panel()

        self.assertTrue(any("statement_timeout" in query for query in self.pool.connection.queries))

    async def test_only_the_member_who_ran_it_can_press_the_buttons(self):
        _interaction, view = await self.open_panel()
        stranger = FakeInteraction()
        stranger.user = FakeUser(user_id=99)

        self.assertFalse(await view.interaction_check(stranger))
        self.assertEqual([messages.MY_DATA_NOT_YOURS], stranger.response.messages)

    async def test_offers_stop_featuring_and_delete_to_a_featured_member(self):
        _interaction, view = await self.open_panel()

        self.assertIn(view.featuring_button, view.children)
        self.assertEqual(messages.STOP_FEATURING_BUTTON, view.featuring_button.label)
        self.assertFalse(view.download_button.disabled)
        self.assertFalse(view.delete_button.disabled)


class DownloadMyDataTests(MyDataPanelTestCase):
    async def test_sends_the_file_privately(self):
        _interaction, view = await self.open_panel()
        pressed = await self.press(view.download_button)

        self.assertTrue(pressed.response.deferred_ephemeral)
        self.assertEqual([messages.MY_DATA_EXPORT], pressed.followup.messages)
        self.assertEqual([True], pressed.followup.ephemeral)
        [file] = pressed.followup.attachments[0]
        self.assertIsInstance(file, discord.File)
        self.assertEqual("hall-of-fame-my-data.json", file.filename)

    @staticmethod
    def refusing_over(limit, status=413):
        """
        A button press whose followups Discord refuses when a message's files add up to more than limit
        :return: The interaction, and the messages it accepted as (content, [(filename, bytes)])
        """
        pressed = FakeInteraction()
        accepted = []

        async def send(content=None, ephemeral=False, file=None, files=None, **_kwargs):
            files = list(files or []) + ([file] if file is not None else [])
            contents = [(attached.filename, attached.fp.getvalue()) for attached in files]
            if sum(len(data) for _name, data in contents) > limit:
                response = types.SimpleNamespace(status=status, reason="Payload Too Large")
                raise discord.HTTPException(response, {"code": 40005, "message": "Request entity too large"})
            accepted.append((content, contents))

        pressed.followup.send = send
        return pressed, accepted

    async def test_sends_one_file_whenever_discord_accepts_it(self):
        """Discord's own limit decides, so a file over the split budget still goes as one if it fits."""
        self.posts = [dict(SAMPLE_POST, message_id=number) for number in range(400)]
        self.patch(commands, "EXPORT_MESSAGE_BYTES", 20_000)
        _interaction, view = await self.open_panel()
        pressed, accepted = self.refusing_over(10_000_000)
        await view.download_button.callback(pressed)

        [(content, files)] = accepted
        self.assertEqual(messages.MY_DATA_EXPORT, content)
        self.assertEqual(["hall-of-fame-my-data.json"], [name for name, _data in files])
        self.assertGreater(len(files[0][1]), 20_000)

    async def test_an_export_discord_refuses_is_sent_in_parts(self):
        self.posts = [dict(SAMPLE_POST, message_id=number) for number in range(400)]
        _interaction, view = await self.open_panel()
        pressed, accepted = self.refusing_over(40_000)
        await view.download_button.callback(pressed)

        files = [file for _content, message in accepted for file in message]
        self.assertGreater(len(files), 1)
        self.assertEqual(messages.MY_DATA_EXPORT_PARTS.format(parts=len(files)), accepted[0][0])
        message_ids = [post["message_id"] for _name, data in files for post in json.loads(data)["featured_posts"]]
        self.assertEqual([str(number) for number in range(400)], message_ids)
        self.assertEqual(f"hall-of-fame-my-data-part-1-of-{len(files)}.json", files[0][0])
        self.assertTrue(main.on_daily_cooldown(77, "my_data"))
        self.assertTrue(any("after Discord refused one" in entry for entry in self.logged))

    async def test_parts_discord_also_refuses_are_reported(self):
        self.posts = [dict(SAMPLE_POST, message_id=number) for number in range(400)]
        _interaction, view = await self.open_panel()
        # Below even the parts, which are half of the refused file
        pressed, accepted = self.refusing_over(1_000)
        sent = []
        refuse = pressed.followup.send

        async def send(content=None, ephemeral=False, file=None, files=None, **kwargs):
            if not files and file is None:
                sent.append(content)
                return
            await refuse(content, ephemeral, file, files, **kwargs)

        pressed.followup.send = send
        await view.download_button.callback(pressed)

        self.assertIn(sent[-1], (messages.MY_DATA_EXPORT_SEND_FAILED, messages.MY_DATA_EXPORT_TOO_LARGE))
        self.assertFalse(main.on_daily_cooldown(77, "my_data"))

    async def test_a_row_too_big_for_any_part_goes_to_the_support_server(self):
        self.wrapped = [{"guild_id": 1, "year": 2025, "fan_of_users": "x" * 50_000}]
        _interaction, view = await self.open_panel()
        pressed, accepted = self.refusing_over(40_000)
        sent = []
        refuse = pressed.followup.send

        async def send(content=None, ephemeral=False, file=None, files=None, **kwargs):
            if not files and file is None:
                sent.append(content)
                return
            await refuse(content, ephemeral, file, files, **kwargs)

        pressed.followup.send = send
        await view.download_button.callback(pressed)

        self.assertEqual([messages.MY_DATA_EXPORT_TOO_LARGE], sent)
        self.assertTrue(any("too large to send through Discord" in entry for entry in self.logged))
        self.assertFalse(main.on_daily_cooldown(77, "my_data"))

    async def test_too_many_messages_go_to_the_support_server(self):
        self.posts = [dict(SAMPLE_POST, message_id=number) for number in range(400)]
        self.patch(commands, "EXPORT_MAX_MESSAGES", 1)
        self.patch(commands, "EXPORT_FILES_PER_MESSAGE", 1)
        _interaction, view = await self.open_panel()
        pressed, accepted = self.refusing_over(40_000)
        sent = []
        refuse = pressed.followup.send

        async def send(content=None, ephemeral=False, file=None, files=None, **kwargs):
            if not files and file is None:
                sent.append(content)
                return
            await refuse(content, ephemeral, file, files, **kwargs)

        pressed.followup.send = send
        await view.download_button.callback(pressed)

        self.assertEqual([messages.MY_DATA_EXPORT_TOO_LARGE], sent)

    async def test_a_user_install_outside_a_server_with_the_bot_takes_fewer_messages(self):
        """Discord allows only 5 followups there, which the whole file and a failure notice share."""
        self.posts = [dict(SAMPLE_POST, message_id=number) for number in range(400)]
        self.patch(commands, "EXPORT_FILES_PER_MESSAGE", 1)
        _interaction, view = await self.open_panel()
        pressed, accepted = self.refusing_over(40_000)
        pressed.guild_install = False
        sent = []
        refuse = pressed.followup.send

        async def send(content=None, ephemeral=False, file=None, files=None, **kwargs):
            if not files and file is None:
                sent.append(content)
                return
            await refuse(content, ephemeral, file, files, **kwargs)

        pressed.followup.send = send
        await view.download_button.callback(pressed)

        self.assertEqual([messages.MY_DATA_EXPORT_TOO_LARGE], sent)
        self.assertEqual([], accepted)

    def test_the_message_limit_follows_the_install(self):
        server = FakeInteraction()
        user_install = FakeInteraction()
        user_install.guild_install = False

        self.assertEqual(commands.EXPORT_MAX_MESSAGES, commands.export_max_messages(server))
        self.assertEqual(commands.EXPORT_MAX_MESSAGES_USER_INSTALL, commands.export_max_messages(user_install))
        self.assertLessEqual(commands.EXPORT_MAX_MESSAGES_USER_INSTALL + 2, 5)

    async def test_parts_are_not_sent_twice_when_a_later_message_is_refused(self):
        """Resending after some parts went out would leave the member with two sets that do not match."""
        self.posts = [dict(SAMPLE_POST, message_id=number) for number in range(400)]
        self.patch(commands, "EXPORT_FILES_PER_MESSAGE", 1)
        _interaction, view = await self.open_panel()
        pressed = FakeInteraction()
        attempts = []
        sent = []

        async def send(content=None, ephemeral=False, file=None, files=None, **_kwargs):
            if not files and file is None:
                sent.append(content)
                return
            attempts.append([attached.filename for attached in files])
            # The whole file and the second part are refused for their size, the first part is accepted
            if len(attempts) != 2:
                response = types.SimpleNamespace(status=413, reason="Payload Too Large")
                raise discord.HTTPException(response, {"code": 40005, "message": "Request entity too large"})

        pressed.followup.send = send
        await view.download_button.callback(pressed)

        self.assertEqual(3, len(attempts))
        self.assertEqual([messages.MY_DATA_EXPORT_SEND_FAILED], sent)
        self.assertFalse(main.on_daily_cooldown(77, "my_data"))

    async def test_a_refusal_that_is_not_about_size_is_reported_without_splitting(self):
        _interaction, view = await self.open_panel()
        pressed, accepted = self.refusing_over(0, status=503)
        sent = []
        refuse = pressed.followup.send

        async def send(content=None, ephemeral=False, file=None, files=None, **kwargs):
            if not files and file is None:
                sent.append(content)
                return
            response = types.SimpleNamespace(status=503, reason="Service Unavailable")
            raise discord.HTTPException(response, "Discord is down")

        pressed.followup.send = send
        await view.download_button.callback(pressed)

        self.assertEqual([messages.MY_DATA_EXPORT_SEND_FAILED], sent)
        self.assertTrue(any("Discord refused a member's data export" in entry for entry in self.logged))
        self.assertFalse(main.on_daily_cooldown(77, "my_data"))

    async def test_once_a_day(self):
        _interaction, view = await self.open_panel()
        await self.press(view.download_button)
        again = await self.press(view.download_button)

        self.assertEqual([messages.MY_DATA_DOWNLOAD_ON_COOLDOWN], again.response.messages)
        self.assertEqual([True], again.response.ephemeral)

    async def test_a_failure_is_reported_and_does_not_use_up_the_day(self):
        def fail(*_args):
            raise RuntimeError("database went away")

        self.patch(hall_of_fame_message_repo, "get_messages_by_author", fail)
        _interaction, view = await self.open_panel()
        pressed = await self.press(view.download_button)

        self.assertEqual([messages.COMMAND_FAILED], pressed.followup.messages)
        self.assertFalse(main.on_daily_cooldown(77, "my_data"))


class ConcurrentPressTests(MyDataPanelTestCase):
    async def test_two_quick_downloads_read_the_data_once(self):
        """The day is taken before the first await, so a second press while the first runs is refused."""
        reads = []
        self.patch(hall_of_fame_message_repo, "get_messages_by_author",
                   lambda *_args: reads.append(True) or self.posts)
        _interaction, view = await self.open_panel()
        first, second = FakeInteraction(), FakeInteraction()
        await asyncio.gather(view.download_button.callback(first), view.download_button.callback(second))

        self.assertEqual(1, len(reads))
        self.assertIn(messages.MY_DATA_DOWNLOAD_ON_COOLDOWN, first.response.messages + second.response.messages)

    async def test_a_second_press_of_delete_while_the_first_is_answered_is_ignored(self):
        """Two confirmations on one message would let the first one's expiry overwrite the done message."""
        _interaction, view = await self.open_panel()
        view.delete_pending = True
        pressed = await self.press(view.delete_button)

        self.assertTrue(pressed.response.deferred)
        self.assertEqual([], pressed.original_edits)
        self.assertEqual([], pressed.followup.messages)


class TotalsAcrossServersButtonTests(MyDataPanelTestCase):
    async def test_hides_the_totals(self):
        _interaction, view = await self.open_panel()
        pressed = await self.press(view.totals_button)

        self.assertEqual({77}, self.hidden)
        content, new_view = pressed.original_edits[0]
        self.assertIn("Your totals across servers are hidden", content)
        self.assertIn("<t:", content)
        self.assertEqual(messages.SHOW_TOTALS_BUTTON, new_view.totals_button.label)

    async def test_shows_them_again(self):
        self.hidden.add(77)
        _interaction, view = await self.open_panel()
        self.assertEqual(messages.SHOW_TOTALS_BUTTON, view.totals_button.label)
        pressed = await self.press(view.totals_button)

        self.assertEqual(set(), self.hidden)
        self.assertIn(messages.MY_DATA_TOTALS_SHOWN, pressed.original_edits[0][0])

    async def test_is_not_held_back_by_the_download_limit(self):
        main.start_daily_cooldown(77, "my_data")
        _interaction, view = await self.open_panel()
        await self.press(view.totals_button)

        self.assertEqual({77}, self.hidden)

    async def test_stores_nothing_for_a_member_who_has_no_totals_since_the_panel_opened(self):
        """Not featured and nothing credited: the choice would be data kept about them for nothing."""
        _interaction, view = await self.open_panel()
        self.posts, self.standings = [], []
        self.opted_out.add(77)
        pressed = await self.press(view.totals_button)

        self.assertEqual(set(), self.hidden)
        content, new_view = pressed.original_edits[0]
        self.assertIn("New messages of yours are not featured", content)
        self.assertNotIn(new_view.totals_button, new_view.children)

    async def test_answers_the_button_before_reading_the_database(self):
        """The summary is read twice around the change, which can outlast the three seconds Discord waits."""
        _interaction, view = await self.open_panel()
        button = FakeInteraction()
        deferred_first = []
        self.patch(hall_of_fame_message_repo, "count_messages_by_author",
                   lambda *_args: deferred_first.append(button.response.deferred) or len(self.posts))
        await view.totals_button.callback(button)

        self.assertEqual([True, True], deferred_first)

    async def test_a_failure_is_reported(self):
        _interaction, view = await self.open_panel()

        def fail(*_args, **_kwargs):
            raise RuntimeError("canceling statement due to statement timeout")

        self.patch(global_profile_repo, "set_hidden", fail)
        pressed = await self.press(view.totals_button)

        self.assertEqual([(messages.COMMAND_FAILED, None)], pressed.original_edits)
        self.assertTrue(any("Error changing whether a member's totals are hidden" in entry for entry in self.logged))


class DeleteMyDataTests(MyDataPanelTestCase):
    async def test_asks_for_confirmation_before_deleting(self):
        _interaction, panel = await self.open_panel()
        pressed = await self.press(panel.delete_button)

        content, view = pressed.original_edits[0]
        self.assertEqual(messages.DELETE_MY_DATA_CONFIRM, content)
        self.assertIsInstance(view, ConfirmDeleteView)
        self.assertEqual([], self.calls)
        self.assertTrue(panel.is_finished())

    async def test_confirming_deletes_everything_posts_first(self):
        """The rebuild recreates statistics from the posts, so the posts must lose their author first."""
        view = await self.ask_to_delete()
        button = FakeInteraction()
        await view.confirm(button)

        self.assertEqual(["posts", "stats", "wrapped", "privacy", ("opt_out", False)], self.calls)
        content, offer = button.original_edits[0]
        self.assertEqual(messages.DELETE_MY_DATA_DONE.format(command=command_refs.MY_DATA), content)
        self.assertIsInstance(offer, StopFeaturingView)

    async def test_answers_the_button_before_deleting(self):
        """The deletes can outlast the three seconds Discord waits for a button to be answered."""
        view = await self.ask_to_delete()
        button = FakeInteraction()
        deferred_first = []
        self.patch(hall_of_fame_message_repo, "remove_author",
                   lambda *_args, **_kw: deferred_first.append(button.response.deferred) or 0)
        await view.confirm(button)

        self.assertEqual([True], deferred_first)

    async def test_deletes_in_one_transaction(self):
        """Each step leaves the commit to the end, so a failure part way deletes nothing."""
        kwargs = []
        for repo, name in ((hall_of_fame_message_repo, "remove_author"),
                           (server_user_repo, "delete_server_users_for_user"),
                           (hof_wrapped_repo, "delete_hof_wrapped_for_user"),
                           (global_profile_repo, "delete_for_user")):
            self.patch(repo, name, lambda *_args, **kw: kwargs.append(kw) or 0)
        view = await self.ask_to_delete()
        await view.confirm(FakeInteraction())

        self.assertEqual([{"commit": False}] * 4, kwargs)

    async def test_a_failed_deletion_is_reported_and_can_be_retried(self):
        def fail(*_args, **_kw):
            raise RuntimeError("canceling statement due to statement timeout")

        self.patch(server_user_repo, "delete_server_users_for_user", fail)
        view = await self.ask_to_delete()
        button = FakeInteraction()
        await view.confirm(button)

        self.assertEqual([(messages.COMMAND_FAILED, None)], button.original_edits)
        self.assertTrue(any("Error deleting a member's data" in entry for entry in self.logged))
        self.assertGreater(self.pool.connection.rollbacks, 0)
        self.assertIsInstance(await self.ask_to_delete(), ConfirmDeleteView)

    async def test_the_log_does_not_name_the_member(self):
        view = await self.ask_to_delete()
        await view.confirm(FakeInteraction())

        entry = [entry for entry in self.logged if "deleted their data" in entry][0]
        self.assertNotIn("Member", entry)

    async def test_once_a_day(self):
        view = await self.ask_to_delete()
        await view.confirm(FakeInteraction())
        _interaction, panel = await self.open_panel()
        pressed = await self.press(panel.delete_button)

        self.assertEqual([messages.MY_DATA_DELETE_ON_COOLDOWN], pressed.followup.messages)
        self.assertEqual([True], pressed.followup.ephemeral)
        self.assertEqual([], pressed.original_edits)

    async def test_is_not_held_back_by_the_download_limit(self):
        main.start_daily_cooldown(77, "my_data")

        self.assertIsInstance(await self.ask_to_delete(), ConfirmDeleteView)

    async def test_a_member_with_nothing_stored_is_not_held_to_the_limit(self):
        """With nothing left to scan the limit has no purpose."""
        view = await self.ask_to_delete()
        await view.confirm(FakeInteraction())
        self.posts, self.standings = [], []
        self.hidden.add(77)

        self.assertIsInstance(await self.ask_to_delete(), ConfirmDeleteView)

    async def test_the_confirmation_warns_that_the_choice_not_to_be_featured_goes_too(self):
        self.opted_out.add(77)
        _interaction, panel = await self.open_panel()
        content = (await self.press(panel.delete_button)).original_edits[0][0]

        self.assertTrue(content.endswith(messages.DELETE_MY_DATA_CONFIRM_OPT_OUT))

    async def test_the_confirmation_says_nothing_about_featuring_to_a_featured_member(self):
        _interaction, panel = await self.open_panel()
        content = (await self.press(panel.delete_button)).original_edits[0][0]

        self.assertEqual(messages.DELETE_MY_DATA_CONFIRM, content)

    async def test_the_warning_follows_an_opt_out_made_since_the_panel_opened(self):
        """A panel opened before the member opted out from another /my_data must still warn."""
        _interaction, panel = await self.open_panel()
        self.opted_out.add(77)
        content = (await self.press(panel.delete_button)).original_edits[0][0]

        self.assertTrue(content.endswith(messages.DELETE_MY_DATA_CONFIRM_OPT_OUT))

    async def test_a_failure_reading_the_summary_is_reported(self):
        _interaction, panel = await self.open_panel()

        def fail(*_args):
            raise RuntimeError("database went away")

        self.patch(hall_of_fame_message_repo, "count_messages_by_author", fail)
        pressed = await self.press(panel.delete_button)

        self.assertEqual([(messages.COMMAND_FAILED, None)], pressed.original_edits)
        self.assertEqual([], self.calls)
        self.assertTrue(panel.is_finished())


class HiddenChoiceAfterStoppingTests(MyDataPanelTestCase):
    async def test_a_stored_hidden_choice_stays_listed_and_can_be_undone(self):
        """Hidden, then not featured with no posts: the choice is still stored, so it must still show."""
        self.posts, self.standings = [], []
        self.hidden.add(77)
        self.opted_out.add(77)
        interaction, view = await self.open_panel()

        self.assertIn(messages.MY_DATA_TOTALS_HIDDEN.format(since=CHOSEN_SHOWN), interaction.followup.messages[0])
        self.assertIn(view.totals_button, view.children)
        self.assertEqual(messages.SHOW_TOTALS_BUTTON, view.totals_button.label)

    async def test_showing_them_again_is_stored_even_without_totals(self):
        self.posts, self.standings = [], []
        self.hidden.add(77)
        self.opted_out.add(77)
        _interaction, view = await self.open_panel()
        await self.press(view.totals_button)

        self.assertEqual(set(), self.hidden)


class StopFeaturingTests(MyDataPanelTestCase):
    """Stop featuring me: a setting of its own on /my_data, which concerns new messages only."""

    async def test_the_panel_button_stops_featuring_without_deleting(self):
        _interaction, view = await self.open_panel()
        pressed = await self.press(view.featuring_button)

        self.assertEqual({77}, self.opted_out)
        self.assertEqual([("opt_out", True)], self.calls)
        content, new_view = pressed.original_edits[0]
        self.assertTrue(content.startswith(messages.STOPPED_FEATURING))
        self.assertEqual(messages.FEATURE_ME_AGAIN_BUTTON, new_view.featuring_button.label)

    async def test_feature_me_again(self):
        self.opted_out.add(77)
        _interaction, view = await self.open_panel()
        self.assertEqual(messages.FEATURE_ME_AGAIN_BUTTON, view.featuring_button.label)
        pressed = await self.press(view.featuring_button)

        self.assertEqual(set(), self.opted_out)
        content, new_view = pressed.original_edits[0]
        self.assertTrue(content.startswith(messages.COUNTED_AGAIN))
        self.assertNotIn("New messages of yours are not featured", content)
        self.assertEqual(messages.STOP_FEATURING_BUTTON, new_view.featuring_button.label)

    async def test_earlier_posts_and_statistics_are_kept(self):
        """Only new messages are left out, so the history and everything to manage it stays."""
        self.opted_out.add(77)
        interaction, view = await self.open_panel()

        content = interaction.followup.messages[0]
        self.assertIn(messages.MY_DATA_NOT_FEATURED.format(since=CHOSEN_SHOWN), content)
        self.assertIn(messages.MY_DATA_EARLIER_KEPT, content)
        for button in (view.download_button, view.totals_button, view.delete_button):
            self.assertIn(button, view.children)

    async def test_with_only_the_choice_stored_it_can_be_downloaded_and_deleted(self):
        """The choice is data about the member too, so Download and Delete work for it; there are no totals to hide."""
        self.posts, self.standings = [], []
        self.opted_out.add(77)
        interaction, view = await self.open_panel()

        content = interaction.followup.messages[0]
        self.assertNotIn(messages.MY_DATA_EARLIER_KEPT, content)
        self.assertNotIn(messages.MY_DATA_TOTALS_SHOWN_ONCE_FEATURED, content)
        self.assertEqual([view.download_button, view.featuring_button, view.delete_button], view.children)
        self.assertFalse(view.download_button.disabled)
        self.assertFalse(view.delete_button.disabled)

    async def test_downloading_right_after_stopping_includes_the_choice(self):
        self.posts, self.standings = [], []
        _interaction, view = await self.open_panel()
        stopped = (await self.press(view.featuring_button)).original_edits[0][1]
        pressed = await self.press(stopped.download_button)

        [file] = pressed.followup.attachments[0]
        export = json.loads(file.fp.getvalue())
        self.assertTrue(export["not_counted"])
        self.assertEqual([], export["featured_posts"])

    async def test_delete_is_offered_while_something_is_stored(self):
        """A member who only hid their totals still has that choice to delete."""
        self.posts, self.standings = [], []
        self.hidden.add(77)
        _interaction, view = await self.open_panel()

        self.assertFalse(view.delete_button.disabled)

    async def test_delete_is_greyed_out_for_a_member_with_nothing_stored(self):
        self.posts, self.standings = [], []
        _interaction, view = await self.open_panel()

        self.assertTrue(view.delete_button.disabled)

    async def test_the_buttons_come_alive_once_something_is_stored(self):
        """Hiding the totals stores a choice, so there is something to delete from then on."""
        self.posts, self.standings = [], []
        _interaction, view = await self.open_panel()
        pressed = await self.press(view.totals_button)

        self.assertFalse(pressed.original_edits[0][1].delete_button.disabled)

    async def test_is_not_held_back_by_the_cooldowns(self):
        main.start_daily_cooldown(77, "delete_my_data")
        main.start_daily_cooldown(77, "my_data")
        _interaction, view = await self.open_panel()
        await self.press(view.featuring_button)

        self.assertEqual({77}, self.opted_out)

    async def test_deleting_offers_to_stop_featuring(self):
        view = await self.ask_to_delete()
        button = FakeInteraction()
        await view.confirm(button)
        offer = button.original_edits[0][1]
        pressed = await self.press(offer.children[0])

        self.assertEqual({77}, self.opted_out)
        self.assertEqual(["posts", "stats", "wrapped", "privacy", ("opt_out", False), ("opt_out", True)], self.calls)
        self.assertEqual([(messages.DELETE_MY_DATA_DONE_STOPPED.format(command=command_refs.MY_DATA), None)],
                         pressed.original_edits)

    async def test_deleting_also_deletes_the_choice_not_to_be_featured(self):
        """Deleting removes everything stored, and then offers to stop featuring the member afresh."""
        self.opted_out.add(77)
        view = await self.ask_to_delete()
        button = FakeInteraction()
        await view.confirm(button)

        self.assertEqual(set(), self.opted_out)
        content, offer = button.original_edits[0]
        self.assertEqual(messages.DELETE_MY_DATA_DONE.format(command=command_refs.MY_DATA), content)
        self.assertIsInstance(offer, StopFeaturingView)

    async def test_only_the_member_can_take_the_offer(self):
        offer = StopFeaturingView(77, on_stop=None)
        stranger = FakeInteraction()
        stranger.user = FakeUser(user_id=99)

        self.assertFalse(await offer.interaction_check(stranger))
        self.assertEqual([messages.MY_DATA_NOT_YOURS], stranger.response.messages)


class OptingOutWhileAPostIsSentTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_insert_is_left_to_leave_the_member_out(self):
        """
        insert_hall_of_fame_message checks opted_out_member in the same statement, which the PostgreSQL test
        of a member opting out while their post is sent covers, so the member is passed as they are and the
        opt-out is not looked up a second time
        """
        import utils
        stored = []
        answers = iter([False, True])

        def record(_connection, *args):
            stored.append(args)

        async def send(*_args, **_kwargs):
            return types.SimpleNamespace(id=999)

        async def no_embed(*_args, **_kwargs):
            return None

        async def count(*_args, **_kwargs):
            return 5

        channel = types.SimpleNamespace(send=send)
        bot = types.SimpleNamespace(get_channel=lambda _id: channel)
        message = types.SimpleNamespace(id=1, channel=types.SimpleNamespace(id=2), guild=types.SimpleNamespace(id=3),
                                        author=types.SimpleNamespace(id=77))
        # Featured when the post is checked, opted out by the time it is stored
        with unittest.mock.patch.object(opt_out_repo, "is_opted_out", lambda *_args: next(answers)), \
                unittest.mock.patch.object(hall_of_fame_message_repo, "insert_hall_of_fame_message", record), \
                unittest.mock.patch.object(utils, "create_embed", no_embed), \
                unittest.mock.patch.object(utils, "reaction_count", count), \
                unittest.mock.patch.object(utils, "check_video_extension", lambda _m: None):
            await utils.post_hall_of_fame_message(message, bot, FakeConnection(), 100, 5)

        # The sixth value stored is the author
        self.assertEqual(77, stored[0][5])
        self.assertEqual(True, next(answers), "the opt-out was looked up again before storing")


class WrappedWithoutTheAuthorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_detached_post_is_credited_to_nobody(self):
        """Discord still knows who wrote it, so it must not be fetched and handed back to them."""
        import hof_wrapped
        rows = [{"channel_id": 2, "message_id": 1, "author_id": hall_of_fame_message_repo.NO_AUTHOR_ID}]
        fetched = []
        guild = types.SimpleNamespace(id=200, get_channel=lambda channel_id: fetched.append(channel_id))
        with unittest.mock.patch.object(hof_wrapped.hall_of_fame_message_repo,
                                        "get_all_hall_of_fame_messages_for_guild", lambda *_args: rows):
            await hof_wrapped.process_hof_messages_from_db(guild, FakeConnection())

        self.assertEqual([], fetched)

    def test_a_member_who_deleted_while_rows_were_saved_is_deleted_again(self):
        """Saving takes a while, so a deletion in the middle would otherwise be undone by the rows after it."""
        import hof_wrapped
        deleted = []
        with unittest.mock.patch.object(hof_wrapped, "users", {77: object(), 88: object()}), \
                unittest.mock.patch.object(hof_wrapped.hall_of_fame_message_repo, "find_members_for_guild",
                                           lambda *_args: [88]), \
                unittest.mock.patch.object(hof_wrapped.hof_wrapped_repo, "delete_hof_wrapped_for_user",
                                           lambda _connection, user_id: deleted.append(user_id)):
            hof_wrapped.forget_members_who_deleted_meanwhile(FakeConnection(), 200)

        self.assertEqual([77], deleted)


class NotFeaturedPostingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_message_by_a_member_who_is_not_featured_is_neither_posted_nor_stored(self):
        import utils
        stored = []
        sent = []

        def record(_connection, *args):
            stored.append(args)

        channel = types.SimpleNamespace(send=None)

        async def send(*_args, **_kwargs):
            sent.append(_args)
            return types.SimpleNamespace(id=999)

        channel.send = send
        bot = types.SimpleNamespace(get_channel=lambda _id: channel)
        message = types.SimpleNamespace(id=1, channel=types.SimpleNamespace(id=2), guild=types.SimpleNamespace(id=3),
                                        author=types.SimpleNamespace(id=77))

        async def no_embed(*_args, **_kwargs):
            return None

        async def count(*_args, **_kwargs):
            return 5

        with unittest.mock.patch.object(opt_out_repo, "is_opted_out", lambda _c, user_id: user_id == 77), \
                unittest.mock.patch.object(hall_of_fame_message_repo, "insert_hall_of_fame_message", record), \
                unittest.mock.patch.object(utils, "create_embed", no_embed), \
                unittest.mock.patch.object(utils, "reaction_count", count), \
                unittest.mock.patch.object(utils, "check_video_extension", lambda _m: None):
            await utils.post_hall_of_fame_message(message, bot, FakeConnection(), 100, 5)

        self.assertEqual([], sent)
        self.assertEqual([], stored)


class DataCommandContextTests(unittest.TestCase):
    def test_data_commands_work_outside_servers(self):
        """Someone who left every server with the bot must still be able to reach their data."""
        for command in (main.my_data,):
            with self.subTest(command=command.name):
                self.assertTrue(command.allowed_installs.user)
                self.assertTrue(command.allowed_contexts.dm_channel)

    def test_the_server_commands_stay_inside_servers(self):
        for command in (main.count_in_global_profiles, main.leaderboard, main.hof_wrapped_command):
            with self.subTest(command=command.name):
                self.assertIsNone(command.allowed_installs)
                self.assertIsNone(command.allowed_contexts)


def user_with_avatar(user_id):
    user = FakeUser(user_id=user_id)
    user.display_avatar = types.SimpleNamespace(url=f"https://cdn.example/{user_id}.png")
    return user


def outside_a_server(guild_id=None):
    """A user install answers in a DM (no guild) or in a server the bot is not in."""
    interaction = FakeInteraction()
    interaction.guild_id = guild_id
    interaction.guild = None
    interaction.user = user_with_avatar(77)
    return interaction


class UserProfileOutsideServerTests(CommandTestCase):
    """/user_profile through a user install shows your own totals across servers, and only yours."""

    def setUp(self):
        super().setUp()
        self.hidden = set()
        self.profile = dict(PROFILE)
        self.server_reads = []
        self.profile_reads = []
        self.patch(global_profile_repo, "is_hidden", lambda _connection, user_id: user_id in self.hidden)

        def read_profile(_connection, user_id, guild_id=None):
            self.profile_reads.append(user_id)
            return self.profile

        self.patch(global_profile_repo, "get_global_profile", read_profile)
        self.patch(main.server_user_repo, "get_server_user",
                   lambda *args: self.server_reads.append(args) or {"total_hall_of_fame_messages": 40})

    async def test_a_dm_gets_your_totals_card_without_reading_a_server(self):
        interaction = outside_a_server()
        await main.user_server_profile.callback(interaction, None)

        # Deferred first, since waiting for a connection can outlast Discord's three seconds
        self.assertTrue(interaction.response.deferred)
        self.assertFalse(interaction.response.deferred_ephemeral)
        embed = interaction.followup.messages[0]
        self.assertIsInstance(embed, discord.Embed)
        self.assertEqual([messages.GLOBAL_PROFILE_HEADING, messages.BADGES_HEADING],
                         [field.name for field in embed.fields])
        self.assertIn("**47** posts", embed.fields[0].value)
        self.assertEqual([False], interaction.followup.ephemeral)
        self.assertEqual([], self.server_reads)

    async def test_naming_yourself_is_the_same_as_leaving_it_out(self):
        interaction = outside_a_server()
        await main.user_server_profile.callback(interaction, user_with_avatar(77))

        self.assertIsInstance(interaction.followup.messages[0], discord.Embed)

    async def test_a_server_without_the_bot_gets_the_same_card(self):
        interaction = outside_a_server(guild_id=999)
        await main.user_server_profile.callback(interaction, None)

        self.assertIsInstance(interaction.followup.messages[0], discord.Embed)
        self.assertEqual([], self.server_reads)

    async def test_another_member_cannot_be_looked_up_outside_a_server_with_the_bot(self):
        """Their totals would reach a DM or a server that never added the bot."""
        for guild_id in (None, 999):
            with self.subTest(guild_id=guild_id):
                interaction = outside_a_server(guild_id=guild_id)
                await main.user_server_profile.callback(interaction, user_with_avatar(88))

                self.assertEqual([messages.PROFILE_OTHERS_OUTSIDE_SERVER.format(command=command_refs.USER_PROFILE)],
                                 interaction.response.messages)
                self.assertEqual([True], interaction.response.ephemeral)
        self.assertEqual([], self.profile_reads)
        self.assertEqual(0, self.pool.handed_out)

    async def test_no_posts_anywhere_says_so(self):
        self.profile = {field: 0 for field in global_profile_repo.PROFILE_FIELDS}
        interaction = outside_a_server()
        await main.user_server_profile.callback(interaction, None)

        self.assertEqual([messages.PROFILE_NOTHING_OUTSIDE_SERVER], interaction.followup.messages)
        self.assertEqual([True], interaction.followup.ephemeral)
        self.assertTrue(interaction.deleted_original, "the public thinking message was left to carry the refusal")

    async def test_hidden_totals_are_not_shown_even_to_you(self):
        """The card is posted in the channel, so showing them to you shows them to everyone there."""
        self.hidden.add(77)
        interaction = outside_a_server()
        await main.user_server_profile.callback(interaction, None)

        self.assertEqual([messages.PROFILE_HIDDEN_OUTSIDE_SERVER_SELF.format(command=command_refs.MY_DATA)],
                         interaction.followup.messages)
        self.assertEqual([True], interaction.followup.ephemeral)
        self.assertEqual([], self.profile_reads)

    async def test_a_server_with_the_bot_but_no_setup_is_told_so(self):
        """Not "outside a server with Hall of Fame": the bot is there, its setup did not finish."""
        interaction = outside_a_server(guild_id=999)
        with unittest.mock.patch.object(main, "bot", types.SimpleNamespace(get_guild=lambda _guild_id: object())):
            await main.user_server_profile.callback(interaction, None)

        self.assertEqual([messages.ERROR_SERVER_NOT_SETUP], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_a_server_with_the_bot_can_still_look_up_other_members(self):
        recorded = []

        async def record(_interaction, user, *_args, **_kwargs):
            recorded.append(user.id)

        self.patch(main.commands, "user_server_profile", record)
        await main.user_server_profile.callback(FakeInteraction(), FakeUser(user_id=88))

        self.assertEqual([88], recorded)
        self.assertEqual(1, len(self.server_reads))


class GlobalProfileEmbedTests(unittest.TestCase):
    def test_names_and_links_no_server(self):
        embed = commands.build_global_profile_embed(user_with_avatar(88), dict(PROFILE, servers=6))
        text = " ".join([embed.description or ""] + [f"{field.name} {field.value}" for field in embed.fields])

        self.assertNotIn("discord.com/channels", text)
        self.assertNotIn("<#", text)
        self.assertIn(messages.BADGE_SERVERS.format(servers=6), text)

    def test_leaves_the_badges_out_when_none_are_earned(self):
        small = {"posts": 2, "reactions": 9, "servers": 1, "biggest_post": 5, "best_month": 1, "top_of_board": 0}
        embed = commands.build_global_profile_embed(user_with_avatar(88), small)

        self.assertEqual([messages.GLOBAL_PROFILE_HEADING], [field.name for field in embed.fields])




class ViewOwnerAndTimeoutTests(unittest.IsolatedAsyncioTestCase):
    """The three /my_data views: only their member may press them, and they tidy up when they expire."""

    def views(self):
        summary = {"posts": 1, "servers": 1, "wrapped": 0, "hidden_since": None, "opted_out_since": None}

        async def nothing(*_args):
            return None

        return (ConfirmDeleteView(77, nothing), StopFeaturingView(77, nothing),
                MyDataView(77, summary, nothing, nothing, nothing, nothing))

    async def test_the_member_who_asked_may_press_them(self):
        for view in self.views():
            with self.subTest(view=type(view).__name__):
                self.assertTrue(await view.interaction_check(FakeInteraction()))

    async def test_an_expired_view_drops_its_buttons(self):
        for view in self.views():
            with self.subTest(view=type(view).__name__):
                original = FakeInteraction()
                view.original_interaction = original
                await view.on_timeout()

                self.assertEqual(1, len(original.original_edits))
                self.assertIsNone(original.original_edits[0][1])

    async def test_an_expired_confirmation_says_nothing_was_deleted(self):
        view = self.views()[0]
        original = FakeInteraction()
        view.original_interaction = original
        await view.on_timeout()

        self.assertEqual(messages.DELETE_MY_DATA_EXPIRED.format(command=command_refs.MY_DATA),
                         original.original_edits[0][0])

    async def test_a_finished_view_leaves_its_message_alone(self):
        for view in self.views():
            with self.subTest(view=type(view).__name__):
                original = FakeInteraction()
                view.original_interaction = original
                view.finished = True
                await view.on_timeout()

                self.assertEqual([], original.original_edits)

    async def test_a_view_without_its_message_does_nothing(self):
        for view in self.views():
            with self.subTest(view=type(view).__name__):
                await view.on_timeout()

    async def test_a_dismissed_message_is_not_an_error(self):
        async def gone(**_kwargs):
            raise discord.HTTPException(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")

        for view in self.views():
            with self.subTest(view=type(view).__name__):
                view.original_interaction = types.SimpleNamespace(edit_original_response=gone)
                await view.on_timeout()


class ExportEdgeTests(unittest.TestCase):
    def test_no_files_make_no_messages(self):
        self.assertEqual([], batch_export_files([]))

    def test_a_part_that_comes_out_too_big_is_never_sent(self):
        """Part sizes are worked out, not measured, so each part is measured again before it goes."""
        real = commands.encode_export

        def padded(document):
            # Only parts holding rows come out bigger, so the room worked out for an empty part is right
            return real(document) + (b" " * 10_000 if "part" in document and document["featured_posts"] else b"")

        document = build_my_data_document(77, [dict(SAMPLE_POST, message_id=n) for n in range(100)], [], [], False)
        with unittest.mock.patch.object(commands, "encode_export", padded):
            with self.assertRaises(ExportTooLarge):
                split_my_data_export(document, max_bytes=8_000)


class CheckSetupButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_press_before_the_bot_has_logged_in_does_nothing(self):
        """The handler is registered at login, and a press that comes earlier must not fail."""
        with unittest.mock.patch.object(commands, "setup_check_handler", None):
            await commands.SetupCheckView.check_setup(FakeInteraction())

    async def test_a_press_runs_the_registered_check(self):
        pressed = []

        async def handler(interaction):
            pressed.append(interaction)

        interaction = FakeInteraction()
        with unittest.mock.patch.object(commands, "setup_check_handler", handler):
            await commands.SetupCheckView.check_setup(interaction)

        self.assertEqual([interaction], pressed)


class TimeZoneEdgeTests(unittest.TestCase):
    """Dates read back with a time zone already are used as they are."""

    def test_a_first_feature_with_a_time_zone_still_earns_the_year_badge(self):
        facts = {"posts_by_month": [], "biggest_post": 0, "champion_months": 0,
                 "first_featured": datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)}

        self.assertIn(messages.BADGE_VETERAN, commands.earned_badges(facts, None))

    def test_a_last_feature_with_a_time_zone_is_shown(self):
        last = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        value = commands.highlights_value(1, {"best_post": None, "last_featured": last}, None)

        self.assertIn(f"<t:{int(last.timestamp())}:R>", value)


class RankGapSharingFirstTests(unittest.TestCase):
    def test_a_leader_level_with_second_place_shares_first(self):
        stats = {"this_month_hall_of_fame_messages": 5, "monthly_message_rank": 1}
        line = commands.rank_gap_line(stats, lambda *_args: 5)

        self.assertEqual(messages.HIGHLIGHT_SHARING_FIRST.format(period="this month"), line)



class RepositoryEmptyResultTests(unittest.TestCase):
    def test_totals_across_servers_are_zero_when_nothing_comes_back(self):
        profile = global_profile_repo.get_global_profile(FakeConnection(row=None), 77)

        self.assertEqual({field: 0 for field in global_profile_repo.PROFILE_FIELDS}, profile)

    def test_post_activity_is_empty_when_nothing_comes_back(self):
        self.assertEqual({"total": 0, "latest": None, "today": 0},
                         hall_of_fame_message_repo.get_post_activity(FakeConnection(row=None), 200))

    def test_finding_opted_out_members_among_nobody_asks_nothing(self):
        connection = FakeConnection()

        self.assertEqual(set(), opt_out_repo.find_opted_out(connection, []))
        self.assertEqual([], connection.queries)

    def test_finds_the_opted_out_members_among_those_asked_about(self):
        connection = FakeConnection(rows=[(77,)])

        self.assertEqual({77}, opt_out_repo.find_opted_out(connection, {77, 88}))




class FeaturingFailureTests(MyDataPanelTestCase):
    """Stopping searches every stored Wrapped, so a timeout there is answered rather than left hanging."""

    def failing(self):
        async def fail(_user_id):
            raise RuntimeError("canceling statement due to statement timeout")

        self.patch(main, "stop_featuring_member", fail)

    async def test_a_failure_on_the_panel_is_reported(self):
        self.failing()
        _interaction, view = await self.open_panel()
        pressed = await self.press(view.featuring_button)

        self.assertEqual([(messages.COMMAND_FAILED, None)], pressed.original_edits)
        self.assertTrue(any("Error changing whether a member is featured" in entry for entry in self.logged))

    async def test_a_failure_after_deleting_is_reported(self):
        view = await self.ask_to_delete()
        button = FakeInteraction()
        await view.confirm(button)
        self.failing()
        pressed = await self.press(button.original_edits[0][1].children[0])

        self.assertEqual([(messages.COMMAND_FAILED, None)], pressed.original_edits)

    async def test_a_failure_reading_the_panel_again_still_says_the_change_worked(self):
        """The opt-out is stored by then, so the member hears that, rather than a stale panel or nothing."""
        _interaction, view = await self.open_panel()

        def fail_after_the_change(*_args):
            if self.opted_out:
                raise RuntimeError("canceling statement due to statement timeout")
            return len(self.posts)

        self.patch(hall_of_fame_message_repo, "count_messages_by_author", fail_after_the_change)
        pressed = await self.press(view.featuring_button)

        self.assertEqual({77}, self.opted_out)
        self.assertEqual([(messages.STOPPED_FEATURING, None)], pressed.original_edits)
        self.assertTrue(view.is_finished())
        self.assertTrue(any("after changing whether they are featured" in entry for entry in self.logged))

    async def test_stopping_records_the_opt_out_and_clears_the_fan_lists_together(self):
        cleared = []
        self.patch(hof_wrapped_repo, "remove_from_fan_lists",
                   lambda _c, user_id, commit=True: cleared.append((user_id, commit)))
        await main.stop_featuring_member(77)

        self.assertEqual({77}, self.opted_out)
        self.assertEqual([(77, False)], cleared)
        self.assertTrue(any("statement_timeout" in query for query in self.pool.connection.queries))



if __name__ == "__main__":
    unittest.main()
