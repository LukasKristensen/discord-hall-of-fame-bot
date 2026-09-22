"""Tests for the checks on what members type into commands.

The whitelist is compared against ``str(reaction.emoji)`` on every reaction, so an entry that is not
exactly how Discord writes an emoji never matches anything, and the server quietly stops counting.
"""

import unittest

import validation


class FakeGuildEmoji:
    def __init__(self, name, emoji_id, animated=False):
        self.name = name
        self.id = emoji_id
        self.animated = animated

    def __str__(self):
        return f"<{'a' if self.animated else ''}:{self.name}:{self.id}>"


class ParseEmojiTests(unittest.TestCase):
    def assert_accepted(self, raw, expected=None, guild_emojis=()):
        emoji, error = validation.parse_emoji(raw, guild_emojis)
        self.assertIsNone(error)
        self.assertEqual(expected if expected is not None else raw, emoji)

    def assert_refused(self, raw, guild_emojis=()):
        emoji, error = validation.parse_emoji(raw, guild_emojis)
        self.assertIsNone(emoji)
        self.assertTrue(error)
        return error

    def test_accepts_a_plain_emoji(self):
        self.assert_accepted("🔥")

    def test_accepts_an_emoji_with_a_variation_selector(self):
        """❤️ is two code points, and the old length check turned it away."""
        self.assert_accepted("❤️")

    def test_accepts_an_emoji_with_a_skin_tone(self):
        self.assert_accepted("👍🏽")

    def test_accepts_a_family_joined_into_one_emoji(self):
        self.assert_accepted("👨‍👩‍👧")

    def test_accepts_a_flag(self):
        self.assert_accepted("🇩🇰")

    def test_accepts_a_subdivision_flag(self):
        self.assert_accepted("🏴󠁧󠁢󠁥󠁮󠁧󠁿")

    def test_accepts_a_keycap(self):
        self.assert_accepted("1️⃣")

    def test_accepts_a_custom_emoji(self):
        self.assert_accepted("<:pepe:123456789012345678>")

    def test_accepts_an_animated_custom_emoji(self):
        self.assert_accepted("<a:dance:123456789012345678>")

    def test_trims_surrounding_whitespace(self):
        self.assert_accepted("  🔥 ", "🔥")

    def test_looks_up_a_custom_emoji_typed_by_name(self):
        emojis = [FakeGuildEmoji("pepe", 123456789012345678)]
        self.assert_accepted(":pepe:", "<:pepe:123456789012345678>", emojis)

    def test_refuses_a_name_the_server_has_no_emoji_for(self):
        error = self.assert_refused(":nope:", [FakeGuildEmoji("pepe", 123456789012345678)])
        self.assertIn("not an emoji in this server", error)

    def test_refuses_two_emojis(self):
        error = self.assert_refused("🔥🔥")
        self.assertIn("one emoji", error)

    def test_refuses_two_flags(self):
        self.assert_refused("🇩🇰🇸🇪")

    def test_refuses_text(self):
        self.assert_refused("fire")

    def test_refuses_a_single_letter(self):
        """The old check let any single character through."""
        self.assert_refused("a")

    def test_refuses_a_bare_digit(self):
        self.assert_refused("1")

    def test_refuses_an_emoji_with_text_after_it(self):
        self.assert_refused("🔥 nice")

    def test_refuses_something_that_only_looks_like_a_custom_emoji(self):
        """The old check let anything starting with < through."""
        self.assert_refused("<not an emoji>")

    def test_refuses_nothing(self):
        self.assert_refused("   ")

    def test_refuses_a_lone_modifier(self):
        self.assert_refused("‍")


class FindInWhitelistTests(unittest.TestCase):
    def test_finds_an_exact_entry(self):
        self.assertEqual("🔥", validation.find_in_whitelist(["🔥"], "🔥"))

    def test_finds_an_entry_that_would_no_longer_pass_validation(self):
        """Otherwise an entry stored before validation existed could never be removed."""
        self.assertEqual("fire", validation.find_in_whitelist(["fire"], "fire"))

    def test_finds_a_renamed_custom_emoji_by_its_id(self):
        whitelist = ["<:old_name:123456789012345678>"]

        self.assertEqual(whitelist[0], validation.find_in_whitelist(
            whitelist, "<:new_name:123456789012345678>"))

    def test_finds_a_custom_emoji_typed_by_name(self):
        whitelist = ["<:pepe:123456789012345678>"]

        self.assertEqual(whitelist[0], validation.find_in_whitelist(
            whitelist, ":pepe:", [FakeGuildEmoji("pepe", 123456789012345678)]))

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
