"""Tests for the table holding every message that has reached the Hall of Fame.

This is the table the posting path reads on every reaction and the leaderboard reads every day, so
the tests here are about three things: that a row is mapped back to the fields the rest of the bot
expects by name, that every query is scoped to the guild it was asked about, and that the two
places where a caller supplies a column name cannot be talked into naming something else.
"""

import datetime
import unittest

from repositories import hall_of_fame_message_repo

from tests.fakes import FakeConnection

MESSAGE_COLUMNS = ["message_id", "channel_id", "guild_id", "hall_of_fame_message_id",
                   "reaction_count", "author_id", "created_at", "video_link_message_id"]

MESSAGE_ROW = (4242, 100, 200, 5555, 12, 77, datetime.datetime(2026, 3, 1, 12, 0), None)


class FindHallOfFameMessageTests(unittest.TestCase):
    def test_maps_the_row_to_its_column_names(self):
        connection = FakeConnection(row=MESSAGE_ROW, description=MESSAGE_COLUMNS)
        found = hall_of_fame_message_repo.find_hall_of_fame_message(connection, 200, 100, 4242)

        self.assertEqual(4242, found["message_id"])
        self.assertEqual(5555, found["hall_of_fame_message_id"])
        self.assertEqual(12, found["reaction_count"])

    def test_carries_a_null_video_link_through_as_a_key(self):
        """The posting path reads this key on every restore, so it must exist even when null."""
        connection = FakeConnection(row=MESSAGE_ROW, description=MESSAGE_COLUMNS)
        found = hall_of_fame_message_repo.find_hall_of_fame_message(connection, 200, 100, 4242)

        self.assertIn("video_link_message_id", found)
        self.assertIsNone(found["video_link_message_id"])

    def test_returns_nothing_for_a_message_that_is_not_on_the_board(self):
        connection = FakeConnection(row=None, description=MESSAGE_COLUMNS)
        self.assertIsNone(hall_of_fame_message_repo.find_hall_of_fame_message(connection, 200, 100, 4242))

    def test_looks_the_message_up_by_guild_channel_and_message(self):
        connection = FakeConnection(row=MESSAGE_ROW, description=MESSAGE_COLUMNS)
        hall_of_fame_message_repo.find_hall_of_fame_message(connection, 200, 100, 4242)

        self.assertEqual([(200, 100, 4242)], connection.parameters)

    def test_closes_the_cursor(self):
        connection = FakeConnection(row=MESSAGE_ROW, description=MESSAGE_COLUMNS)
        hall_of_fame_message_repo.find_hall_of_fame_message(connection, 200, 100, 4242)

        self.assertTrue(all(cursor.closed for cursor in connection.cursors))


class GuildMessageCountTodayTests(unittest.TestCase):
    def test_returns_the_count(self):
        connection = FakeConnection(row=(37,))
        self.assertEqual(37, hall_of_fame_message_repo.guild_message_count_today(connection, 200))

    def test_returns_zero_for_a_guild_that_has_posted_nothing(self):
        connection = FakeConnection(row=None)
        self.assertEqual(0, hall_of_fame_message_repo.guild_message_count_today(connection, 200))

    def test_counts_from_the_start_of_today_rather_than_the_last_day(self):
        """The daily limit resets at midnight, it is not a rolling twenty four hour window."""
        connection = FakeConnection(row=(0,))
        hall_of_fame_message_repo.guild_message_count_today(connection, 200)

        self.assertIn("DATE_TRUNC('day', NOW())", connection.queries[0])

    def test_counts_only_the_guild_it_was_asked_about(self):
        connection = FakeConnection(row=(0,))
        hall_of_fame_message_repo.guild_message_count_today(connection, 200)

        self.assertEqual([(200,)], connection.parameters)


class InsertHallOfFameMessageTests(unittest.TestCase):
    def insert(self, connection, video_link_message_id=None):
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            connection, 4242, 100, 200, 5555, 12, 77,
            datetime.datetime(2026, 3, 1, 12, 0), video_link_message_id)

    def test_writes_every_column_in_order(self):
        connection = FakeConnection()
        self.insert(connection)

        self.assertEqual(
            (4242, 100, 200, 5555, 12, 77, datetime.datetime(2026, 3, 1, 12, 0), None),
            connection.parameters[0])

    def test_keeps_the_video_link_when_there_is_one(self):
        connection = FakeConnection()
        self.insert(connection, video_link_message_id=6666)

        self.assertEqual(6666, connection.parameters[0][-1])

    def test_replaces_a_message_that_is_already_recorded(self):
        """A message can be reposted after being hidden, and must not become a second row."""
        connection = FakeConnection()
        self.insert(connection)

        self.assertIn("ON CONFLICT (message_id) DO UPDATE", connection.queries[0])

    def test_commits(self):
        connection = FakeConnection()
        self.insert(connection)

        self.assertEqual(1, connection.commits)


class UpdateFieldForMessageTests(unittest.TestCase):
    """The only place a caller names a column, so it is the only place a name can be smuggled in."""

    def test_rejects_a_column_it_does_not_know(self):
        with self.assertRaises(ValueError):
            hall_of_fame_message_repo.update_field_for_message(
                FakeConnection(), 200, 100, 4242, "reaction_count = 0; DROP TABLE hall_of_fame_message", 1)

    def test_rejects_a_column_that_exists_but_is_not_updatable(self):
        with self.assertRaises(ValueError):
            hall_of_fame_message_repo.update_field_for_message(
                FakeConnection(), 200, 100, 4242, "message_id", 1)

    def test_writes_an_allowed_column(self):
        connection = FakeConnection()
        hall_of_fame_message_repo.update_field_for_message(connection, 200, 100, 4242, "reaction_count", 15)

        self.assertIn("SET reaction_count = %s", connection.queries[0])

    def test_passes_the_value_as_a_parameter_rather_than_inlining_it(self):
        connection = FakeConnection()
        hall_of_fame_message_repo.update_field_for_message(connection, 200, 100, 4242, "reaction_count", 15)

        self.assertEqual([(15, 200, 100, 4242)], connection.parameters)

    def test_updates_one_message_in_one_guild(self):
        connection = FakeConnection()
        hall_of_fame_message_repo.update_field_for_message(connection, 200, 100, 4242, "reaction_count", 15)

        self.assertIn("WHERE guild_id = %s AND channel_id = %s AND message_id = %s", connection.queries[0])

    def test_allows_every_field_the_bot_actually_updates(self):
        for field in ("hall_of_fame_message_id", "reaction_count", "video_link_message_id"):
            with self.subTest(field=field):
                hall_of_fame_message_repo.update_field_for_message(
                    FakeConnection(), 200, 100, 4242, field, 1)


class FindTopMessagesTests(unittest.TestCase):
    def test_maps_every_row(self):
        connection = FakeConnection(rows=[MESSAGE_ROW, MESSAGE_ROW], description=MESSAGE_COLUMNS)
        found = hall_of_fame_message_repo.find_top_messages_by_reaction_count(connection, 200)

        self.assertEqual(2, len(found))
        self.assertEqual(12, found[0]["reaction_count"])

    def test_ranks_by_reaction_count(self):
        connection = FakeConnection(rows=[], description=MESSAGE_COLUMNS)
        hall_of_fame_message_repo.find_top_messages_by_reaction_count(connection, 200)

        self.assertIn("ORDER BY reaction_count DESC", connection.queries[0])

    def test_passes_the_limit_it_was_given(self):
        connection = FakeConnection(rows=[], description=MESSAGE_COLUMNS)
        hall_of_fame_message_repo.find_top_messages_by_reaction_count(connection, 200, limit=30)

        self.assertEqual([(200, 30)], connection.parameters)

    def test_returns_nothing_for_a_guild_with_an_empty_board(self):
        connection = FakeConnection(rows=[], description=MESSAGE_COLUMNS)
        self.assertEqual([], hall_of_fame_message_repo.find_top_messages_by_reaction_count(connection, 200))


class GuildScopedReadTests(unittest.TestCase):
    def test_counts_the_messages_of_one_guild(self):
        connection = FakeConnection(row=(9,))
        self.assertEqual(9, hall_of_fame_message_repo.count_messages_for_guild(connection, 200))
        self.assertEqual([(200,)], connection.parameters)

    def test_counts_zero_for_an_unknown_guild(self):
        connection = FakeConnection(row=None)
        self.assertEqual(0, hall_of_fame_message_repo.count_messages_for_guild(connection, 200))

    def test_lists_each_member_once(self):
        connection = FakeConnection(rows=[(77,), (88,)])
        self.assertEqual([77, 88], hall_of_fame_message_repo.find_members_for_guild(connection, 200))
        self.assertIn("SELECT DISTINCT author_id", connection.queries[0])

    def test_deletes_only_the_guild_it_was_asked_about(self):
        connection = FakeConnection()
        hall_of_fame_message_repo.delete_hall_of_fame_messages_for_guild(connection, 200)

        self.assertIn("WHERE guild_id = %s", connection.queries[0])
        self.assertEqual([(200,)], connection.parameters)

    def test_maps_every_hall_of_fame_message_of_a_guild(self):
        connection = FakeConnection(rows=[MESSAGE_ROW], description=MESSAGE_COLUMNS)
        found = hall_of_fame_message_repo.get_all_hall_of_fame_messages_for_guild(connection, 200)

        self.assertEqual([200], [message["guild_id"] for message in found])


class MonthlyMessageCountTests(unittest.TestCase):
    def test_maps_the_count_of_every_guild(self):
        connection = FakeConnection(rows=[(200, 40), (201, 12)])
        counts = hall_of_fame_message_repo.get_monthly_message_counts_by_guild(
            connection, datetime.date(2026, 3, 1), datetime.date(2026, 4, 1))

        self.assertEqual([{"guild_id": 200, "message_count": 40},
                          {"guild_id": 201, "message_count": 12}], counts)

    def test_takes_the_month_as_a_half_open_range(self):
        """A closed range would count the first message of the next month twice."""
        connection = FakeConnection(rows=[])
        hall_of_fame_message_repo.get_monthly_message_counts_by_guild(
            connection, datetime.date(2026, 3, 1), datetime.date(2026, 4, 1))

        self.assertIn("created_at >= %s AND created_at < %s", connection.queries[0])


if __name__ == "__main__":
    unittest.main()
