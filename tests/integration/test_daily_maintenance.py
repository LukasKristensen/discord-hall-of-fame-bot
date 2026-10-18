"""The daily task as one run, against a real PostgreSQL database.

events.daily_task strings together the leaderboard refresh, the departed-server check, the statistics
rebuild and the board permission check, all on shared connections. Each piece has its own tests; these
run the whole task over several servers and check the rows it leaves behind, including that one
server failing does not stop the rest.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import contextlib
import datetime
import unittest
from unittest import mock

import events
import utils
from repositories import hall_of_fame_message_repo, server_config_repo, server_user_repo

from tests.integration.database import DatabaseTestCase, skip_without_database
from tests.integration.discord_world import Author, Board, Bot, Guild, Post, SourceChannel, post_embed
from tests.test_server_class import build_server

LEADERBOARD_GUILD = 9001
DEPARTED = 9002
# Enough servers that one missing stays under the share that makes the departed check stand down
OTHER_GUILDS = list(range(9100, 9112))
MEMBER, OTHER_MEMBER = Author(101), Author(102)
RECENT = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=2)


@skip_without_database
class DailyMaintenanceTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.guild = Guild(LEADERBOARD_GUILD)
        self.channel = SourceChannel(500, self.guild)
        self.board = Board(600, self.guild)
        self.others = [Guild(guild_id) for guild_id in OTHER_GUILDS]
        self.other_boards = {}
        for guild in self.others:
            self.other_boards[guild.id] = Board(guild.id * 10, guild)
        self.bot = Bot(self.guild, *self.others)

        # Three leaderboard slots already on the board, which the task fills in
        slot_ids = []
        for _ in range(3):
            self.board.next_id += 1
            self.board.posts[self.board.next_id] = Post(self.board.next_id)
            slot_ids.append(self.board.next_id)
        self.slot_ids = slot_ids

        self.server_classes = {
            LEADERBOARD_GUILD: build_server(guild_id=LEADERBOARD_GUILD, hall_of_fame_channel_id=self.board.id,
                                            leaderboard_message_ids=[str(slot) for slot in slot_ids]),
            DEPARTED: build_server(guild_id=DEPARTED, hall_of_fame_channel_id=1),
            **{guild_id: build_server(guild_id=guild_id, hall_of_fame_channel_id=guild_id * 10)
               for guild_id in OTHER_GUILDS},
        }
        for guild_id in self.server_classes:
            server_config_repo.insert_server_config(self.connection, guild_id)
        server_config_repo.update_server_config_param(LEADERBOARD_GUILD, "leaderboard_setup", True, self.connection)

        # Three featured posts whose stored counts are out of date: the live reactions say otherwise
        for message_id, author, stored, live in ((1, MEMBER, 3, 9), (2, OTHER_MEMBER, 8, 4), (3, MEMBER, 5, 6)):
            message = self.channel.add(message_id, author)
            message.react("🔥", *range(1000, 1000 + live))
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, message_id, self.channel.id, LEADERBOARD_GUILD, 5000 + message_id, stored,
                author.id, RECENT)
        # The departed server's data, which must survive its first day missing
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, 50, 700, DEPARTED, 5050, 4, MEMBER.id, RECENT)

        async def no_log(*_args, **_kwargs):
            pass

        for target, name, value in ((utils, "logging", no_log), (utils, "create_embed", post_embed),
                                    (events, "permission_warnings_sent", {})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def borrow_connection(self):
        @contextlib.asynccontextmanager
        async def borrow():
            yield self.connection
        return borrow()

    async def run_task(self, dev_testing=False):
        await events.daily_task(self.bot, self.connection, self.server_classes, dev_testing, self.borrow_connection)

    def stored_counts(self):
        return dict(self.rows("SELECT message_id, reaction_count FROM hall_of_fame_message WHERE guild_id = %s",
                              (LEADERBOARD_GUILD,)))

    async def test_refreshes_the_stored_counts_from_the_live_reactions(self):
        await self.run_task()

        self.assertEqual({1: 9, 2: 4, 3: 6}, self.stored_counts())

    async def test_fills_the_leaderboard_slots_in_order(self):
        await self.run_task()

        contents = [self.board.posts[slot].content for slot in self.slot_ids]
        self.assertEqual(["**HallOfFame#1**", "**HallOfFame#2**", "**HallOfFame#3**"], contents)

    async def test_rebuilds_the_statistics_from_the_fresh_counts(self):
        await self.run_task()

        self.assertEqual({MEMBER.id: (2, 15), OTHER_MEMBER.id: (1, 4)}, {row[0]: row[1:] for row in self.rows(
            "SELECT user_id, total_hall_of_fame_messages, total_hall_of_fame_message_reactions FROM server_user "
            "WHERE guild_id = %s", (LEADERBOARD_GUILD,))})

    async def test_a_server_missing_for_a_day_is_marked_but_kept(self):
        await self.run_task()

        self.assertIsNotNone(self.rows("SELECT missing_since FROM server_configs WHERE guild_id = %s",
                                       (DEPARTED,))[0][0])
        self.assertEqual([(1,)], self.rows("SELECT COUNT(*) FROM hall_of_fame_message WHERE guild_id = %s",
                                           (DEPARTED,)))
        self.assertIn(DEPARTED, self.server_classes)

    async def test_the_development_bot_never_marks_servers_missing(self):
        await self.run_task(dev_testing=True)

        self.assertEqual([(None,)], self.rows("SELECT missing_since FROM server_configs WHERE guild_id = %s",
                                              (DEPARTED,)))

    async def test_one_server_failing_its_rebuild_does_not_stop_the_others(self):
        rebuild = server_user_repo.rebuild_user_stats_for_guild

        def fail_for_one(connection, guild_id, window_start):
            if guild_id == OTHER_GUILDS[0]:
                cursor = connection.cursor()
                cursor.execute("SELECT 1/0")
            return rebuild(connection, guild_id, window_start)

        with mock.patch.object(server_user_repo, "rebuild_user_stats_for_guild", fail_for_one):
            await self.run_task()

        self.assertEqual([(2,)], self.rows("SELECT COUNT(*) FROM server_user WHERE guild_id = %s", (LEADERBOARD_GUILD,)))

    async def test_leaves_the_connection_without_a_statement_timeout(self):
        await self.run_task()

        self.assertEqual([("0",)], self.rows("SHOW statement_timeout"))

    def break_board(self, guild_id=OTHER_GUILDS[0]):
        """Take Send Messages away on a server's board, and give it a channel the warning can go to."""
        guild = self.bot.get_guild(guild_id)
        self.other_boards[guild_id].missing_permissions = {"send_messages"}
        general = Board(guild_id * 10 + 1, guild, name="general")
        guild.text_channels = [general]
        return general

    async def test_warns_a_server_whose_board_is_missing_a_permission(self):
        general = self.break_board()
        await self.run_task()

        self.assertEqual(1, len(general.sent))
        self.assertIn("Send Messages", general.sent[0].content)

    async def test_does_not_repeat_the_warning_on_the_next_run(self):
        """Remembered in memory instead of found again by reading the channel's history."""
        general = self.break_board()
        await self.run_task()
        await self.run_task()

        self.assertEqual(1, len(general.sent))

    async def test_warns_again_once_the_board_breaks_after_being_fixed(self):
        general = self.break_board()
        await self.run_task()
        self.other_boards[OTHER_GUILDS[0]].missing_permissions = set()
        await self.run_task()
        self.other_boards[OTHER_GUILDS[0]].missing_permissions = {"send_messages"}
        await self.run_task()

        self.assertEqual(2, len(general.sent))

    async def test_a_warned_server_does_not_change_what_the_others_are_told(self):
        first = self.break_board(OTHER_GUILDS[0])
        await self.run_task()
        second = self.break_board(OTHER_GUILDS[1])
        await self.run_task()

        self.assertEqual(1, len(first.sent))
        self.assertEqual(1, len(second.sent))

    async def test_the_warning_leaves_the_stored_rows_alone(self):
        await self.run_task()
        before = (self.stored_counts(), self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id"))
        self.break_board()
        await self.run_task()

        self.assertEqual(before, (self.stored_counts(),
                                  self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id")))

    async def test_running_twice_gives_the_same_result(self):
        await self.run_task()
        once = (self.stored_counts(), self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id"))
        await self.run_task()

        self.assertEqual(once, (self.stored_counts(), self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id")))


if __name__ == "__main__":
    unittest.main()
