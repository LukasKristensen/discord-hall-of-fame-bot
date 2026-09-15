"""Tests for the per-member statistics table behind /user_profile and /leaderboard.

The nightly rebuild of this table is covered in ``test_user_stats``. What is covered here is
everything the commands do with it afterwards: reading one member's row back by name, and the two
queries that take a column name from the caller and so decide for themselves what is allowed.
"""

import unittest

from repositories import server_user_repo

from tests.fakes import FakeConnection

USER_COLUMNS = ["user_id", "guild_id", "monthly_reaction_rank", "total_message_rank",
                "total_reaction_rank", "this_month_hall_of_fame_messages",
                "total_hall_of_fame_messages", "monthly_message_rank",
                "this_month_hall_of_fame_message_reactions", "total_hall_of_fame_message_reactions"]

USER_ROW = (77, 200, 3, 1, 2, 4, 40, 5, 60, 600)

USER_STATS = {
    "monthly_reaction_rank": 3,
    "total_message_rank": 1,
    "total_reaction_rank": 2,
    "this_month_hall_of_fame_messages": 4,
    "total_hall_of_fame_messages": 40,
    "monthly_message_rank": 5,
    "this_month_hall_of_fame_message_reactions": 60,
    "total_hall_of_fame_message_reactions": 600,
}


class GetServerUserTests(unittest.TestCase):
    def test_maps_the_row_to_its_column_names(self):
        connection = FakeConnection(row=USER_ROW, description=USER_COLUMNS)
        user = server_user_repo.get_server_user(connection, 77, 200)

        self.assertEqual(40, user["total_hall_of_fame_messages"])
        self.assertEqual(1, user["total_message_rank"])
        self.assertEqual(600, user["total_hall_of_fame_message_reactions"])

    def test_returns_nothing_for_a_member_with_no_hall_of_fame_history(self):
        connection = FakeConnection(row=None, description=USER_COLUMNS)
        self.assertIsNone(server_user_repo.get_server_user(connection, 77, 200))

    def test_reads_one_member_in_one_guild(self):
        """The primary key is the pair, so a member has separate standings per server."""
        connection = FakeConnection(row=USER_ROW, description=USER_COLUMNS)
        server_user_repo.get_server_user(connection, 77, 200)

        self.assertEqual([(77, 200)], connection.parameters)

    def test_closes_the_cursor_when_a_member_is_found(self):
        connection = FakeConnection(row=USER_ROW, description=USER_COLUMNS)
        server_user_repo.get_server_user(connection, 77, 200)

        self.assertTrue(all(cursor.closed for cursor in connection.cursors))

    def test_closes_the_cursor_when_no_member_is_found(self):
        connection = FakeConnection(row=None, description=USER_COLUMNS)
        server_user_repo.get_server_user(connection, 77, 200)

        self.assertTrue(all(cursor.closed for cursor in connection.cursors))


class TopUsersByStatTests(unittest.TestCase):
    def test_rejects_a_statistic_it_does_not_know(self):
        with self.assertRaises(ValueError):
            server_user_repo.get_top_users_by_stat(
                FakeConnection(), 200, "total_hall_of_fame_messages; DROP TABLE server_user")

    def test_rejects_a_column_that_is_not_a_statistic(self):
        with self.assertRaises(ValueError):
            server_user_repo.get_top_users_by_stat(FakeConnection(), 200, "user_id")

    def test_accepts_every_statistic_the_commands_rank_by(self):
        for stat in server_user_repo.ALLOWED_STAT_FIELDS:
            with self.subTest(stat=stat):
                connection = FakeConnection(rows=[], description=["user_id", "guild_id", stat])
                server_user_repo.get_top_users_by_stat(connection, 200, stat)

    def test_ranks_by_the_statistic_it_was_given(self):
        connection = FakeConnection(rows=[], description=["user_id", "guild_id", "total_hall_of_fame_messages"])
        server_user_repo.get_top_users_by_stat(connection, 200, "total_hall_of_fame_messages")

        self.assertIn("ORDER BY total_hall_of_fame_messages DESC", connection.queries[0])

    def test_maps_every_row(self):
        connection = FakeConnection(rows=[(77, 200, 40), (88, 200, 12)],
                                    description=["user_id", "guild_id", "total_hall_of_fame_messages"])
        top = server_user_repo.get_top_users_by_stat(connection, 200, "total_hall_of_fame_messages")

        self.assertEqual([77, 88], [user["user_id"] for user in top])

    def test_passes_the_guild_and_the_limit_as_parameters(self):
        connection = FakeConnection(rows=[], description=["user_id", "guild_id", "total_hall_of_fame_messages"])
        server_user_repo.get_top_users_by_stat(connection, 200, "total_hall_of_fame_messages", limit=5)

        self.assertEqual([(200, 5)], connection.parameters)


class CheckIfUserIsTopOfStatTests(unittest.TestCase):
    def test_rejects_a_statistic_it_does_not_know(self):
        with self.assertRaises(ValueError):
            server_user_repo.check_if_user_is_top_of_stat(FakeConnection(), 77, 200, "1; DELETE FROM server_user")

    def test_confirms_the_member_holding_the_top_place(self):
        connection = FakeConnection(row=(77,))
        self.assertTrue(server_user_repo.check_if_user_is_top_of_stat(
            connection, 77, 200, "total_hall_of_fame_messages"))

    def test_denies_a_member_who_is_not_first(self):
        connection = FakeConnection(row=(88,))
        self.assertFalse(server_user_repo.check_if_user_is_top_of_stat(
            connection, 77, 200, "total_hall_of_fame_messages"))

    def test_denies_everyone_in_a_guild_with_no_standings_yet(self):
        connection = FakeConnection(row=None)
        self.assertFalse(server_user_repo.check_if_user_is_top_of_stat(
            connection, 77, 200, "total_hall_of_fame_messages"))


class UpdateUserStatsTests(unittest.TestCase):
    def test_writes_every_statistic_in_the_order_the_columns_are_listed(self):
        connection = FakeConnection()
        server_user_repo.update_user_stats(connection, USER_STATS, 77, 200)

        self.assertEqual((77, 200, 3, 1, 2, 4, 40, 5, 60, 600), connection.parameters[0])

    def test_updates_a_member_who_already_has_standings(self):
        connection = FakeConnection()
        server_user_repo.update_user_stats(connection, USER_STATS, 77, 200)

        self.assertIn("ON CONFLICT(user_id, guild_id) DO UPDATE", connection.queries[0])

    def test_commits(self):
        connection = FakeConnection()
        server_user_repo.update_user_stats(connection, USER_STATS, 77, 200)

        self.assertEqual(1, connection.commits)


class DeleteServerUsersTests(unittest.TestCase):
    def test_removes_the_standings_of_one_guild_only(self):
        connection = FakeConnection()
        server_user_repo.delete_server_users(connection, 200)

        self.assertIn("WHERE guild_id = %s", connection.queries[0])
        self.assertEqual([(200,)], connection.parameters)


if __name__ == "__main__":
    unittest.main()
