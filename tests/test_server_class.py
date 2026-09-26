import unittest

from classes.server_class import Server
from enums import calculation_method_type
from repositories import server_config_repo


def build_server(**overrides):
    arguments = {
        "hall_of_fame_channel_id": 100,
        "guild_id": 200,
        "reaction_threshold": 5,
        "post_due_date": 30,
        "sweep_limit": 1000,
        "sweep_limited": False,
        "include_author_in_reaction_calculation": True,
        "allow_messages_in_hof_channel": False,
        "custom_emoji_check_logic": False,
        "whitelisted_emojis": [],
        "leaderboard_setup": False,
        "ignore_bot_messages": False,
        "reaction_count_calculation_method": calculation_method_type.MOST_REACTIONS_ON_EMOJI,
        "hide_hof_post_below_threshold": True,
        "leaderboard_message_ids": [],
        "server_member_count": 42,
        "require_image_or_video": False
    }
    arguments.update(overrides)
    return Server(**arguments)


class ReactionConfigTests(unittest.TestCase):
    def test_exposes_the_values_used_for_counting(self):
        server = build_server(include_author_in_reaction_calculation=False, custom_emoji_check_logic=True,
                              whitelisted_emojis=["👍"],
                              reaction_count_calculation_method=calculation_method_type.UNIQUE_USERS)

        self.assertEqual({
            "reaction_count_calculation_method": calculation_method_type.UNIQUE_USERS,
            "include_author_in_reaction_calculation": False,
            "custom_emoji_check_logic": True,
            "whitelisted_emojis": ["👍"]
        }, server.reaction_config())

    def test_matches_the_columns_the_repository_reads(self):
        # Guards against the in memory config drifting away from the database fallback
        self.assertEqual(set(server_config_repo.REACTION_CONFIG_COLUMNS), set(build_server().reaction_config()))

    def test_reflects_a_configuration_change_without_a_new_lookup(self):
        server = build_server()
        server.whitelisted_emojis = ["🔥"]
        server.custom_emoji_check_logic = True

        self.assertEqual(["🔥"], server.reaction_config()["whitelisted_emojis"])
        self.assertTrue(server.reaction_config()["custom_emoji_check_logic"])


class LeaderboardMessageIdsTests(unittest.TestCase):
    def test_defaults_to_an_empty_list(self):
        self.assertEqual([], build_server(leaderboard_message_ids=None).leaderboard_message_ids)

    def test_keeps_the_supplied_ids(self):
        self.assertEqual([1, 2], build_server(leaderboard_message_ids=[1, 2]).leaderboard_message_ids)


if __name__ == "__main__":
    unittest.main()
