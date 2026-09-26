"""Tests for how the statistics report reads the database and fakes it.

An optional query may only come back empty for a table or column the deployment does not have yet.
Any other failure has to surface, or the report shows zero churn instead of admitting it failed.
The synthetic dataset has to count posts over the same trailing window as the production query.
"""

import unittest
from datetime import date, datetime, timezone

from stats import queries, synthetic


class DatabaseError(Exception):
    def __init__(self, pgcode):
        super().__init__(f"pgcode {pgcode}")
        self.pgcode = pgcode


class FailingCursor:
    def __init__(self, error):
        self.error = error

    def execute(self, _sql, _params=None):
        raise self.error

    def close(self):
        pass


class FailingConnection:
    def __init__(self, error):
        self.error = error
        self.rollbacks = 0

    def cursor(self):
        return FailingCursor(self.error)

    def rollback(self):
        self.rollbacks += 1


class OptionalFetchTests(unittest.TestCase):
    def test_a_missing_table_comes_back_empty(self):
        connection = FailingConnection(DatabaseError("42P01"))

        self.assertEqual([], queries._fetch(connection, "SELECT 1", optional=True))
        self.assertEqual(1, connection.rollbacks)

    def test_a_missing_column_comes_back_empty(self):
        connection = FailingConnection(DatabaseError("42703"))

        self.assertEqual([], queries._fetch(connection, "SELECT 1", optional=True))

    def test_a_permission_error_still_raises(self):
        connection = FailingConnection(DatabaseError("42501"))

        with self.assertRaises(DatabaseError):
            queries._fetch(connection, "SELECT 1", optional=True)

    def test_a_dropped_connection_still_raises(self):
        connection = FailingConnection(ConnectionError("server closed the connection"))

        with self.assertRaises(ConnectionError):
            queries._fetch(connection, "SELECT 1", optional=True)

    def test_a_required_query_raises_even_for_a_missing_table(self):
        connection = FailingConnection(DatabaseError("42P01"))

        with self.assertRaises(DatabaseError):
            queries._fetch(connection, "SELECT 1")


class SyntheticTrailingWindowTests(unittest.TestCase):
    now = datetime(2026, 9, 8, tzinfo=timezone.utc)

    def test_counts_the_end_of_last_month_as_well_as_this_one(self):
        # The window runs from 9 August, so 23 of August's 31 days and 7 of September's 30 fall in it
        series = [(date(2026, 8, 1), 310), (date(2026, 9, 1), 300)]

        self.assertEqual(230 + 70, synthetic._posts_in_trailing_window(series, self.now))

    def test_ignores_months_before_the_window(self):
        series = [(date(2026, 6, 1), 500), (date(2026, 7, 1), 500)]

        self.assertEqual(0, synthetic._posts_in_trailing_window(series, self.now))

    def test_only_uses_calculation_methods_the_bot_stores(self):
        from enums import calculation_method_type

        stored = {calculation_method_type.MOST_REACTIONS_ON_EMOJI, calculation_method_type.TOTAL_REACTIONS,
                  calculation_method_type.UNIQUE_USERS}
        self.assertEqual(stored, {method for method, _ in synthetic.CALCULATION_METHODS})


if __name__ == "__main__":
    unittest.main()
