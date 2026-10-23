"""Tests for the bot's rotating status.

The presence is seen by every member who opens a member list in any of the bot's servers, so it
takes turns between the member count and pointers to commands, /invite among them.
"""

import unittest
from unittest import mock

import main
from translations import messages

from tests.test_main import MainTestCase


COUNT = "🏆 Hall of Fame - 260,000 users"
NOVEMBER, DECEMBER, JANUARY, FEBRUARY = 11, 12, 1, 2


def rotation(member_count, turns, month=None):
    return [main.presence_status(turn, member_count, month) for turn in range(turns)]


class PresenceStatusTests(unittest.TestCase):
    def test_shows_the_member_count_every_second_turn(self):
        invite, leaderboard = messages.PRESENCE_STATUSES

        self.assertEqual(rotation(260_000, 5, NOVEMBER), [COUNT, invite, COUNT, leaderboard, COUNT])

    def test_starts_the_pointers_over_after_the_last(self):
        self.assertEqual(main.presence_status(5, 260_000, NOVEMBER), messages.PRESENCE_STATUSES[0])

    def test_leaves_the_count_out_before_discord_reports_one(self):
        self.assertEqual(rotation(0, 3, NOVEMBER), messages.PRESENCE_STATUSES + messages.PRESENCE_STATUSES[:1])

    def test_points_members_to_the_invite_command(self):
        self.assertTrue(any("/invite" in status for status in rotation(10, 4, NOVEMBER)))

    def test_every_status_fits_in_a_discord_status(self):
        for status in rotation(10**9, 6, DECEMBER):
            self.assertLessEqual(len(status), 128, status)


class WrappedSeasonTests(unittest.TestCase):
    def test_points_to_wrapped_in_december(self):
        invite, leaderboard = messages.PRESENCE_STATUSES

        self.assertEqual(rotation(260_000, 6, DECEMBER),
                         [COUNT, invite, COUNT, leaderboard, COUNT, messages.PRESENCE_WRAPPED])

    def test_points_to_wrapped_in_january(self):
        self.assertIn(messages.PRESENCE_WRAPPED, rotation(260_000, 6, JANUARY))

    def test_leaves_wrapped_out_for_the_rest_of_the_year(self):
        for month in (FEBRUARY, NOVEMBER):
            self.assertNotIn(messages.PRESENCE_WRAPPED, rotation(260_000, 12, month), month)

    def test_points_to_wrapped_before_discord_reports_a_count(self):
        self.assertIn(messages.PRESENCE_WRAPPED, rotation(0, 3, DECEMBER))


class RotatePresenceTests(MainTestCase):
    def setUp(self):
        super().setUp()
        self.change_presence = mock.AsyncMock()
        self.patch(main.bot, "change_presence", self.change_presence)
        self.patch(main, "presence_index", 0)
        self.patch(main, "total_member_count", 500)

    def shown(self):
        return [call.kwargs["activity"].name for call in self.change_presence.await_args_list]

    async def test_shows_each_status_in_turn_and_starts_over(self):
        for _ in range(7):
            await main.rotate_presence()

        self.assertEqual(self.shown(), rotation(500, 7))

    async def test_shows_the_latest_member_count(self):
        await main.adjust_total_member_count(250)
        await main.rotate_presence()

        self.assertEqual(self.shown(), ["🏆 Hall of Fame - 750 users"])

    async def test_a_server_joining_does_not_change_the_presence_itself(self):
        self.patch(main, "bot_loaded", True)

        await main.adjust_total_member_count(100)

        self.change_presence.assert_not_awaited()

    async def test_servers_joining_and_leaving_keep_the_rotation_in_step(self):
        self.patch(main, "bot_loaded", True)

        await main.rotate_presence()
        await main.adjust_total_member_count(100)
        await main.adjust_total_member_count(-40)
        await main.rotate_presence()

        self.assertEqual(self.shown(), [main.presence_status(0, 500), messages.PRESENCE_STATUSES[0]])

    async def test_a_failed_change_is_logged_and_the_rotation_moves_on(self):
        self.change_presence.side_effect = RuntimeError("rate limited")

        await main.rotate_presence()

        self.assertEqual(main.presence_index, 1)
        self.assertTrue(any("rate limited" in line for line in self.logged))


if __name__ == "__main__":
    unittest.main()
