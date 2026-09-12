"""Tests for the two tables behind Hall of Fame Wrapped.

``hof_wrapped`` holds one finished wrapped per member per year, and ``hof_wrapped_progress`` records
how far the yearly generation got for a guild. The generation walks a guild's whole history, so the
progress table is what lets it be resumed rather than started again, and both tables are keyed by
year so that one year's run cannot overwrite another's.
"""

import unittest

from repositories import hof_wrapped_guild_status_repo, hof_wrapped_repo

from tests.fakes import FakeConnection

WRAPPED_COLUMNS = ["id", "guild_id", "user_id", "year", "reaction_count", "hof_message_posts",
                   "most_used_channels", "most_used_emojis", "most_reacted_post_message_id",
                   "most_reacted_post_channel_id", "most_reacted_post_reaction_count",
                   "fan_of_users", "users_fans", "created_at", "user_ranks"]

WRAPPED_ROW = (1, 200, 77, 2025, 640, 32, "general", "😂", 4242, 100, 55,
               "88", "99", None, "1")


def insert_arguments(**overrides):
    arguments = {
        "guild_id": 200,
        "user_id": 77,
        "year": 2025,
        "reaction_count": 640,
        "hof_message_posts": 32,
        "most_used_channels": "general",
        "most_used_emojis": "😂",
        "most_reacted_post_message_id": 4242,
        "most_reacted_post_channel_id": 100,
        "most_reacted_post_reaction_count": 55,
        "fan_of_users": "88",
        "users_fans": "99",
        "user_ranks": "1",
    }
    arguments.update(overrides)
    return arguments


class GetHofWrappedTests(unittest.TestCase):
    def test_maps_the_row_to_its_column_names(self):
        connection = FakeConnection(row=WRAPPED_ROW, description=WRAPPED_COLUMNS)
        wrapped = hof_wrapped_repo.get_hof_wrapped(connection, 200, 77, 2025)

        self.assertEqual(640, wrapped["reaction_count"])
        self.assertEqual(32, wrapped["hof_message_posts"])
        self.assertEqual(2025, wrapped["year"])

    def test_returns_nothing_for_a_member_with_no_wrapped_that_year(self):
        connection = FakeConnection(row=None, description=WRAPPED_COLUMNS)
        self.assertIsNone(hof_wrapped_repo.get_hof_wrapped(connection, 200, 77, 2025))

    def test_reads_one_member_in_one_guild_for_one_year(self):
        connection = FakeConnection(row=WRAPPED_ROW, description=WRAPPED_COLUMNS)
        hof_wrapped_repo.get_hof_wrapped(connection, 200, 77, 2025)

        self.assertEqual([(200, 77, 2025)], connection.parameters)

    def test_closes_the_cursor_when_a_wrapped_is_found(self):
        connection = FakeConnection(row=WRAPPED_ROW, description=WRAPPED_COLUMNS)
        hof_wrapped_repo.get_hof_wrapped(connection, 200, 77, 2025)

        self.assertTrue(all(cursor.closed for cursor in connection.cursors))

    def test_closes_the_cursor_when_no_wrapped_is_found(self):
        """A miss is the common case in a fresh guild, so it must not leak a cursor each time."""
        connection = FakeConnection(row=None, description=WRAPPED_COLUMNS)
        hof_wrapped_repo.get_hof_wrapped(connection, 200, 77, 2025)

        self.assertTrue(all(cursor.closed for cursor in connection.cursors))


class GetAllHofWrappedForGuildTests(unittest.TestCase):
    def test_maps_every_member(self):
        connection = FakeConnection(rows=[WRAPPED_ROW, WRAPPED_ROW], description=WRAPPED_COLUMNS)
        wrapped = hof_wrapped_repo.get_all_hof_wrapped_for_guild(connection, 200, 2025)

        self.assertEqual(2, len(wrapped))
        self.assertEqual(640, wrapped[0]["reaction_count"])

    def test_returns_nothing_for_a_guild_with_no_wrapped_that_year(self):
        connection = FakeConnection(rows=[], description=WRAPPED_COLUMNS)
        self.assertEqual([], hof_wrapped_repo.get_all_hof_wrapped_for_guild(connection, 200, 2025))

    def test_reads_one_guild_and_one_year(self):
        connection = FakeConnection(rows=[], description=WRAPPED_COLUMNS)
        hof_wrapped_repo.get_all_hof_wrapped_for_guild(connection, 200, 2025)

        self.assertEqual([(200, 2025)], connection.parameters)


class CheckIfGuildWrappedDataExistsTests(unittest.TestCase):
    def test_confirms_a_year_that_has_been_generated(self):
        connection = FakeConnection(row=(1,))
        self.assertTrue(hof_wrapped_repo.check_if_guild_wrapped_data_exists(connection, 200, 2025))

    def test_denies_a_year_that_has_not(self):
        connection = FakeConnection(row=None)
        self.assertFalse(hof_wrapped_repo.check_if_guild_wrapped_data_exists(connection, 200, 2025))

    def test_asks_about_one_guild_and_one_year(self):
        connection = FakeConnection(row=None)
        hof_wrapped_repo.check_if_guild_wrapped_data_exists(connection, 200, 2025)

        self.assertEqual([(200, 2025)], connection.parameters)


class InsertHofWrappedTests(unittest.TestCase):
    def test_writes_every_field_in_the_order_the_columns_are_listed(self):
        connection = FakeConnection()
        hof_wrapped_repo.insert_hof_wrapped(connection, **insert_arguments())

        self.assertEqual(
            (200, 77, 2025, 640, 32, "general", "😂", 4242, 100, 55, "88", "99", "1"),
            connection.parameters[0])

    def test_replaces_a_wrapped_that_was_generated_before(self):
        """Generation can be run again for a year, and must not leave two rows for one member."""
        connection = FakeConnection()
        hof_wrapped_repo.insert_hof_wrapped(connection, **insert_arguments())

        self.assertIn("ON CONFLICT (guild_id, user_id, year) DO UPDATE", connection.queries[0])

    def test_commits(self):
        connection = FakeConnection()
        hof_wrapped_repo.insert_hof_wrapped(connection, **insert_arguments())

        self.assertEqual(1, connection.commits)


class DeleteHofWrappedForGuildTests(unittest.TestCase):
    def test_removes_every_year_of_one_guild(self):
        connection = FakeConnection()
        hof_wrapped_repo.delete_hof_wrapped_for_guild(connection, 200)

        self.assertIn("WHERE guild_id = %s", connection.queries[0])
        self.assertEqual([(200,)], connection.parameters)


class WrappedProgressTests(unittest.TestCase):
    def test_records_how_much_history_a_guild_has_to_get_through(self):
        connection = FakeConnection()
        hof_wrapped_guild_status_repo.create_progress_entry(connection, 200, 2025, 4200)

        self.assertEqual([(200, 2025, 4200)], connection.parameters)

    def test_does_not_restart_progress_that_is_already_recorded(self):
        """Resuming depends on the first entry surviving a second attempt at the same year."""
        connection = FakeConnection()
        hof_wrapped_guild_status_repo.create_progress_entry(connection, 200, 2025, 4200)

        self.assertIn("ON CONFLICT (guild_id, year) DO NOTHING", connection.queries[0])

    def test_marks_one_guild_and_one_year_as_finished(self):
        connection = FakeConnection()
        hof_wrapped_guild_status_repo.mark_hof_wrapped_as_processed(connection, 200, 2025, 12.5)

        self.assertEqual([(12.5, 200, 2025)], connection.parameters)
        self.assertIn("WHERE guild_id = %s AND year = %s", connection.queries[0])

    def test_reports_a_year_that_has_been_processed(self):
        connection = FakeConnection(row=(True,))
        self.assertTrue(hof_wrapped_guild_status_repo.is_hof_wrapped_processed(connection, 200, 2025))

    def test_reports_a_year_that_was_started_but_not_finished(self):
        connection = FakeConnection(row=(False,))
        self.assertFalse(hof_wrapped_guild_status_repo.is_hof_wrapped_processed(connection, 200, 2025))

    def test_reports_a_year_that_was_never_started(self):
        connection = FakeConnection(row=None)
        self.assertFalse(hof_wrapped_guild_status_repo.is_hof_wrapped_processed(connection, 200, 2025))

    def test_closes_the_cursor(self):
        connection = FakeConnection(row=(True,))
        hof_wrapped_guild_status_repo.is_hof_wrapped_processed(connection, 200, 2025)

        self.assertTrue(all(cursor.closed for cursor in connection.cursors))


if __name__ == "__main__":
    unittest.main()
