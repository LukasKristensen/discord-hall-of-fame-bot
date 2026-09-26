"""Tests for how the statistics report chooses its database.

Kept apart from the export tests, which need matplotlib and are skipped in CI, because this is the
check that a development run never holds the production credentials and it has to run everywhere.
"""

import os
import unittest
from unittest import mock

import server_stats


class DatabaseSettingsTests(unittest.TestCase):
    """The report must choose its database the way the bot does."""

    variables = {
        "POSTGRES_HOST": "production-host", "POSTGRES_DB": "production-db",
        "POSTGRES_USER": "production-user", "POSTGRES_PASSWORD": "production-password",
        "POSTGRES_HOST_LOCAL": "local-host", "POSTGRES_DB_LOCAL": "local-db",
        "POSTGRES_USER_LOCAL": "local-user", "POSTGRES_PASSWORD_LOCAL": "local-password",
    }

    def settings(self, dev_test):
        with mock.patch.dict(os.environ, dict(self.variables, DEV_TEST=dev_test), clear=True), \
                mock.patch.object(server_stats, "load_dotenv"):
            return server_stats.database_settings()

    def test_a_development_run_reads_the_local_database(self):
        settings = self.settings("True")

        self.assertEqual("local-host", settings["host"])
        self.assertNotIn("production-password", settings.values())

    def test_a_production_run_reads_the_production_database(self):
        self.assertEqual("production-host", self.settings("False")["host"])


if __name__ == "__main__":
    unittest.main()
