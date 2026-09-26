"""Tests for the checks on what members type into commands.

The whitelist is compared against ``str(reaction.emoji)`` on every reaction, so an entry that is not
exactly how Discord writes an emoji never matches anything, and the server quietly stops counting.
/whitelist_emoji does not try to catch that up front: whatever a member sends is trimmed and stored
as-is, and an entry that never matches a reaction just never fires.
"""

import unittest

import validation


class NormalizeEmojiTests(unittest.TestCase):
    def test_trims_surrounding_whitespace(self):
        self.assertEqual("🔥", validation.normalize_emoji("  🔥 "))

    def test_passes_a_custom_emoji_through_unchanged(self):
        self.assertEqual("<:pepe:123456789012345678>", validation.normalize_emoji("<:pepe:123456789012345678>"))

    def test_passes_arbitrary_text_through_unchanged(self):
        """Not a real emoji, but that is for the reaction matching to quietly ignore, not this."""
        self.assertEqual("fire", validation.normalize_emoji("fire"))

    def test_refuses_nothing(self):
        self.assertIsNone(validation.normalize_emoji("   "))

    def test_refuses_none(self):
        self.assertIsNone(validation.normalize_emoji(None))


class FindInWhitelistTests(unittest.TestCase):
    def test_finds_an_exact_entry(self):
        self.assertEqual("🔥", validation.find_in_whitelist(["🔥"], "🔥"))

    def test_finds_an_entry_by_trimming_the_input(self):
        self.assertEqual("fire", validation.find_in_whitelist(["fire"], "  fire  "))

    def test_finds_a_renamed_custom_emoji_by_its_id(self):
        whitelist = ["<:old_name:123456789012345678>"]

        self.assertEqual(whitelist[0], validation.find_in_whitelist(
            whitelist, "<:new_name:123456789012345678>"))

    def test_reports_an_emoji_that_is_not_there(self):
        self.assertIsNone(validation.find_in_whitelist(["🔥"], "😂"))


class OutOfRangeMessageTests(unittest.TestCase):
    def test_accepts_the_bounds_themselves(self):
        self.assertIsNone(validation.out_of_range_message("X", 1, 1, 10))
        self.assertIsNone(validation.out_of_range_message("X", 10, 1, 10))

    def test_names_the_bounds_when_refusing(self):
        self.assertEqual("X must be between 1 and 10, but got 11.",
                         validation.out_of_range_message("X", 11, 1, 10))


if __name__ == "__main__":
    unittest.main()
