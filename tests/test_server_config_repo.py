import datetime
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


class GuildIdsWithLeaderboardTests(unittest.TestCase):
    """The daily task updates exactly these guilds, so a wrong filter silently drops every leaderboard."""

    def test_returns_the_guild_of_every_row(self):
        connection = FakeConnection(rows=[(200,), (201,), (205,)])
        self.assertEqual({200, 201, 205}, server_config_repo.get_guild_ids_with_leaderboard(connection))

    def test_returns_nothing_when_no_guild_has_one(self):
        self.assertEqual(set(), server_config_repo.get_guild_ids_with_leaderboard(FakeConnection(rows=[])))

    def test_selects_only_guilds_with_a_leaderboard_set_up(self):
        connection = FakeConnection(rows=[])
        server_config_repo.get_guild_ids_with_leaderboard(connection)

        query = " ".join(connection.queries[0].split())
        self.assertEqual("SELECT guild_id FROM server_configs WHERE leaderboard_setup", query)

    def test_is_one_query_for_the_whole_fleet(self):
        connection = FakeConnection(rows=[(200,), (201,)])
        server_config_repo.get_guild_ids_with_leaderboard(connection)

        self.assertEqual(1, len(connection.queries))
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))


class RecordMissingGuildsTests(unittest.TestCase):
    """The grace period before a departed server is deleted is counted from this date."""

    NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.timezone.utc)

    def test_returns_when_each_server_was_first_found_missing(self):
        earlier = self.NOW - datetime.timedelta(days=3)
        connection = FakeConnection(rows=[(300, earlier), (301, self.NOW)])

        missing_since = server_config_repo.record_missing_guilds(connection, [300, 301], self.NOW)

        self.assertEqual({300: earlier, 301: self.NOW}, missing_since)

    def test_clears_servers_that_are_back_before_marking_new_ones(self):
        connection = FakeConnection(rows=[])
        server_config_repo.record_missing_guilds(connection, [300], self.NOW)

        clear, mark, _ = connection.queries
        self.assertIn("SET missing_since = NULL", clear)
        self.assertIn("NOT (guild_id = ANY", clear)
        self.assertIn("WHERE missing_since IS NULL", mark)
        self.assertEqual([([300],), (self.NOW, [300]), None], connection.parameters)

    def test_never_moves_the_date_of_a_server_already_missing(self):
        connection = FakeConnection(rows=[])
        server_config_repo.record_missing_guilds(connection, [300], self.NOW)

        self.assertIn("missing_since IS NULL", connection.queries[1])

    def test_commits_and_closes(self):
        connection = FakeConnection(rows=[])
        server_config_repo.record_missing_guilds(connection, [], self.NOW)

        self.assertEqual(1, connection.commits)
        self.assertTrue(all(cursor.closed for cursor in connection.cursors))


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



def config_row(guild_id=200, hall_of_fame_channel_id=100, channel_first=True):
    """A server_configs row in the column order the two queries select."""
    identity = [hall_of_fame_channel_id, guild_id] if channel_first else [guild_id, hall_of_fame_channel_id]
    return tuple(identity + [
        5,                          # reaction_threshold
        30,                         # post_due_date
        ["11", "12"],               # leaderboard_message_ids
        1000,                       # sweep_limit
        False,                      # sweep_limited
        True,                       # include_author_in_reaction_calculation
        False,                      # allow_messages_in_hof_channel
        True,                       # custom_emoji_check_logic
        ["👍"],                     # whitelisted_emojis
        "2024-01-01",               # joined_date
        True,                       # leaderboard_setup
        False,                      # ignore_bot_messages
        42,                         # server_member_count
        "unique_users",             # reaction_count_calculation_method
        True,                       # hide_hof_post_below_threshold
        True                        # require_image_or_video
    ])


class ServerClassMappingTests(unittest.TestCase):
    def test_get_server_classes_keys_the_result_by_guild(self):
        connection = FakeConnection(rows=[config_row(guild_id=200), config_row(guild_id=201)])
        classes = server_config_repo.get_server_classes(connection)

        self.assertEqual({200, 201}, set(classes))
        self.assertEqual(200, classes[200].guild_id)

    def test_get_server_classes_maps_every_column(self):
        connection = FakeConnection(rows=[config_row()])
        server = server_config_repo.get_server_classes(connection)[200]

        self.assertEqual(100, server.hall_of_fame_channel_id)
        self.assertEqual(5, server.reaction_threshold)
        self.assertEqual(30, server.post_due_date)
        self.assertEqual(["11", "12"], server.leaderboard_message_ids)
        self.assertEqual(["👍"], server.whitelisted_emojis)
        self.assertEqual(42, server.server_member_count)
        self.assertEqual("unique_users", server.reaction_count_calculation_method)
        self.assertTrue(server.require_image_or_video)
        self.assertTrue(server.leaderboard_setup)
        self.assertFalse(server.ignore_bot_messages)

    def test_row_to_server_class_reads_the_other_column_order(self):
        # get_all_server_configs selects guild_id first, get_server_classes selects the channel first
        server = server_config_repo.row_to_server_class(config_row(channel_first=False))

        self.assertEqual(200, server.guild_id)
        self.assertEqual(100, server.hall_of_fame_channel_id)
        self.assertEqual(["👍"], server.whitelisted_emojis)

    def test_get_all_server_configs_returns_every_row(self):
        connection = FakeConnection(rows=[config_row(guild_id=200, channel_first=False),
                                          config_row(guild_id=201, channel_first=False)])
        configs = server_config_repo.get_all_server_configs(connection)

        self.assertEqual([200, 201], [config.guild_id for config in configs])

    def test_the_mapped_config_feeds_the_reaction_helpers(self):
        connection = FakeConnection(rows=[config_row()])
        server = server_config_repo.get_server_classes(connection)[200]

        self.assertEqual({
            "reaction_count_calculation_method": "unique_users",
            "include_author_in_reaction_calculation": True,
            "custom_emoji_check_logic": True,
            "whitelisted_emojis": ["👍"]
        }, server.reaction_config())



class FailingAlterCursor:
    """A cursor whose ALTER TABLE statements fail, as on a database that refuses a column change."""

    def __init__(self):
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append(query)
        if query.strip().upper().startswith("ALTER TABLE"):
            raise RuntimeError("permission denied")

    def close(self):
        pass


class CreateTableMigrationTests(unittest.TestCase):
    def test_a_column_that_cannot_be_added_does_not_stop_the_others(self):
        """Each change is tried on its own and rolled back, so one refusal leaves the rest to run."""
        connection = FakeConnection()
        cursor = FailingAlterCursor()
        connection.cursor = lambda: cursor
        server_config_repo.create_server_config_table(connection)

        altered = [query for query in cursor.executed if "ADD COLUMN IF NOT EXISTS" in query]
        self.assertTrue(any("count_in_global_profiles" in query for query in altered))
        self.assertTrue(any("missing_since" in query for query in altered))
        self.assertEqual(len(altered), connection.rollbacks)



if __name__ == "__main__":
    unittest.main()
