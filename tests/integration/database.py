"""A real, disposable PostgreSQL schema for the tests that must prove what the SQL actually does.

The unit tests use fakes that only record the SQL text, which cannot show which rows a DELETE or an
UPDATE really touches. These tests run the real statements instead.

They only run when HOF_TEST_DATABASE_URL is set, as a libpq connection string. Point it at a
throwaway database, never at a bot's database: the tests create their own schema with a random name,
build every table in it with the bot's own setup code, and drop it again afterwards, but a test
database is still the only safe place for that. CI starts a fresh PostgreSQL service for it.
"""

import contextlib
import io
import os
import unittest
import uuid

import psycopg2

DATABASE_URL_VARIABLE = "HOF_TEST_DATABASE_URL"


def database_url():
    return os.environ.get(DATABASE_URL_VARIABLE)


def skip_without_database(test_case):
    return unittest.skipUnless(database_url(), f"{DATABASE_URL_VARIABLE} is not set")(test_case)


class SingleConnectionPool:
    """Hands out the test's own connection, in the shape the bot's pool has."""

    def __init__(self, connection):
        self.connection = connection

    def getconn(self):
        return self.connection

    def putconn(self, _connection):
        pass


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    """Every test gets an empty schema of its own, with every table the bot creates on start."""

    def setUp(self):
        self.connection = psycopg2.connect(database_url())
        self.schema = f"hof_test_{uuid.uuid4().hex[:12]}"
        cursor = self.connection.cursor()
        cursor.execute(f"CREATE SCHEMA {self.schema}")
        cursor.execute(f"SET search_path TO {self.schema}")
        cursor.close()
        self.connection.commit()
        self.addCleanup(self.drop_schema)

        import main
        # The setup prints a line per table, which is noise in a test run
        with contextlib.redirect_stdout(io.StringIO()):
            main.setup_databases(self.connection)

    def drop_schema(self):
        self.connection.rollback()
        cursor = self.connection.cursor()
        # Only ever the schema this test created, whose name is random
        cursor.execute(f"DROP SCHEMA {self.schema} CASCADE")
        cursor.close()
        self.connection.commit()
        self.connection.close()

    def execute(self, sql, params=None):
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        cursor.close()
        self.connection.commit()

    def rows(self, sql, params=None):
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        result = cursor.fetchall()
        cursor.close()
        self.connection.commit()
        return result
