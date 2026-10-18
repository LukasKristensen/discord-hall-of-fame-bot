"""The daily rebuild behind leaderboards and profiles, against a real PostgreSQL database.

rebuild_user_stats_for_guild counts and ranks every member of a server in one statement. The numbers
here were worked out by hand from the posts below, so a change to the counting, the ranking, the
monthly window or the tie-breaking shows up as a wrong number.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import unittest

from repositories import hall_of_fame_message_repo, server_config_repo, server_user_repo

from tests.integration.database import DatabaseTestCase, skip_without_database

GUILD = 9001
OTHER_GUILD = 9002
UNCONFIGURED_GUILD = 9003
# Ties are broken by user ID, lowest first, so the order of these IDs matters
ALICE, BOB, CAROL, DAVE = 101, 102, 103, 104

WINDOW_START = datetime.datetime(2026, 9, 18, 0, 0)
IN_WINDOW = datetime.datetime(2026, 10, 1, 12, 0)
BEFORE_WINDOW = datetime.datetime(2026, 8, 1, 12, 0)

# (author, reactions, created_at)
POSTS = [
    (ALICE, 5, IN_WINDOW), (ALICE, 6, IN_WINDOW), (ALICE, 7, IN_WINDOW), (ALICE, 10, BEFORE_WINDOW),
    (BOB, 1, BEFORE_WINDOW), (BOB, 1, BEFORE_WINDOW), (BOB, 1, BEFORE_WINDOW), (BOB, 1, BEFORE_WINDOW),
    (CAROL, 20, IN_WINDOW), (CAROL, 1, IN_WINDOW), (CAROL, 1, BEFORE_WINDOW), (CAROL, 1, BEFORE_WINDOW),
    (DAVE, 30, IN_WINDOW),
    # Posts without an author, which must never reach a leaderboard however many there are
    (hall_of_fame_message_repo.NO_AUTHOR_ID, 99, IN_WINDOW), (hall_of_fame_message_repo.NO_AUTHOR_ID, 99, IN_WINDOW),
]

# user: (total posts, total reactions, posts this month, reactions this month)
EXPECTED_COUNTS = {
    ALICE: (4, 28, 3, 18),
    BOB: (4, 4, 0, 0),
    CAROL: (4, 23, 2, 21),
    DAVE: (1, 30, 1, 30),
}
# user: (total_message_rank, total_reaction_rank, monthly_message_rank, monthly_reaction_rank)
EXPECTED_RANKS = {
    ALICE: (1, 2, 1, 3),
    BOB: (2, 4, None, None),
    CAROL: (3, 3, 2, 2),
    DAVE: (4, 1, 3, 1),
}


@skip_without_database
class StatisticsRebuildTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        for guild in (GUILD, OTHER_GUILD):
            server_config_repo.insert_server_config(self.connection, guild)
        self.next_message_id = 1
        for author, reactions, created_at in POSTS:
            self.post(author, reactions, created_at)
        # Another server's posts by the same members, which must not leak into this server's numbers
        self.post(ALICE, 50, IN_WINDOW, guild=OTHER_GUILD)
        self.post(BOB, 50, IN_WINDOW, guild=OTHER_GUILD)

    def post(self, author, reactions, created_at, guild=GUILD):
        message_id = self.next_message_id
        self.next_message_id += 1
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, message_id, 500, guild, message_id + 5000, reactions, author, created_at)

    def rebuild(self, guild=GUILD):
        return server_user_repo.rebuild_user_stats_for_guild(self.connection, guild, WINDOW_START)

    def stats(self, guild=GUILD):
        return {row[0]: row[1:] for row in self.rows(
            "SELECT user_id, total_hall_of_fame_messages, total_hall_of_fame_message_reactions, "
            "this_month_hall_of_fame_messages, this_month_hall_of_fame_message_reactions "
            "FROM server_user WHERE guild_id = %s", (guild,))}

    def ranks(self, guild=GUILD):
        return {row[0]: row[1:] for row in self.rows(
            "SELECT user_id, total_message_rank, total_reaction_rank, monthly_message_rank, monthly_reaction_rank "
            "FROM server_user WHERE guild_id = %s", (guild,))}

    def test_counts_each_members_posts_and_reactions(self):
        self.rebuild()

        self.assertEqual(EXPECTED_COUNTS, self.stats())

    def test_ranks_each_member(self):
        self.rebuild()

        self.assertEqual(EXPECTED_RANKS, self.ranks())

    def test_breaks_ties_by_user_id(self):
        """Alice, Bob and Carol all have four posts, so their order comes from their IDs."""
        self.rebuild()
        ranks = self.ranks()

        self.assertEqual([1, 2, 3], [ranks[user][0] for user in (ALICE, BOB, CAROL)])

    def test_every_rank_is_given_once(self):
        self.rebuild()

        for column in range(4):
            with self.subTest(column=column):
                given = [rank[column] for rank in self.ranks().values() if rank[column] is not None]
                self.assertEqual(sorted(given), list(range(1, len(given) + 1)))

    def test_a_member_with_nothing_this_month_has_no_monthly_rank(self):
        self.rebuild()

        self.assertEqual((None, None), self.ranks()[BOB][2:])

    def test_leaves_out_posts_without_an_author(self):
        self.rebuild()

        self.assertNotIn(hall_of_fame_message_repo.NO_AUTHOR_ID, self.stats())

    def test_a_post_exactly_at_the_start_of_the_window_counts_this_month(self):
        self.post(BOB, 3, WINDOW_START)
        self.rebuild()

        self.assertEqual((5, 7, 1, 3), self.stats()[BOB])

    def test_a_post_just_before_the_window_only_counts_all_time(self):
        self.post(BOB, 3, WINDOW_START - datetime.timedelta(seconds=1))
        self.rebuild()

        self.assertEqual((5, 7, 0, 0), self.stats()[BOB])

    def test_only_counts_the_servers_own_posts(self):
        self.rebuild()
        self.rebuild(OTHER_GUILD)

        self.assertEqual({ALICE: (1, 50, 1, 50), BOB: (1, 50, 1, 50)}, self.stats(OTHER_GUILD))
        self.assertEqual(EXPECTED_COUNTS, self.stats())

    def test_reports_how_many_members_were_written(self):
        self.assertEqual(4, self.rebuild())

    def test_running_it_again_updates_rather_than_duplicates(self):
        self.rebuild()
        self.post(DAVE, 2, IN_WINDOW)
        self.rebuild()

        self.assertEqual((2, 32, 2, 32), self.stats()[DAVE])
        self.assertEqual([(4,)], self.rows("SELECT COUNT(*) FROM server_user WHERE guild_id = %s", (GUILD,)))

    def test_running_it_again_without_changes_changes_nothing(self):
        self.rebuild()
        once = self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id")
        self.rebuild()

        self.assertEqual(once, self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id"))

    def test_a_server_without_a_configuration_gets_no_statistics(self):
        """The bot has left it, or never set it up, so there is nobody to show a leaderboard to."""
        self.post(ALICE, 5, IN_WINDOW, guild=UNCONFIGURED_GUILD)

        self.assertEqual(0, self.rebuild(UNCONFIGURED_GUILD))
        self.assertEqual({}, self.stats(UNCONFIGURED_GUILD))

    def test_a_quiet_month_leaves_everyone_unranked_for_the_month(self):
        self.rebuild()
        later_window = datetime.datetime(2027, 1, 1)
        server_user_repo.rebuild_user_stats_for_guild(self.connection, GUILD, later_window)

        for user, ranks in self.ranks().items():
            with self.subTest(user=user):
                self.assertEqual((None, None), ranks[2:])
        self.assertTrue(all(counts[2:] == (0, 0) for counts in self.stats().values()))


if __name__ == "__main__":
    unittest.main()
