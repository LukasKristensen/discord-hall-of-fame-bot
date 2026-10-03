import unittest

from caches import ExpiringSet


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ExpiringSetTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.entries = ExpiringSet(ttl_seconds=60, time_source=self.clock)

    def test_a_new_value_is_accepted(self):
        self.assertTrue(self.entries.add_if_absent("first"))

    def test_a_repeated_value_is_rejected_within_the_window(self):
        self.entries.add_if_absent("first")
        self.clock.advance(59)
        self.assertFalse(self.entries.add_if_absent("first"))

    def test_a_repeated_value_is_accepted_again_after_the_window(self):
        self.entries.add_if_absent("first")
        self.clock.advance(60)
        self.assertTrue(self.entries.add_if_absent("first"))

    def test_values_expire_independently(self):
        self.entries.add_if_absent("first")
        self.clock.advance(30)
        self.entries.add_if_absent("second")
        self.clock.advance(31)

        self.assertNotIn("first", self.entries)
        self.assertIn("second", self.entries)

    def test_different_values_do_not_block_each_other(self):
        self.assertTrue(self.entries.add_if_absent("first"))
        self.assertTrue(self.entries.add_if_absent("second"))

    def test_expired_values_are_dropped_from_the_set(self):
        self.entries.add_if_absent("first")
        self.entries.add_if_absent("second")
        self.assertEqual(2, len(self.entries))

        self.clock.advance(61)
        self.assertEqual(0, len(self.entries))


if __name__ == "__main__":
    unittest.main()
