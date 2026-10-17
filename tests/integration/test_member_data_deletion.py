"""/delete_my_data against a real PostgreSQL database.

Deleting someone's data is the one thing the bot does that cannot be undone, and the promise in the
privacy policy is twofold: everything about the member goes, and nothing else changes. These tests
check both halves on real rows. Each one builds the same small world of servers and members, takes a
snapshot of every table, runs the deletion through the bot's own code, and compares the snapshot
afterwards with what should have changed, so a statement that touches one row too many fails here.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import copy
import datetime
import json
import types
import unittest
from unittest import mock

import main
import utils
from repositories import (
    global_profile_repo,
    hall_of_fame_message_repo,
    hof_wrapped_repo,
    opt_out_repo,
    server_user_repo,
)

from tests.integration.database import DatabaseTestCase, SingleConnectionPool, skip_without_database

# Members, as Discord snowflakes. FAN's ID begins with every digit of DELETED's, so a removal that
# matched IDs as text without their quotes would take FAN out of the fan lists too
DELETED = 111111111111111111
FAN = 1111111111111111111
OTHER = 222222222222222222
THIRD = 333333333333333333
NOBODY = 999999999999999999

# Servers. OPTED_OUT_SERVER has switched off counting toward totals across servers
SHARED, SECOND, OTHERS_ONLY, OPTED_OUT_SERVER = 9001, 9002, 9003, 9004
GUILDS = (SHARED, SECOND, OTHERS_ONLY, OPTED_OUT_SERVER)

# Every table that holds a member's user ID, and so has to be handled by /delete_my_data
TABLES_WITH_MEMBER_IDS = {"hall_of_fame_message", "server_user", "hof_wrapped", "hidden_global_profile",
                          "opted_out_member"}
# Text columns of hof_wrapped that hold JSON, compared parsed so formatting does not matter
WRAPPED_JSON_COLUMNS = ("most_used_channels", "most_used_emojis", "fan_of_users", "users_fans", "user_ranks")

NOW = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def days_ago(days):
    return NOW - datetime.timedelta(days=days)


def in_order(rows):
    """Rows in a fixed order, so two snapshots of the same table compare equal"""
    return sorted(rows, key=lambda record: json.dumps(record, sort_keys=True, default=str))


# (message_id, guild, channel, reactions, author, created_at). Message IDs are unique across the table
POSTS = [
    (1, SHARED, 501, 9, DELETED, days_ago(2)),
    (2, SHARED, 501, 4, DELETED, days_ago(40)),
    (3, SHARED, 502, 12, DELETED, days_ago(5)),
    (4, SECOND, 601, 3, DELETED, days_ago(1)),
    (5, SECOND, 601, 7, DELETED, days_ago(100)),
    (6, OPTED_OUT_SERVER, 801, 5, DELETED, days_ago(3)),
    (10, SHARED, 501, 6, OTHER, days_ago(4)),
    (11, SHARED, 502, 8, OTHER, days_ago(60)),
    (12, SECOND, 601, 2, OTHER, days_ago(2)),
    (13, OTHERS_ONLY, 701, 15, OTHER, days_ago(7)),
    (14, OTHERS_ONLY, 701, 3, OTHER, days_ago(8)),
    (20, SHARED, 501, 5, THIRD, days_ago(6)),
    (21, SHARED, 502, 4, FAN, days_ago(9)),
    # A post migrated without an author, which the stats rebuild has always skipped
    (30, SHARED, 501, 10, hall_of_fame_message_repo.NO_AUTHOR_ID, days_ago(400)),
]


@skip_without_database
class MemberDataDeletionTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.logged = []

        async def record_log(_bot, message, *args, **kwargs):
            self.logged.append(str(message))

        for target, name, replacement in ((utils, "logging", record_log),
                                          (main, "connection_pool", SingleConnectionPool(self.connection))):
            patcher = mock.patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self):
        for guild in GUILDS:
            self.execute("INSERT INTO server_configs (guild_id, hall_of_fame_channel_id, server_member_count, "
                         "count_in_global_profiles) VALUES (%s, %s, %s, %s)",
                         (guild, guild * 10, 50, guild != OPTED_OUT_SERVER))
            self.execute("INSERT INTO guild_lifecycle_event (guild_id, event_type, occurred_at) VALUES (%s, 'JOIN', %s)",
                         (guild, datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)))
            self.execute("INSERT INTO guild_monthly_snapshot (guild_id, month_start, member_count, message_count, "
                         "captured_at) VALUES (%s, '2026-09-01', 50, 3, now())", (guild,))
            self.execute("INSERT INTO hof_wrapped_progress (guild_id, year, is_complete, hall_of_fame_message_count) "
                         "VALUES (%s, 2025, TRUE, 4)", (guild,))

        for message_id, guild, channel, reactions, author, created_at in POSTS:
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, message_id, channel, guild, message_id + 5000, reactions, author, created_at)

        self.rebuild_all()

        def fans(entries):
            return json.dumps({str(user_id): count for user_id, count in entries})

        wrapped = [
            # (guild, user, fan_of_users, users_fans)
            (SHARED, DELETED, fans([(OTHER, 2), (THIRD, 1)]), fans([(OTHER, 5), (FAN, 1)])),
            (SECOND, DELETED, fans([(OTHER, 1)]), fans([(OTHER, 3)])),
            (SHARED, OTHER, fans([(DELETED, 5), (FAN, 4), (THIRD, 2)]), fans([(DELETED, 2), (THIRD, 7)])),
            (SECOND, OTHER, fans([(DELETED, 3)]), fans([(DELETED, 1)])),
            (SHARED, THIRD, fans([(DELETED, 1)]), fans([(OTHER, 2)])),
            (SHARED, FAN, fans([(DELETED, 1), (OTHER, 1)]), fans([(OTHER, 4)])),
            (OTHERS_ONLY, OTHER, "{}", "{}"),
        ]
        for guild, user, fan_of_users, users_fans in wrapped:
            hof_wrapped_repo.insert_hof_wrapped(
                self.connection, guild, user, 2025, 10, 3, json.dumps({"501": 2}), json.dumps({"🔥": 4}),
                1, 501, 9, fan_of_users, users_fans, json.dumps({"hallOfFameMessagePosts": 1}))
        # A row whose fan lists are empty in the database, as rows from before the feature are
        self.execute("INSERT INTO hof_wrapped (guild_id, user_id, year) VALUES (%s, %s, 2024)", (SHARED, THIRD))

        global_profile_repo.set_hidden(self.connection, DELETED, True)
        global_profile_repo.set_hidden(self.connection, OTHER, True)
        opt_out_repo.set_opted_out(self.connection, THIRD, True)

    def rebuild_all(self):
        for guild in GUILDS:
            server_user_repo.rebuild_user_stats_for_guild(self.connection, guild, utils.monthly_window_start())

    def tables(self):
        return [row[0] for row in self.rows(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",
            (self.schema,))]

    def snapshot(self):
        """Every row of every table, comparable with ==, with JSON text parsed"""
        result = {}
        for table in self.tables():
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT * FROM {table}")
            columns = [description[0] for description in cursor.description]
            rows = []
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                if table == "hof_wrapped":
                    for column in WRAPPED_JSON_COLUMNS:
                        if record[column] is not None:
                            record[column] = json.loads(record[column])
                rows.append(record)
            cursor.close()
            result[table] = in_order(rows)
        self.connection.commit()
        return result

    @staticmethod
    def expected_after_deleting(before, user_id):
        """What every table should hold once user_id is deleted, worked out from the snapshot alone"""
        expected = copy.deepcopy(before)
        for post in expected["hall_of_fame_message"]:
            if post["author_id"] == user_id:
                post["author_id"] = hall_of_fame_message_repo.NO_AUTHOR_ID
        expected["server_user"] = [row for row in expected["server_user"] if row["user_id"] != user_id]
        expected["hof_wrapped"] = [row for row in expected["hof_wrapped"] if row["user_id"] != user_id]
        for row in expected["hof_wrapped"]:
            for column in ("fan_of_users", "users_fans"):
                if row[column] is not None:
                    row[column].pop(str(user_id), None)
        expected["hidden_global_profile"] = [row for row in expected["hidden_global_profile"]
                                             if row["user_id"] != user_id]
        # Changing a value can change where a row sorts, so the order is worked out again
        return {table: in_order(rows) for table, rows in expected.items()}

    def assert_only_the_member_changed(self, before, after, user_id, stop_counting):
        expected = self.expected_after_deleting(before, user_id)
        # The opt-out row carries the moment it was made, so it is checked on its own
        added = [row for row in after["opted_out_member"] if row["user_id"] == user_id]
        self.assertEqual(stop_counting, bool(added))
        after = dict(after, opted_out_member=[row for row in after["opted_out_member"] if row["user_id"] != user_id])
        expected["opted_out_member"] = [row for row in expected["opted_out_member"] if row["user_id"] != user_id]

        self.assertEqual(set(expected), set(after), "a table appeared or disappeared")
        for table in expected:
            with self.subTest(table=table):
                self.assertEqual(expected[table], after[table])

    def posts_by(self, user_id):
        return self.rows("SELECT message_id FROM hall_of_fame_message WHERE author_id = %s ORDER BY message_id",
                         (user_id,))


class DeletionTests(MemberDataDeletionTestCase):
    async def test_only_the_member_changes(self):
        """The core promise: every row about the member goes, and every other row is exactly as it was."""
        before = self.snapshot()
        await main.delete_member_data(DELETED)

        self.assert_only_the_member_changed(before, self.snapshot(), DELETED, stop_counting=False)

    async def test_only_the_member_changes_when_they_stop_being_counted(self):
        before = self.snapshot()
        await main.delete_member_data(DELETED, stop_counting=True)

        self.assert_only_the_member_changed(before, self.snapshot(), DELETED, stop_counting=True)

    async def test_deleting_another_member_leaves_this_one_alone(self):
        """The same check from the other side, so the result does not depend on who is deleted."""
        before = self.snapshot()
        await main.delete_member_data(OTHER)

        self.assert_only_the_member_changed(before, self.snapshot(), OTHER, stop_counting=False)

    async def test_detaches_every_post_by_the_member(self):
        await main.delete_member_data(DELETED)

        self.assertEqual([], self.posts_by(DELETED))

    async def test_reports_how_many_posts_were_detached(self):
        detached = await main.delete_member_data(DELETED)

        self.assertEqual(sum(1 for post in POSTS if post[4] == DELETED), detached)

    async def test_the_posts_stay_on_the_boards(self):
        """The reposts belong to the servers, so the rows that point at them are kept, just without an author."""
        before = self.rows("SELECT message_id, guild_id, channel_id, hall_of_fame_message_id, reaction_count, "
                           "created_at FROM hall_of_fame_message ORDER BY message_id")
        await main.delete_member_data(DELETED)
        after = self.rows("SELECT message_id, guild_id, channel_id, hall_of_fame_message_id, reaction_count, "
                          "created_at FROM hall_of_fame_message ORDER BY message_id")

        self.assertEqual(before, after)

    async def test_other_members_keep_their_posts(self):
        for user_id in (OTHER, THIRD, FAN):
            with self.subTest(user_id=user_id):
                before = self.posts_by(user_id)
                await main.delete_member_data(DELETED)
                self.assertEqual(before, self.posts_by(user_id))

    async def test_posts_that_never_had_an_author_are_untouched(self):
        before = self.rows("SELECT message_id FROM hall_of_fame_message WHERE author_id = 0 ORDER BY message_id")
        await main.delete_member_data(DELETED)
        after = self.rows("SELECT message_id FROM hall_of_fame_message WHERE author_id = 0 ORDER BY message_id")

        deleted_posts = [(post[0],) for post in POSTS if post[4] == DELETED]
        self.assertEqual(sorted(before + deleted_posts), after)

    async def test_deletes_the_members_statistics_in_every_server(self):
        await main.delete_member_data(DELETED)

        self.assertEqual([], server_user_repo.get_server_users_for_user(self.connection, DELETED))

    async def test_other_members_keep_their_statistics(self):
        before = self.rows("SELECT * FROM server_user WHERE user_id <> %s ORDER BY user_id, guild_id", (DELETED,))
        await main.delete_member_data(DELETED)
        after = self.rows("SELECT * FROM server_user WHERE user_id <> %s ORDER BY user_id, guild_id", (DELETED,))

        self.assertEqual(before, after)
        self.assertTrue(after, "the seed should give other members statistics")

    async def test_deletes_the_members_wrapped_in_every_server_and_year(self):
        await main.delete_member_data(DELETED)

        self.assertEqual([], hof_wrapped_repo.get_hof_wrapped_for_user(self.connection, DELETED))

    async def test_removes_the_member_from_every_fan_list(self):
        await main.delete_member_data(DELETED)

        for fan_of_users, users_fans in self.rows("SELECT fan_of_users, users_fans FROM hof_wrapped"):
            for value in (fan_of_users, users_fans):
                if value is not None:
                    self.assertNotIn(str(DELETED), json.loads(value))

    async def test_keeps_a_member_whose_id_starts_with_the_deleted_id(self):
        await main.delete_member_data(DELETED)

        fan_of_users = json.loads(self.rows(
            "SELECT fan_of_users FROM hof_wrapped WHERE guild_id = %s AND user_id = %s", (SHARED, OTHER))[0][0])
        self.assertEqual({str(FAN): 4, str(THIRD): 2}, fan_of_users)

    async def test_fan_lists_still_read_as_the_bot_reads_them(self):
        """Wrapped parses these with json.loads and looks members up by their ID as text."""
        await main.delete_member_data(DELETED)

        users_fans = json.loads(self.rows(
            "SELECT users_fans FROM hof_wrapped WHERE guild_id = %s AND user_id = %s", (SHARED, OTHER))[0][0])
        self.assertEqual({str(THIRD): 7}, users_fans)
        self.assertTrue(all(isinstance(key, str) for key in users_fans))

    async def test_empty_and_missing_fan_lists_stay_as_they_were(self):
        await main.delete_member_data(DELETED)

        self.assertEqual([("{}", "{}")], self.rows(
            "SELECT fan_of_users, users_fans FROM hof_wrapped WHERE guild_id = %s", (OTHERS_ONLY,)))
        self.assertEqual([(None, None)], self.rows(
            "SELECT fan_of_users, users_fans FROM hof_wrapped WHERE year = 2024"))

    async def test_forgets_the_members_privacy_choice(self):
        await main.delete_member_data(DELETED)

        self.assertFalse(global_profile_repo.is_hidden(self.connection, DELETED))

    async def test_other_members_keep_their_privacy_and_counting_choices(self):
        await main.delete_member_data(DELETED, stop_counting=True)

        self.assertTrue(global_profile_repo.is_hidden(self.connection, OTHER))
        self.assertTrue(opt_out_repo.is_opted_out(self.connection, THIRD))

    async def test_server_settings_and_history_are_untouched(self):
        tables = ("server_configs", "guild_lifecycle_event", "guild_monthly_snapshot", "hof_wrapped_progress")
        before = {table: self.rows(f"SELECT * FROM {table} ORDER BY 1, 2") for table in tables}
        await main.delete_member_data(DELETED)

        for table in tables:
            with self.subTest(table=table):
                self.assertEqual(before[table], self.rows(f"SELECT * FROM {table} ORDER BY 1, 2"))

    async def test_my_data_finds_nothing_afterwards(self):
        await main.delete_member_data(DELETED)

        self.assertEqual([], hall_of_fame_message_repo.get_messages_by_author(self.connection, DELETED))
        self.assertEqual([], server_user_repo.get_server_users_for_user(self.connection, DELETED))
        self.assertEqual([], hof_wrapped_repo.get_hof_wrapped_for_user(self.connection, DELETED))
        self.assertFalse(global_profile_repo.is_hidden(self.connection, DELETED))

    async def test_the_totals_across_servers_are_empty_afterwards(self):
        await main.delete_member_data(DELETED)

        profile = global_profile_repo.get_global_profile(self.connection, DELETED)
        self.assertEqual({field: 0 for field in global_profile_repo.PROFILE_FIELDS}, profile)

    async def test_other_members_totals_across_servers_are_unchanged(self):
        before = global_profile_repo.get_global_profile(self.connection, OTHER)
        await main.delete_member_data(DELETED)

        self.assertEqual(before, global_profile_repo.get_global_profile(self.connection, OTHER))

    async def test_deleting_a_member_with_no_data_changes_nothing(self):
        before = self.snapshot()
        detached = await main.delete_member_data(NOBODY)

        self.assertEqual(0, detached)
        self.assertEqual(before, self.snapshot())

    async def test_deleting_twice_changes_nothing_more(self):
        await main.delete_member_data(DELETED)
        once = self.snapshot()
        detached = await main.delete_member_data(DELETED)

        self.assertEqual(0, detached)
        self.assertEqual(once, self.snapshot())

    async def test_a_deletion_that_failed_part_way_completes_when_run_again(self):
        """
        Each step commits on its own, so a failure can leave a deletion half done. Running it again,
        which the member can do, must end in exactly the state a clean deletion would have.
        """
        before = self.snapshot()
        with mock.patch.object(hof_wrapped_repo, "delete_hof_wrapped_for_user",
                               side_effect=RuntimeError("connection lost")):
            with self.assertRaises(RuntimeError):
                await main.delete_member_data(DELETED)
        await main.delete_member_data(DELETED)

        self.assert_only_the_member_changed(before, self.snapshot(), DELETED, stop_counting=False)

    async def test_resets_the_statement_timeout_afterwards(self):
        """The connection goes back to the pool, and a leftover timeout would cut short the daily task."""
        await main.delete_member_data(DELETED)

        self.assertEqual([("0",)], self.rows("SHOW statement_timeout"))

    async def test_the_member_does_not_come_back_with_the_daily_rebuild(self):
        await main.delete_member_data(DELETED)
        self.rebuild_all()

        self.assertEqual([], server_user_repo.get_server_users_for_user(self.connection, DELETED))

    async def test_the_daily_rebuild_keeps_everyone_elses_totals(self):
        """Ranks may move up into the freed places, but nobody else's counts may change."""
        query = ("SELECT user_id, guild_id, total_hall_of_fame_messages, total_hall_of_fame_message_reactions, "
                 "this_month_hall_of_fame_messages, this_month_hall_of_fame_message_reactions FROM server_user "
                 "WHERE user_id <> %s ORDER BY user_id, guild_id")
        before = self.rows(query, (DELETED,))
        await main.delete_member_data(DELETED)
        self.rebuild_all()

        self.assertEqual(before, self.rows(query, (DELETED,)))

    async def test_the_daily_rebuild_moves_others_up_into_the_freed_rank(self):
        await main.delete_member_data(DELETED)
        self.rebuild_all()

        ranks = self.rows("SELECT total_message_rank FROM server_user WHERE guild_id = %s ORDER BY 1", (SHARED,))
        self.assertEqual([(1,), (2,), (3,)], ranks)


class StopCountingTests(MemberDataDeletionTestCase):
    async def post(self, author_id, message_id=900):
        """Feature a new message through the bot's own posting code, with the Discord side faked"""
        async def send(*_args, **_kwargs):
            return types.SimpleNamespace(id=message_id + 5000)

        async def no_embed(*_args, **_kwargs):
            return None

        async def five(*_args, **_kwargs):
            return 5

        channel = types.SimpleNamespace(send=send)
        bot = types.SimpleNamespace(get_channel=lambda _channel_id: channel)
        message = types.SimpleNamespace(id=message_id, channel=types.SimpleNamespace(id=501),
                                        guild=types.SimpleNamespace(id=SHARED),
                                        author=types.SimpleNamespace(id=author_id))
        with mock.patch.object(utils, "create_embed", no_embed), \
                mock.patch.object(utils, "reaction_count", five), \
                mock.patch.object(utils, "check_video_extension", lambda _message: None):
            await utils.post_hall_of_fame_message(message, bot, self.connection, SHARED * 10, 5)
        return self.rows("SELECT author_id FROM hall_of_fame_message WHERE message_id = %s", (message_id,))[0][0]

    async def test_records_that_the_member_is_not_counted(self):
        await main.delete_member_data(DELETED, stop_counting=True)

        self.assertTrue(opt_out_repo.is_opted_out(self.connection, DELETED))

    async def test_a_plain_deletion_keeps_counting_the_member(self):
        await main.delete_member_data(DELETED)

        self.assertFalse(opt_out_repo.is_opted_out(self.connection, DELETED))

    async def test_a_new_post_by_a_member_not_counted_is_stored_without_them(self):
        await main.delete_member_data(DELETED, stop_counting=True)

        self.assertEqual(hall_of_fame_message_repo.NO_AUTHOR_ID, await self.post(DELETED))

    async def test_the_post_still_reaches_the_board(self):
        """The board belongs to the server, so opting out does not stop the repost."""
        await main.delete_member_data(DELETED, stop_counting=True)
        await self.post(DELETED, message_id=901)

        self.assertEqual([(5901,)], self.rows(
            "SELECT hall_of_fame_message_id FROM hall_of_fame_message WHERE message_id = 901"))

    async def test_a_new_post_by_anybody_else_keeps_its_author(self):
        await main.delete_member_data(DELETED, stop_counting=True)

        self.assertEqual(OTHER, await self.post(OTHER))

    async def test_the_member_stays_off_the_statistics_after_new_posts(self):
        await main.delete_member_data(DELETED, stop_counting=True)
        await self.post(DELETED)
        self.rebuild_all()

        self.assertEqual([], server_user_repo.get_server_users_for_user(self.connection, DELETED))

    async def test_counting_again_credits_new_posts(self):
        await main.delete_member_data(DELETED, stop_counting=True)
        opt_out_repo.set_opted_out(self.connection, DELETED, False)

        self.assertEqual(DELETED, await self.post(DELETED))

    async def test_counting_again_leaves_earlier_posts_uncredited(self):
        await main.delete_member_data(DELETED, stop_counting=True)
        await self.post(DELETED, message_id=902)
        opt_out_repo.set_opted_out(self.connection, DELETED, False)

        self.assertEqual([(0,)], self.rows("SELECT author_id FROM hall_of_fame_message WHERE message_id = 902"))
        self.assertEqual([], self.posts_by(DELETED))

    async def test_counting_again_only_removes_this_member(self):
        await main.delete_member_data(DELETED, stop_counting=True)
        opt_out_repo.set_opted_out(self.connection, DELETED, False)

        self.assertTrue(opt_out_repo.is_opted_out(self.connection, THIRD))


class CoverageGuardTests(MemberDataDeletionTestCase):
    def test_every_table_holding_member_ids_is_handled_by_the_deletion(self):
        """
        A new table with a user_id or author_id column holds member data, so /delete_my_data has to
        handle it and this test has to be told about it. Without this, a new feature could keep data
        that a member was promised is deleted.
        """
        found = {row[0] for row in self.rows(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE table_schema = %s AND column_name IN ('user_id', 'author_id')", (self.schema,))}

        self.assertEqual(TABLES_WITH_MEMBER_IDS, found)


if __name__ == "__main__":
    unittest.main()
