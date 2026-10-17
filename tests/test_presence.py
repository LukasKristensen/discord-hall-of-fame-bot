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


def rotation(member_count, turns):
    return [main.presence_status(turn, member_count) for turn in range(turns)]


class PresenceStatusTests(unittest.TestCase):
    def test_shows_the_member_count_every_second_turn(self):
        first, second, third = messages.PRESENCE_STATUSES

        self.assertEqual(rotation(260_000, 7), [COUNT, first, COUNT, second, COUNT, third, COUNT])

    def test_starts_the_pointers_over_after_the_last(self):
        self.assertEqual(main.presence_status(7, 260_000), messages.PRESENCE_STATUSES[0])

    def test_leaves_the_count_out_before_discord_reports_one(self):
        self.assertEqual(rotation(0, 4), messages.PRESENCE_STATUSES + messages.PRESENCE_STATUSES[:1])

    def test_points_members_to_the_invite_command(self):
        self.assertTrue(any("/invite" in status for status in rotation(10, 6)))

    def test_every_status_fits_in_a_discord_status(self):
        for status in rotation(10**9, 6):
            self.assertLessEqual(len(status), 128, status)


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
