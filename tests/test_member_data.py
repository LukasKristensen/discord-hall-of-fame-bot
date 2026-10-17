"""Tests for what members can do with their own data: see it, delete it, and the global profile.

These commands are where the privacy policy's promises are kept, so the tests pin the promises
themselves: the global profile never shows a server, a hidden profile cannot be told apart from an
empty one, an export goes only to the member it describes, and a deletion survives the daily rebuild.
"""

import datetime
import json
import types
import unittest
import unittest.mock

import discord

import main
import commands
from commands import ConfirmDeleteView, CountAgainView, build_my_data_export
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

PROFILE = {"posts": 47, "reactions": 1382, "servers": 3, "biggest_post": 120, "best_month": 11, "top_of_board": 2}


class GlobalProfileRepoTests(unittest.TestCase):
    def test_maps_the_totals_by_name(self):
        connection = FakeConnection(row=(47, 1382, 3, 120, 11, 2))

        self.assertEqual(PROFILE, global_profile_repo.get_global_profile(connection, 77))

    def test_a_member_with_nothing_gets_zeros(self):
        connection = FakeConnection(row=(0, None, 0, None, None, 0))

        self.assertEqual({field: 0 for field in global_profile_repo.PROFILE_FIELDS},
                         global_profile_repo.get_global_profile(connection, 77))

    def test_returns_totals_only(self):
        """Nothing that could name or point to a server may leave the query."""
        connection = FakeConnection(row=(1, 5, 1, 5, 1, 0))
        profile = global_profile_repo.get_global_profile(connection, 77)

        self.assertEqual(set(global_profile_repo.PROFILE_FIELDS), set(profile))
        self.assertNotIn("guild", " ".join(profile))

    def test_leaves_out_servers_that_opted_out(self):
        connection = FakeConnection(row=(0, 0, 0, 0, 0, 0))
        global_profile_repo.get_global_profile(connection, 77)

        query = " ".join(connection.queries[0].split())
        self.assertIn("count_in_global_profiles", query)
        self.assertEqual({"user_id": 77}, connection.parameters[0])

    def test_counts_every_post_so_the_totals_match_the_server_profiles(self):
        """No size or reaction filter, or a member's servers would not add up to their global card."""
        connection = FakeConnection(row=(0, 0, 0, 0, 0, 0))
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


class MemberDataRepoTests(unittest.TestCase):
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
        self.assertFalse(commands.global_profile_adds_something(PROFILE, {"total_hall_of_fame_messages": 47}))
        self.assertTrue(commands.global_profile_adds_something(PROFILE, {"total_hall_of_fame_messages": 40}))

    def test_not_shown_without_totals(self):
        self.assertFalse(commands.global_profile_adds_something(None, {"total_hall_of_fame_messages": 40}))
        self.assertFalse(commands.global_profile_adds_something(dict(PROFILE, posts=0), {}))


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
        self.assertEqual([messages.DELETE_MY_DATA_NOT_YOURS], stranger.response.messages)

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

        def read_profile(_connection, user_id):
            self.profile_reads.append(user_id)
            return dict(PROFILE)

        self.patch(global_profile_repo, "get_global_profile", read_profile)

        async def record(_interaction, _user, _stats, _connection, _month, _all_time, global_profile=None):
            self.given.append(global_profile)

        self.patch(main.commands, "user_server_profile", record)

    async def test_hands_the_totals_to_the_profile(self):
        await main.user_server_profile.callback(FakeInteraction(), FakeUser(user_id=88))

        self.assertEqual([PROFILE], self.given)

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
        self.assertEqual([], interaction.response.messages)

    async def test_no_data_anywhere_still_says_so(self):
        self.patch(main.server_user_repo, "get_server_user", lambda *_args: None)
        self.patch(global_profile_repo, "get_global_profile",
                   lambda *_args: {field: 0 for field in global_profile_repo.PROFILE_FIELDS})
        interaction = FakeInteraction()
        await main.user_server_profile.callback(interaction, FakeUser(user_id=88))

        self.assertEqual([messages.PROFILE_NO_DATA], interaction.response.messages)
        self.assertEqual([], self.given)

    async def test_hidden_totals_do_not_make_a_card_for_a_member_with_no_data_here(self):
        """Otherwise an empty card would reveal that the member was featured somewhere else."""
        self.patch(main.server_user_repo, "get_server_user", lambda *_args: None)
        self.hidden.add(88)
        interaction = FakeInteraction()
        await main.user_server_profile.callback(interaction, FakeUser(user_id=88))

        self.assertEqual([messages.PROFILE_NO_DATA], interaction.response.messages)

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
        return interaction.response.messages[0]

    async def test_shows_three_columns_side_by_side(self):
        embed = await self.build(PROFILE)

        self.assertEqual(["🏆 This month", "🌟 All time", messages.GLOBAL_PROFILE_HEADING],
                         [field.name for field in embed.fields])
        self.assertTrue(all(field.inline for field in embed.fields))

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
        fields = {field.name: field.value for field in interaction.response.messages[0].fields}

        self.assertIn("**0** posts · -", fields["🏆 This month"])
        self.assertIn("**7** posts · #2", fields["🌟 All time"])


class ProfilePrivacyCommandTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.hidden = set()
        self.patch(global_profile_repo, "is_hidden", lambda _connection, user_id: user_id in self.hidden)

        def set_hidden(_connection, user_id, hidden):
            (self.hidden.add if hidden else self.hidden.discard)(user_id)

        self.patch(global_profile_repo, "set_hidden", set_hidden)

    async def test_hides_the_profile_privately(self):
        interaction = FakeInteraction()
        await main.profile_privacy.callback(interaction, discord.app_commands.Choice(name="Hide", value="hide"))

        self.assertEqual({77}, self.hidden)
        self.assertEqual([messages.PROFILE_PRIVACY_HIDDEN], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)

    async def test_says_so_when_nothing_changes(self):
        interaction = FakeInteraction()
        await main.profile_privacy.callback(interaction, discord.app_commands.Choice(name="Show", value="show"))

        self.assertIn("already visible", interaction.response.messages[0])


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


class MyDataCommandTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.patch(main, "daily_command_cooldowns", {})
        self.posts = [{"guild_id": 200, "message_id": 400, "reaction_count": 9, "created_at": "2026-01-01"}]
        self.patch(hall_of_fame_message_repo, "get_messages_by_author", lambda *_args: self.posts)
        self.patch(server_user_repo, "get_server_users_for_user", lambda *_args: [{"guild_id": 200}])
        self.patch(hof_wrapped_repo, "get_hof_wrapped_for_user", lambda *_args: [])
        self.patch(global_profile_repo, "is_hidden", lambda *_args: False)

    async def test_sends_the_export_privately(self):
        interaction = FakeInteraction()
        await main.my_data.callback(interaction)

        self.assertTrue(interaction.response.deferred_ephemeral)
        self.assertEqual([True], interaction.followup.ephemeral)
        self.assertIsInstance(interaction.followup.files[0], discord.File)
        self.assertIn("1 featured post,", interaction.followup.messages[0])

    async def test_says_so_when_nothing_is_stored(self):
        self.posts = []
        self.patch(server_user_repo, "get_server_users_for_user", lambda *_args: [])
        interaction = FakeInteraction()
        await main.my_data.callback(interaction)

        self.assertEqual([messages.MY_DATA_EMPTY], interaction.followup.messages)
        self.assertEqual([None], interaction.followup.files)

    async def test_once_a_day(self):
        await main.my_data.callback(FakeInteraction())
        again = FakeInteraction()
        await main.my_data.callback(again)

        self.assertEqual([messages.COMMAND_ON_COOLDOWN], again.response.messages)
        self.assertEqual([True], again.response.ephemeral)

    async def test_a_failure_does_not_use_up_the_day(self):
        def fail(*_args):
            raise RuntimeError("database went away")

        self.patch(hall_of_fame_message_repo, "get_messages_by_author", fail)
        with self.assertRaises(RuntimeError):
            await main.my_data.callback(FakeInteraction())

        self.assertFalse(main.on_daily_cooldown(77, "my_data"))

    async def test_queries_run_under_a_statement_timeout(self):
        await main.my_data.callback(FakeInteraction())

        self.assertTrue(any("statement_timeout" in query for query in self.pool.connection.queries))


class DeleteMyDataCommandTests(CommandTestCase):
    def setUp(self):
        super().setUp()
        self.patch(main, "daily_command_cooldowns", {})
        self.calls = []
        self.patch(hall_of_fame_message_repo, "remove_author", lambda _c, user_id: self.calls.append("posts") or 3)
        self.patch(server_user_repo, "delete_server_users_for_user", lambda _c, user_id: self.calls.append("stats"))
        self.patch(hof_wrapped_repo, "delete_hof_wrapped_for_user", lambda _c, user_id: self.calls.append("wrapped"))
        self.patch(global_profile_repo, "delete_for_user", lambda _c, user_id: self.calls.append("privacy"))

    async def ask(self):
        interaction = FakeInteraction()
        await main.delete_my_data.callback(interaction)
        return interaction, interaction.response.views[0]

    async def test_asks_for_confirmation_privately_before_deleting(self):
        interaction, view = await self.ask()

        self.assertEqual([messages.DELETE_MY_DATA_CONFIRM], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)
        self.assertIsInstance(view, ConfirmDeleteView)
        self.assertEqual([], self.calls)

    async def test_confirming_deletes_everything_posts_first(self):
        """The rebuild recreates statistics from the posts, so the posts must lose their author first."""
        _interaction, view = await self.ask()
        button = FakeInteraction()
        await view.confirm(button)

        self.assertEqual(["posts", "stats", "wrapped", "privacy"], self.calls)
        self.assertEqual([(messages.DELETE_MY_DATA_DONE, None)], button.response.edits)

    async def test_the_log_does_not_name_the_member(self):
        _interaction, view = await self.ask()
        await view.confirm(FakeInteraction())

        entry = [entry for entry in self.logged if "deleted their data" in entry][0]
        self.assertNotIn("Member", entry)

    async def test_once_a_day(self):
        _interaction, view = await self.ask()
        await view.confirm(FakeInteraction())
        again = FakeInteraction()
        await main.delete_my_data.callback(again)

        self.assertEqual([messages.COMMAND_ON_COOLDOWN], again.response.messages)


class StopCountingTests(CommandTestCase):
    """Delete and stop counting me: the lasting way to object to being counted."""

    def setUp(self):
        super().setUp()
        self.patch(main, "daily_command_cooldowns", {})
        self.calls = []
        self.opted_out = set()
        self.patch(opt_out_repo, "is_opted_out", lambda _c, user_id: user_id in self.opted_out)

        def set_opted_out(_c, user_id, opted_out):
            self.calls.append(("opt_out", opted_out))
            (self.opted_out.add if opted_out else self.opted_out.discard)(user_id)

        self.patch(opt_out_repo, "set_opted_out", set_opted_out)
        self.patch(hall_of_fame_message_repo, "remove_author", lambda *_args: self.calls.append("posts") or 0)
        self.patch(server_user_repo, "delete_server_users_for_user", lambda *_args: self.calls.append("stats"))
        self.patch(hof_wrapped_repo, "delete_hof_wrapped_for_user", lambda *_args: self.calls.append("wrapped"))
        self.patch(global_profile_repo, "delete_for_user", lambda *_args: self.calls.append("privacy"))

    async def ask(self):
        interaction = FakeInteraction()
        await main.delete_my_data.callback(interaction)
        return interaction

    async def test_records_the_request_before_deleting(self):
        """A post featured while the deletion runs is then already stored without the member."""
        view = (await self.ask()).response.views[0]
        button = FakeInteraction()
        await view.confirm_and_stop_counting(button)

        self.assertEqual([("opt_out", True), "posts", "stats", "wrapped", "privacy"], self.calls)
        self.assertIn("not counted from now on", button.response.edits[0][0])

    async def test_plain_deletion_does_not_stop_counting(self):
        view = (await self.ask()).response.views[0]
        await view.confirm(FakeInteraction())

        self.assertNotIn(("opt_out", True), self.calls)

    async def test_offers_to_count_again_instead_of_deleting(self):
        self.opted_out.add(77)
        interaction = await self.ask()

        self.assertEqual([messages.NOT_COUNTED_STATUS], interaction.response.messages)
        self.assertEqual([True], interaction.response.ephemeral)
        self.assertIsInstance(interaction.response.views[0], CountAgainView)

    async def test_counting_again_is_not_held_back_by_the_cooldown(self):
        self.opted_out.add(77)
        main.start_daily_cooldown(77, "delete_my_data")
        interaction = await self.ask()

        self.assertEqual([messages.NOT_COUNTED_STATUS], interaction.response.messages)

    async def test_count_me_again(self):
        self.opted_out.add(77)
        view = (await self.ask()).response.views[0]
        button = FakeInteraction()
        await view.count_again(button)

        self.assertEqual(set(), self.opted_out)
        self.assertEqual([(messages.COUNTED_AGAIN, None)], button.response.edits)


class PostingWithoutTheAuthorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_post_by_a_member_who_is_not_counted_is_stored_without_them(self):
        import utils
        stored = []

        def record(_connection, *args):
            stored.append(args)

        channel = types.SimpleNamespace(send=None)

        async def send(*_args, **_kwargs):
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

        # The sixth value stored is the author
        self.assertEqual(hall_of_fame_message_repo.NO_AUTHOR_ID, stored[0][5])


class DataCommandContextTests(unittest.TestCase):
    def test_data_commands_work_outside_servers(self):
        """Someone who left every server with the bot must still be able to reach their data."""
        for command in (main.my_data, main.delete_my_data, main.profile_privacy):
            with self.subTest(command=command.name):
                self.assertTrue(command.allowed_installs.user)
                self.assertTrue(command.allowed_contexts.dm_channel)

    def test_the_server_commands_stay_inside_servers(self):
        for command in (main.user_server_profile, main.count_in_global_profiles):
            with self.subTest(command=command.name):
                self.assertIsNone(command.allowed_installs)
                self.assertIsNone(command.allowed_contexts)


if __name__ == "__main__":
    unittest.main()
