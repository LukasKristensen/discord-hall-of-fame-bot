"""Removing the bot from a server, against a real PostgreSQL database.

The privacy policy promises that removing the bot deletes that server's posts, member statistics,
Wrapped data and settings straight away, keeps only anonymous join and leave dates and member counts,
and leaves every other server exactly as it was. These tests check that on real rows, with the same
world of servers and members as the member deletion tests.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import copy
import types
import unittest

import events
import utils
from repositories import global_profile_repo, opt_out_repo, server_user_repo

from tests.integration.test_member_data_deletion import (
    DELETED, GUILDS, OPTED_OUT_SERVER, OTHER, SECOND, SHARED, THIRD, MemberDataDeletionTestCase, in_order,
)

# Tables whose rows for a server are deleted when the bot is removed from it
DELETED_WITH_THE_SERVER = {"hall_of_fame_message", "server_user", "server_configs", "hof_wrapped",
                           "hof_wrapped_progress"}
# Tables with a guild_id that are kept on purpose: anonymous statistics about servers, not members
KEPT_AS_ANONYMOUS_STATISTICS = {"guild_lifecycle_event", "guild_monthly_snapshot"}


class ServerRemovalTests(MemberDataDeletionTestCase):
    @staticmethod
    def expected_after_removing(before, guild_id):
        expected = copy.deepcopy(before)
        for table in DELETED_WITH_THE_SERVER:
            expected[table] = [row for row in expected[table] if row["guild_id"] != guild_id]
        return {table: in_order(rows) for table, rows in expected.items()}

    def assert_only_the_server_changed(self, before, guild_id):
        expected = self.expected_after_removing(before, guild_id)
        after = self.snapshot()
        self.assertEqual(set(expected), set(after))
        for table in expected:
            with self.subTest(table=table):
                self.assertEqual(expected[table], after[table])

    async def test_only_the_server_changes(self):
        """Every row of the server goes, and every row of every other server is exactly as it was."""
        before = self.snapshot()
        utils.delete_database_context(SHARED, self.connection)

        self.assert_only_the_server_changed(before, SHARED)

    async def test_removing_each_server_in_turn_leaves_the_others_alone(self):
        for guild_id in GUILDS:
            with self.subTest(guild_id=guild_id):
                before = self.snapshot()
                utils.delete_database_context(guild_id, self.connection)
                self.assert_only_the_server_changed(before, guild_id)

    async def test_the_remove_event_deletes_the_same_way(self):
        before = self.snapshot()
        await events.guild_remove(types.SimpleNamespace(id=SECOND), self.connection)

        self.assert_only_the_server_changed(before, SECOND)

    async def test_nothing_of_the_server_is_left_in_the_tables_it_is_deleted_from(self):
        utils.delete_database_context(SHARED, self.connection)

        for table in DELETED_WITH_THE_SERVER:
            with self.subTest(table=table):
                self.assertEqual([(0,)], self.rows(f"SELECT COUNT(*) FROM {table} WHERE guild_id = %s", (SHARED,)))

    async def test_keeps_the_anonymous_server_statistics(self):
        before = {table: self.rows(f"SELECT * FROM {table} ORDER BY 1, 2") for table in KEPT_AS_ANONYMOUS_STATISTICS}
        utils.delete_database_context(SHARED, self.connection)

        for table in KEPT_AS_ANONYMOUS_STATISTICS:
            with self.subTest(table=table):
                self.assertEqual(before[table], self.rows(f"SELECT * FROM {table} ORDER BY 1, 2"))

    async def test_members_keep_their_privacy_and_counting_choices(self):
        """Those belong to the member, not to any one server."""
        utils.delete_database_context(SHARED, self.connection)

        self.assertTrue(global_profile_repo.is_hidden(self.connection, DELETED))
        self.assertTrue(global_profile_repo.is_hidden(self.connection, OTHER))
        self.assertTrue(opt_out_repo.is_opted_out(self.connection, THIRD))

    async def test_members_keep_their_standing_in_other_servers(self):
        before = server_user_repo.get_server_users_for_user(self.connection, OTHER)
        utils.delete_database_context(SHARED, self.connection)

        self.assertEqual([row for row in before if row["guild_id"] != SHARED],
                         server_user_repo.get_server_users_for_user(self.connection, OTHER))

    async def test_the_removed_server_leaves_the_totals_across_servers(self):
        before = global_profile_repo.get_global_profile(self.connection, OTHER)
        utils.delete_database_context(SHARED, self.connection)
        after = global_profile_repo.get_global_profile(self.connection, OTHER)

        self.assertEqual(before["servers"] - 1, after["servers"])
        self.assertEqual(before["posts"] - 2, after["posts"])

    async def test_removing_a_server_that_was_never_set_up_changes_nothing(self):
        before = self.snapshot()
        utils.delete_database_context(424242, self.connection)

        self.assertEqual(before, self.snapshot())

    async def test_removing_twice_changes_nothing_more(self):
        utils.delete_database_context(OPTED_OUT_SERVER, self.connection)
        once = self.snapshot()
        utils.delete_database_context(OPTED_OUT_SERVER, self.connection)

        self.assertEqual(once, self.snapshot())

    async def test_the_daily_rebuild_does_not_bring_the_server_back(self):
        utils.delete_database_context(SHARED, self.connection)
        self.rebuild_all()

        self.assertEqual([(0,)], self.rows("SELECT COUNT(*) FROM server_user WHERE guild_id = %s", (SHARED,)))

    def test_every_table_with_a_server_id_is_either_deleted_or_kept_on_purpose(self):
        """
        A new table with a guild_id column holds server data, so removing the bot has to delete it or
        it has to be listed as kept on purpose here, and the privacy policy has to say which.
        """
        found = {row[0] for row in self.rows(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE table_schema = %s AND column_name = 'guild_id'", (self.schema,))}

        self.assertEqual(DELETED_WITH_THE_SERVER | KEPT_AS_ANONYMOUS_STATISTICS, found)


if __name__ == "__main__":
    unittest.main()
