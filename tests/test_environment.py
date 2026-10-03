"""Tests for the environment gate in front of the production credentials.

Only the live bot reports to the listing sites, so only the live bot has any use for their keys. A
development run that reads them is holding a credential it cannot legitimately use, and one that
could authenticate as the real bot by accident. These tests pin the gate that stops that, including
the default, since an unset flag has to mean production for the deployed bot to keep working.
"""

import unittest
from unittest import mock

import environment
from api_services import discordbotlist_api, topgg_api


def running_as(development: bool):
    """Replace the environment with one holding both keys and the requested development flag."""
    return mock.patch.dict("os.environ", {
        environment.DEVELOPMENT_FLAG: "True" if development else "False",
        "TOPGG_API_KEY": "live-topgg-key",
        "DISCORD_BOT_LIST_API_KEY": "live-dbl-key",
    }, clear=True)


class IsDevelopmentTests(unittest.TestCase):
    def test_the_flag_being_true_means_development(self):
        with mock.patch.dict("os.environ", {environment.DEVELOPMENT_FLAG: "True"}, clear=True):
            self.assertTrue(environment.is_development())
            self.assertFalse(environment.is_production())

    def test_the_flag_being_false_means_production(self):
        with mock.patch.dict("os.environ", {environment.DEVELOPMENT_FLAG: "False"}, clear=True):
            self.assertTrue(environment.is_production())

    def test_an_unset_flag_means_production(self):
        """The deployed bot does not set it, so the default has to stay production."""
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(environment.is_production())

    def test_only_the_exact_word_counts_as_development(self):
        for value in ("true", "TRUE", "1", "yes", ""):
            with self.subTest(value=value):
                with mock.patch.dict("os.environ", {environment.DEVELOPMENT_FLAG: value}, clear=True):
                    self.assertTrue(environment.is_production())


class ProductionSecretTests(unittest.TestCase):
    def test_reads_the_credential_in_production(self):
        with running_as(development=False):
            self.assertEqual("live-topgg-key", environment.production_secret("TOPGG_API_KEY"))

    def test_withholds_the_credential_in_development(self):
        with running_as(development=True):
            self.assertIsNone(environment.production_secret("TOPGG_API_KEY"))

    def test_withholds_a_credential_that_is_present_in_the_environment(self):
        """The variable being set is exactly the case this guards against."""
        with running_as(development=True):
            import os
            self.assertEqual("live-topgg-key", os.environ["TOPGG_API_KEY"])
            self.assertIsNone(environment.production_secret("TOPGG_API_KEY"))

    def test_returns_nothing_for_a_credential_that_is_not_configured(self):
        with mock.patch.dict("os.environ", {environment.DEVELOPMENT_FLAG: "False"}, clear=True):
            self.assertIsNone(environment.production_secret("TOPGG_API_KEY"))


class ListingSiteKeyTests(unittest.TestCase):
    def test_the_development_bot_holds_no_top_gg_key(self):
        with running_as(development=True):
            self.assertIsNone(topgg_api.auth_key())

    def test_the_development_bot_holds_no_discordbotlist_key(self):
        with running_as(development=True):
            self.assertIsNone(discordbotlist_api.auth_key())

    def test_the_live_bot_holds_the_top_gg_key(self):
        with running_as(development=False):
            self.assertEqual("live-topgg-key", topgg_api.auth_key())

    def test_the_live_bot_holds_the_discordbotlist_key(self):
        with running_as(development=False):
            self.assertEqual("live-dbl-key", discordbotlist_api.auth_key())

    def test_the_key_is_read_when_it_is_needed_rather_than_when_imported(self):
        """Read at import, the environment at import time would decide it for the whole process."""
        with running_as(development=True):
            self.assertIsNone(topgg_api.auth_key())
        with running_as(development=False):
            self.assertEqual("live-topgg-key", topgg_api.auth_key())


ENV_FILE = {
    "DEV_KEY": "development-token",
    "KEY": "live-token",
    "TOPGG_API_KEY": "live-topgg-key",
    "DISCORD_BOT_LIST_API_KEY": "live-dbl-key",
    "POSTGRES_HOST": "production-host", "POSTGRES_DB": "production-db",
    "POSTGRES_USER": "production-user", "POSTGRES_PASSWORD": "production-password",
    "POSTGRES_HOST_LOCAL": "local-host", "POSTGRES_DB_LOCAL": "local-db",
    "POSTGRES_USER_LOCAL": "local-user", "POSTGRES_PASSWORD_LOCAL": "local-password",
}


class LoadEnvironmentTests(unittest.TestCase):
    """Gating the readers is not enough if loading .env puts every live credential in the environment."""

    def load(self, env_file, already_set=None):
        import os
        with mock.patch.dict("os.environ", already_set or {}, clear=True):
            environment.load_environment(env_file)
            return dict(os.environ)

    def test_a_development_run_loads_no_production_only_value(self):
        loaded = self.load(dict(ENV_FILE, DEV_TEST="True"))

        for name in environment.PRODUCTION_ONLY_VARIABLES:
            self.assertNotIn(name, loaded)
        self.assertEqual("development-token", loaded["DEV_KEY"])
        self.assertEqual("local-host", loaded["POSTGRES_HOST_LOCAL"])

    def test_the_flag_can_come_from_the_shell_rather_than_the_file(self):
        loaded = self.load(dict(ENV_FILE, DEV_TEST="False"), already_set={"DEV_TEST": "True"})

        self.assertNotIn("KEY", loaded)
        self.assertEqual("True", loaded["DEV_TEST"])

    def test_the_live_bot_loads_everything(self):
        loaded = self.load(dict(ENV_FILE, DEV_TEST="False"))

        self.assertEqual("live-token", loaded["KEY"])
        self.assertEqual("production-password", loaded["POSTGRES_PASSWORD"])

    def test_the_live_bot_loads_everything_when_the_flag_is_unset(self):
        """The deployed bot does not set it, so an unset flag has to keep loading the live values."""
        loaded = self.load(dict(ENV_FILE))

        self.assertEqual("live-token", loaded["KEY"])

    def test_a_value_already_in_the_environment_is_left_alone(self):
        loaded = self.load(dict(ENV_FILE, DEV_TEST="False"), already_set={"KEY": "from-the-shell"})

        self.assertEqual("from-the-shell", loaded["KEY"])


class DatabaseSettingsTests(unittest.TestCase):
    def settings(self, development):
        with mock.patch.dict("os.environ", dict(ENV_FILE, DEV_TEST="True" if development else "False"),
                             clear=True):
            return environment.database_settings()

    def test_development_connects_to_the_local_database(self):
        self.assertEqual({"host": "local-host", "database": "local-db", "user": "local-user",
                          "password": "local-password"}, self.settings(development=True))

    def test_production_connects_to_the_production_database(self):
        self.assertEqual("production-host", self.settings(development=False)["host"])


class DevelopmentRequestTests(unittest.TestCase):
    def test_a_development_stats_post_carries_no_credential(self):
        """The bot skips this call in development, and it would be unauthenticated even if not."""
        with running_as(development=True):
            with mock.patch.object(discordbotlist_api.requests, "post") as request:
                request.return_value = mock.Mock(status_code=200, **{"json.return_value": {}})
                discordbotlist_api.post_bot_stats(140)

        self.assertIsNone(request.call_args.kwargs["headers"]["Authorization"])


if __name__ == "__main__":
    unittest.main()
