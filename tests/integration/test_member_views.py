"""What members see about each other, against a real PostgreSQL database.

The leaderboard, the champion titles, the profile highlights and the totals across servers are all
read straight from the database. These tests check them on real rows against numbers worked out by
hand, including ties, members with nothing this month, and servers that opted out.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import unittest

import commands
from repositories import global_profile_repo, hall_of_fame_message_repo, server_config_repo, server_user_repo

from tests.integration.database import DatabaseTestCase, skip_without_database

FIRST, SECOND, OPTED_OUT = 9001, 9002, 9003
ALICE, BOB, CAROL = 101, 102, 103

WINDOW_START = datetime.datetime(2026, 9, 18)
SEPTEMBER = datetime.datetime(2026, 9, 10, 12, 0)
OCTOBER = datetime.datetime(2026, 10, 5, 12, 0)

# (message_id, guild, author, reactions, created_at)
POSTS = [
    (1, FIRST, ALICE, 5, SEPTEMBER), (2, FIRST, ALICE, 6, SEPTEMBER), (3, FIRST, ALICE, 7, OCTOBER),
    (4, FIRST, BOB, 2, OCTOBER), (5, FIRST, BOB, 2, OCTOBER), (6, FIRST, BOB, 2, OCTOBER), (7, FIRST, BOB, 2, SEPTEMBER),
    (8, FIRST, CAROL, 9, OCTOBER),
    (9, SECOND, ALICE, 10, OCTOBER), (10, SECOND, ALICE, 1, OCTOBER),
    # Alice's posts in a server that opted out of the totals across servers
    (11, OPTED_OUT, ALICE, 40, OCTOBER), (12, OPTED_OUT, ALICE, 40, OCTOBER),
    (13, OPTED_OUT, ALICE, 40, OCTOBER), (14, OPTED_OUT, ALICE, 40, OCTOBER),
]


@skip_without_database
class MemberViewsTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        for guild in (FIRST, SECOND, OPTED_OUT):
            server_config_repo.insert_server_config(self.connection, guild)
        server_config_repo.update_server_config_param(OPTED_OUT, "count_in_global_profiles", False, self.connection)
        for message_id, guild, author, reactions, created_at in POSTS:
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, message_id, 500 + guild, guild, message_id + 5000, reactions, author, created_at)
        self.rebuild()

    def rebuild(self):
        for guild in (FIRST, SECOND, OPTED_OUT):
            server_user_repo.rebuild_user_stats_for_guild(self.connection, guild, WINDOW_START)


class LeaderboardTests(MemberViewsTestCase):
    def top(self, stat, limit=5, guild=FIRST):
        return [(row["user_id"], row[stat]) for row in
                server_user_repo.get_top_users_by_stat(self.connection, guild, stat, limit=limit)]

    def test_all_time_posts(self):
        self.assertEqual([(BOB, 4), (ALICE, 3), (CAROL, 1)], self.top("total_hall_of_fame_messages"))

    def test_all_time_reactions(self):
        self.assertEqual([(ALICE, 18), (CAROL, 9), (BOB, 8)], self.top("total_hall_of_fame_message_reactions"))

    def test_this_month_leaves_out_members_with_nothing_this_month(self):
        """Only posts from WINDOW_START count, so September's are left out."""
        self.assertEqual([(BOB, 3), (ALICE, 1), (CAROL, 1)], self.top("this_month_hall_of_fame_messages"))

    def test_respects_the_limit(self):
        self.assertEqual([(BOB, 4)], self.top("total_hall_of_fame_messages", limit=1))

    def test_ranks_are_read_best_first(self):
        self.assertEqual([(BOB, 1), (ALICE, 2), (CAROL, 3)], self.top("total_message_rank"))

    def test_only_shows_the_servers_own_members(self):
        self.assertEqual([(ALICE, 2)], self.top("total_hall_of_fame_messages", guild=SECOND))

    def test_refuses_a_column_that_is_not_a_statistic(self):
        with self.assertRaises(ValueError):
            server_user_repo.get_top_users_by_stat(self.connection, FIRST, "user_id; DROP TABLE server_user", limit=5)


class ChampionTests(MemberViewsTestCase):
    def is_top(self, user, stat, guild=FIRST):
        return server_user_repo.check_if_user_is_top_of_stat(self.connection, user, guild, stat)

    def test_crowns_the_member_with_the_most_posts(self):
        self.assertTrue(self.is_top(BOB, "total_hall_of_fame_messages"))
        self.assertFalse(self.is_top(ALICE, "total_hall_of_fame_messages"))

    def test_crowns_nobody_in_a_month_without_posts(self):
        server_user_repo.rebuild_user_stats_for_guild(self.connection, FIRST, datetime.datetime(2027, 1, 1))

        for user in (ALICE, BOB, CAROL):
            with self.subTest(user=user):
                self.assertFalse(self.is_top(user, "this_month_hall_of_fame_messages"))

    def add_tied_members(self):
        """
        Twenty members tied on 50 posts this month, stored highest ID first. The rebuild ranks ties by
        user ID, lowest first, so 301 is ranked first; anything that does not break ties the same way
        comes back in storage order instead
        """
        tied = list(range(301, 321))
        for user in reversed(tied):
            self.execute("INSERT INTO server_user (user_id, guild_id, this_month_hall_of_fame_messages, "
                         "total_hall_of_fame_messages) VALUES (%s, %s, 50, 50)", (user, FIRST))
        return tied

    def test_a_tie_crowns_the_member_ranked_first(self):
        """Otherwise a profile could crown a member the leaderboard ranks below someone else."""
        tied = self.add_tied_members()
        stat = "this_month_hall_of_fame_messages"

        self.assertTrue(self.is_top(tied[0], stat))
        self.assertFalse(any(self.is_top(user, stat) for user in tied[1:]))

    def test_the_leaderboard_lists_a_tie_in_rank_order(self):
        tied = self.add_tied_members()
        top = server_user_repo.get_top_users_by_stat(self.connection, FIRST, "this_month_hall_of_fame_messages", 10)

        self.assertEqual(tied[:10], [row["user_id"] for row in top])


class RankGapTests(MemberViewsTestCase):
    def gap(self, user, guild=FIRST):
        stats = server_user_repo.get_server_user(self.connection, user, guild)
        return commands.rank_gap_line(stats, lambda stat, rank_field, rank: server_user_repo.get_stat_at_rank(
            self.connection, guild, stat, rank_field, rank))

    def test_reads_the_count_held_at_a_rank(self):
        self.assertEqual(3, server_user_repo.get_stat_at_rank(
            self.connection, FIRST, "this_month_hall_of_fame_messages", "monthly_message_rank", 1))
        self.assertIsNone(server_user_repo.get_stat_at_rank(
            self.connection, FIRST, "this_month_hall_of_fame_messages", "monthly_message_rank", 9))

    def test_the_leader_this_month(self):
        self.assertEqual("🎯 Leading this month by 2 posts", self.gap(BOB))

    def test_a_member_behind_this_month(self):
        self.assertEqual("🎯 2 posts behind #1 this month", self.gap(ALICE))

    def test_a_member_level_with_the_place_above(self):
        """Alice and Carol both have one post this month; Carol is ranked below Alice by ID."""
        self.assertEqual("🎯 Level with #2 this month", self.gap(CAROL))

    def test_the_only_member_of_a_server_has_nobody_to_compare_with(self):
        self.assertIsNone(self.gap(ALICE, guild=SECOND))

    def test_refuses_a_column_that_is_not_a_statistic(self):
        with self.assertRaises(ValueError):
            server_user_repo.get_stat_at_rank(self.connection, FIRST, "user_id", "monthly_message_rank", 1)


class HighlightsTests(MemberViewsTestCase):
    def test_best_post_and_last_featured(self):
        highlights = hall_of_fame_message_repo.get_member_highlights(self.connection, FIRST, ALICE)

        self.assertEqual({"channel_id": 500 + FIRST, "message_id": 3, "reaction_count": 7}, highlights["best_post"])
        self.assertEqual(OCTOBER, highlights["last_featured"])

    def test_a_tie_for_best_post_goes_to_the_newest(self):
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, 20, 500 + FIRST, FIRST, 5020, 7, ALICE, OCTOBER + datetime.timedelta(days=1))

        best = hall_of_fame_message_repo.get_member_highlights(self.connection, FIRST, ALICE)["best_post"]
        self.assertEqual(20, best["message_id"])

    def test_only_looks_at_this_server(self):
        """Alice's 40-reaction posts are in another server and must not be her best post here."""
        best = hall_of_fame_message_repo.get_member_highlights(self.connection, FIRST, ALICE)["best_post"]

        self.assertEqual(7, best["reaction_count"])

    def test_nothing_for_a_member_never_featured_here(self):
        self.assertEqual({"best_post": None, "last_featured": None},
                         hall_of_fame_message_repo.get_member_highlights(self.connection, SECOND, BOB))


class TotalsAcrossServersTests(MemberViewsTestCase):
    def profile(self, user):
        return global_profile_repo.get_global_profile(self.connection, user)

    def test_adds_up_every_server_that_counts(self):
        """Alice: three posts in FIRST and two in SECOND; her four in OPTED_OUT do not count."""
        self.assertEqual({"posts": 5, "reactions": 29, "servers": 2, "biggest_post": 10, "best_month": 3,
                          "top_of_board": 1}, self.profile(ALICE))

    def test_a_member_in_one_server(self):
        self.assertEqual({"posts": 4, "reactions": 8, "servers": 1, "biggest_post": 2, "best_month": 3,
                          "top_of_board": 1}, self.profile(BOB))

    def test_a_member_never_featured(self):
        self.assertEqual({field: 0 for field in global_profile_repo.PROFILE_FIELDS}, self.profile(999))

    def test_opting_a_server_out_takes_effect_at_once(self):
        server_config_repo.update_server_config_param(SECOND, "count_in_global_profiles", False, self.connection)

        self.assertEqual(3, self.profile(ALICE)["posts"])
        self.assertEqual(1, self.profile(ALICE)["servers"])

    def test_opting_back_in_counts_the_server_again(self):
        server_config_repo.update_server_config_param(OPTED_OUT, "count_in_global_profiles", True, self.connection)

        self.assertEqual(9, self.profile(ALICE)["posts"])
        self.assertEqual(3, self.profile(ALICE)["servers"])

    def test_a_server_from_before_the_setting_counts(self):
        """Rows written before the column existed hold NULL, which counts as switched on."""
        self.execute("UPDATE server_configs SET count_in_global_profiles = NULL WHERE guild_id = %s", (SECOND,))

        self.assertEqual(2, self.profile(ALICE)["servers"])

    def test_the_totals_match_the_profiles_in_each_server(self):
        """Without opted-out servers, the totals are the sum of the member's profile in each server."""
        per_server = [row for row in server_user_repo.get_server_users_for_user(self.connection, ALICE)
                      if row["guild_id"] != OPTED_OUT]

        profile = self.profile(ALICE)
        self.assertEqual(sum(row["total_hall_of_fame_messages"] for row in per_server), profile["posts"])
        self.assertEqual(sum(row["total_hall_of_fame_message_reactions"] for row in per_server), profile["reactions"])


if __name__ == "__main__":
    unittest.main()
