import unittest

from tests.fakes import FakeConnection, FakeMessage, FakeReaction

import message_reactions
from enums import calculation_method_type


def config(method=calculation_method_type.MOST_REACTIONS_ON_EMOJI, include_author=True,
           custom_emoji_check=False, whitelist=None):
    return {
        "reaction_count_calculation_method": method,
        "include_author_in_reaction_calculation": include_author,
        "custom_emoji_check_logic": custom_emoji_check,
        "whitelisted_emojis": whitelist if whitelist is not None else []
    }


class FilterWhitelistedReactionsTests(unittest.TestCase):
    def test_returns_every_reaction_when_the_check_is_disabled(self):
        reactions = [FakeReaction("👍", [1]), FakeReaction("😂", [2])]
        self.assertEqual(reactions, message_reactions.filter_whitelisted_reactions(reactions, config(whitelist=["👍"])))

    def test_returns_every_reaction_when_the_whitelist_is_empty(self):
        reactions = [FakeReaction("👍", [1])]
        self.assertEqual(reactions, message_reactions.filter_whitelisted_reactions(
            reactions, config(custom_emoji_check=True, whitelist=[])))

    def test_keeps_only_whitelisted_emojis(self):
        whitelisted = FakeReaction("👍", [1])
        other = FakeReaction("😂", [2])
        filtered = message_reactions.filter_whitelisted_reactions(
            [whitelisted, other], config(custom_emoji_check=True, whitelist=["👍"]))
        self.assertEqual([whitelisted], filtered)

    def test_does_not_match_an_emoji_that_only_contains_a_whitelisted_one(self):
        # A skin tone variant contains the plain emoji, which used to pass the whitelist check
        variant = FakeReaction("👍🏽", [1])
        filtered = message_reactions.filter_whitelisted_reactions(
            [variant], config(custom_emoji_check=True, whitelist=["👍"]))
        self.assertEqual([], filtered)


class MostReactedEmojiTests(unittest.TestCase):
    def test_returns_an_empty_string_without_reactions(self):
        self.assertEqual("", message_reactions.most_reacted_emoji([], 1, None, config()))

    def test_returns_the_only_emoji(self):
        self.assertEqual("👍", message_reactions.most_reacted_emoji([FakeReaction("👍", [1])], 1, None, config()))

    def test_returns_the_emoji_with_the_most_reactions(self):
        reactions = [FakeReaction("👍", [1, 2]), FakeReaction("😂", [1, 2, 3]), FakeReaction("🔥", [1])]
        self.assertEqual("😂", message_reactions.most_reacted_emoji(reactions, 1, None, config()))


class TotalReactionCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_sums_every_reaction(self):
        message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 2]), FakeReaction("😂", [3])])
        self.assertEqual(3, await message_reactions.total_reaction_count(message, 1, None, config()))

    async def test_only_subtracts_the_author_vote_when_the_author_is_excluded(self):
        # The author reacted with 👍, which should cost that reaction one vote and not all of them
        message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 2, 10]), FakeReaction("😂", [3])])
        self.assertEqual(3, await message_reactions.total_reaction_count(
            message, 1, None, config(include_author=False)))


class UniqueReactorCountTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_each_user_once(self):
        message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 2]), FakeReaction("😂", [2, 3])])
        self.assertEqual(3, await message_reactions.unique_reactor_count(message, None, config()))

    async def test_ignores_the_author_when_excluded(self):
        message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 10]), FakeReaction("😂", [10])])
        self.assertEqual(1, await message_reactions.unique_reactor_count(message, None, config(include_author=False)))


class MostReactedEmojiFromMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_zero_without_reactions(self):
        self.assertEqual(0, await message_reactions.most_reacted_emoji_from_message(
            FakeMessage(author_id=10), None, config()))

    async def test_returns_the_highest_reaction_count(self):
        message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 2]), FakeReaction("😂", [1, 2, 3])])
        self.assertEqual(3, await message_reactions.most_reacted_emoji_from_message(message, None, config()))

    async def test_subtracts_the_author_when_excluded(self):
        message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 2, 10])])
        self.assertEqual(2, await message_reactions.most_reacted_emoji_from_message(
            message, None, config(include_author=False)))


class ReactionCountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.message = FakeMessage(author_id=10, reactions=[FakeReaction("👍", [1, 2]), FakeReaction("😂", [2, 3, 4])])

    async def test_uses_the_total_reactions_method(self):
        self.assertEqual(5, await message_reactions.reaction_count(
            self.message, None, config(method=calculation_method_type.TOTAL_REACTIONS)))

    async def test_uses_the_unique_users_method(self):
        self.assertEqual(4, await message_reactions.reaction_count(
            self.message, None, config(method=calculation_method_type.UNIQUE_USERS)))

    async def test_uses_the_most_reactions_on_emoji_method(self):
        self.assertEqual(3, await message_reactions.reaction_count(
            self.message, None, config(method=calculation_method_type.MOST_REACTIONS_ON_EMOJI)))

    async def test_falls_back_to_the_most_reactions_on_emoji_method(self):
        self.assertEqual(3, await message_reactions.reaction_count(self.message, None, config(method="unknown")))

    async def test_reads_the_configuration_once_when_it_is_not_supplied(self):
        connection = FakeConnection(row=(calculation_method_type.MOST_REACTIONS_ON_EMOJI, True, False, []))
        self.assertEqual(3, await message_reactions.reaction_count(self.message, connection))
        self.assertEqual(1, len(connection.queries))


if __name__ == "__main__":
    unittest.main()
