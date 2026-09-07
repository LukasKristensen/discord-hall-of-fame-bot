import unittest

from tests.fakes import FakeConnection

from repositories import server_config_repo


class ParameterValidationTests(unittest.TestCase):
    def test_reading_an_unknown_column_is_rejected(self):
        with self.assertRaises(ValueError):
            server_config_repo.get_parameter_value(FakeConnection(), 1, "guild_id; DROP TABLE server_configs")

    def test_writing_an_unknown_column_is_rejected(self):
        with self.assertRaises(ValueError):
            server_config_repo.update_server_config_param(1, "not_a_column", True, FakeConnection())

    def test_reading_a_known_column_returns_the_value(self):
        connection = FakeConnection(row=(7,))
        self.assertEqual(7, server_config_repo.get_parameter_value(connection, 1, "reaction_threshold"))


class ReactionConfigTests(unittest.TestCase):
    def test_maps_the_row_to_the_configuration(self):
        connection = FakeConnection(row=("total_reactions", False, True, ["👍"]))
        config = server_config_repo.get_reaction_config(connection, 1)

        self.assertEqual({
            "reaction_count_calculation_method": "total_reactions",
            "include_author_in_reaction_calculation": False,
            "custom_emoji_check_logic": True,
            "whitelisted_emojis": ["👍"]
        }, config)

    def test_uses_a_single_parameterised_query(self):
        connection = FakeConnection(row=("total_reactions", False, True, ["👍"]))
        server_config_repo.get_reaction_config(connection, 4321)

        self.assertEqual(1, len(connection.queries))
        self.assertEqual([(4321,)], [params for cursor in connection.cursors for _, params in cursor.executed])

    def test_returns_empty_values_for_an_unknown_guild(self):
        config = server_config_repo.get_reaction_config(FakeConnection(row=None), 1)

        self.assertEqual(set(server_config_repo.REACTION_CONFIG_COLUMNS), set(config))
        self.assertTrue(all(value is None for value in config.values()))


if __name__ == "__main__":
    unittest.main()
