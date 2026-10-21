"""Generating Hall of Fame Wrapped, against a real PostgreSQL database.

hof_wrapped.main reads a server's posts, counts who reacted to whom, and saves a Wrapped row per
member. It is switched off at the moment, so these tests are what says it still works before it is
switched back on for December. Discord is faked; the rows it reads and writes are real.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import json
import types
import unittest
from unittest import mock

import hof_wrapped
import main
import utils
from constants import version
from repositories import hall_of_fame_message_repo, hof_wrapped_repo, opt_out_repo, server_config_repo

from tests.integration.database import DatabaseTestCase, SingleConnectionPool, database_url, skip_without_database
from tests.integration.discord_world import Author, Bot, Guild, SourceChannel

FIRST, SECOND = 9001, 9002
ALICE, BOB, CAROL, DAVE = Author(101), Author(102), Author(103), Author(104)
IN_THE_YEAR = datetime.datetime(version.WRAPPED_YEAR, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)
YEAR_BEFORE = datetime.datetime(version.WRAPPED_YEAR - 1, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)


@skip_without_database
class WrappedTestCase(DatabaseTestCase):
    """Two servers of fake Discord messages and their posts, with Wrapped writing to this test's schema."""

    def setUp(self):
        super().setUp()
        self.first = Guild(FIRST)
        self.first_channel = SourceChannel(500, self.first)
        self.second = Guild(SECOND)
        self.second_channel = SourceChannel(800, self.second)
        self.bot = Bot(self.first, self.second)
        for guild_id in (FIRST, SECOND):
            server_config_repo.insert_server_config(self.connection, guild_id)

        # FIRST: Alice has two posts, Bob one. Carol reacts but never posts, so she has no Wrapped
        self.feature(self.first_channel, 1, ALICE, {"🔥": [BOB.id, CAROL.id]})
        self.feature(self.first_channel, 2, ALICE, {"😂": [BOB.id]})
        self.feature(self.first_channel, 3, BOB, {"🔥": [ALICE.id]})
        # A post from the year before, which this year's Wrapped leaves out
        self.feature(self.first_channel, 4, BOB, {"🔥": [ALICE.id]}, created_at=YEAR_BEFORE)
        # SECOND: only Dave
        self.feature(self.second_channel, 10, DAVE, {"🔥": [ALICE.id]})

        settings = {"dsn": database_url(), "options": f"-c search_path={self.schema} -c TimeZone=UTC"}
        for target, name, value in ((hof_wrapped.environment, "database_settings", lambda: settings),
                                    (hof_wrapped, "users", {}), (hof_wrapped, "total_hall_of_fame_posts", 0),
                                    (hof_wrapped, "rankings", None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def feature(self, channel, message_id, author, reactions, created_at=IN_THE_YEAR):
        message = channel.add(message_id, author, created_at=created_at)
        for emoji, user_ids in reactions.items():
            message.react(emoji, *user_ids)
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, message_id, channel.id, channel.guild.id, 5000 + message_id, 2, author.id,
            created_at.replace(tzinfo=None))

    async def generate(self, guild_id):
        with mock.patch("builtins.print"):
            await hof_wrapped.main(guild_id, self.bot, 3, self.connection)

    def wrapped(self, guild_id, user_id):
        row = hof_wrapped_repo.get_hof_wrapped(self.connection, guild_id, user_id, version.WRAPPED_YEAR)
        if row is None:
            return None
        for column in ("fan_of_users", "users_fans", "most_used_channels", "most_used_emojis", "user_ranks"):
            row[column] = json.loads(row[column])
        return row


class WrappedGenerationTests(WrappedTestCase):
    async def test_saves_a_wrapped_for_every_member_who_was_featured(self):
        await self.generate(FIRST)

        self.assertEqual({ALICE.id, BOB.id}, {row[0] for row in self.rows(
            "SELECT user_id FROM hof_wrapped WHERE guild_id = %s", (FIRST,))})

    async def test_counts_each_members_posts_this_year(self):
        await self.generate(FIRST)

        self.assertEqual(2, self.wrapped(FIRST, ALICE.id)["hof_message_posts"])
        self.assertEqual(1, self.wrapped(FIRST, BOB.id)["hof_message_posts"])

    async def test_records_who_reacted_to_whom(self):
        """Carol never posted, so she is not counted as anyone's fan."""
        await self.generate(FIRST)

        self.assertEqual({str(BOB.id): 2}, self.wrapped(FIRST, ALICE.id)["users_fans"])
        self.assertEqual({str(BOB.id): 1}, self.wrapped(FIRST, ALICE.id)["fan_of_users"])
        self.assertEqual({str(ALICE.id): 1}, self.wrapped(FIRST, BOB.id)["users_fans"])

    async def test_records_the_channels_posts_came_from(self):
        await self.generate(FIRST)

        self.assertEqual({str(self.first_channel.id): 2}, self.wrapped(FIRST, ALICE.id)["most_used_channels"])

    async def test_ranks_the_members(self):
        await self.generate(FIRST)

        self.assertEqual(1, self.wrapped(FIRST, ALICE.id)["user_ranks"]["hallOfFameMessagePosts"])
        self.assertEqual(2, self.wrapped(FIRST, BOB.id)["user_ranks"]["hallOfFameMessagePosts"])

    async def test_a_second_server_gets_only_its_own_members(self):
        """Wrapped runs server after server in one process, so nothing may carry over between them."""
        await self.generate(FIRST)
        await self.generate(SECOND)

        self.assertEqual({DAVE.id}, {row[0] for row in self.rows(
            "SELECT user_id FROM hof_wrapped WHERE guild_id = %s", (SECOND,))})
        self.assertEqual(1, self.wrapped(SECOND, DAVE.id)["hof_message_posts"])

    async def test_the_first_server_is_unchanged_by_the_second(self):
        await self.generate(FIRST)
        before = self.rows("SELECT * FROM hof_wrapped WHERE guild_id = %s ORDER BY user_id", (FIRST,))
        await self.generate(SECOND)

        self.assertEqual(before, self.rows("SELECT * FROM hof_wrapped WHERE guild_id = %s ORDER BY user_id", (FIRST,)))

    async def test_generating_again_replaces_rather_than_duplicates(self):
        await self.generate(FIRST)
        await self.generate(FIRST)

        self.assertEqual([(2,)], self.rows("SELECT COUNT(*) FROM hof_wrapped WHERE guild_id = %s", (FIRST,)))
        self.assertEqual(2, self.wrapped(FIRST, ALICE.id)["hof_message_posts"])

    async def test_a_deleted_member_is_not_generated_again(self):
        """After deleting their data the member's posts have no author, so Wrapped has nobody to credit."""
        hall_of_fame_message_repo.remove_author(self.connection, ALICE.id)
        await self.generate(FIRST)

        self.assertIsNone(self.wrapped(FIRST, ALICE.id))

    async def delete_while_reading(self, member):
        """Run Wrapped with the member deleting their data after the posts were read"""
        read_posts = hof_wrapped.process_hof_messages_from_db

        async def read_then_delete(guild, connection):
            result = await read_posts(guild, connection)
            hall_of_fame_message_repo.remove_author(self.connection, member.id)
            return result

        with mock.patch.object(hof_wrapped, "process_hof_messages_from_db", read_then_delete):
            await self.generate(FIRST)

    async def test_a_member_who_deletes_while_wrapped_runs_is_not_saved(self):
        await self.delete_while_reading(BOB)

        self.assertIsNone(self.wrapped(FIRST, BOB.id))

    async def test_a_member_who_deletes_while_wrapped_runs_leaves_every_fan_list(self):
        await self.delete_while_reading(BOB)

        alice = self.wrapped(FIRST, ALICE.id)
        self.assertEqual({}, alice["users_fans"])
        self.assertEqual({}, alice["fan_of_users"])

    async def delete_while_saving(self, member):
        """
        Run Wrapped with the member deleting their data right after the first row is saved. Whichever row
        that is, the row saved after the deletion would bring them back: their own, or Alice's with them in
        its fan lists
        """
        save = hof_wrapped.save_user_wrapped_to_db
        saved = []

        def save_then_delete(guild_id, user, year):
            save(guild_id, user, year)
            saved.append(user.id)
            if len(saved) == 1:
                # What deleting their data on /my_data does to posts and Wrapped
                hall_of_fame_message_repo.remove_author(self.connection, member.id)
                hof_wrapped_repo.delete_hof_wrapped_for_user(self.connection, member.id)

        with mock.patch.object(hof_wrapped, "save_user_wrapped_to_db", save_then_delete):
            await self.generate(FIRST)
        self.assertEqual(2, len(saved))

    async def test_a_member_who_deletes_while_rows_are_saved_keeps_no_row(self):
        await self.delete_while_saving(BOB)

        self.assertIsNone(self.wrapped(FIRST, BOB.id))

    async def test_a_member_who_deletes_while_rows_are_saved_leaves_every_fan_list(self):
        await self.delete_while_saving(BOB)

        alice = self.wrapped(FIRST, ALICE.id)
        self.assertEqual({}, alice["users_fans"])
        self.assertEqual({}, alice["fan_of_users"])

    async def test_a_member_who_deletes_is_not_ranked(self):
        """Bob is first with Alice gone, rather than ranked against a member who is not saved."""
        await self.delete_while_reading(ALICE)

        self.assertEqual(1, self.wrapped(FIRST, BOB.id)["user_ranks"]["hallOfFameMessagePosts"])

    async def test_a_member_who_asked_not_to_be_featured_gets_no_wrapped(self):
        """Their earlier posts stay, but a Wrapped would record whose posts they reacted to."""
        opt_out_repo.set_opted_out(self.connection, BOB.id, True)
        await self.generate(FIRST)

        self.assertIsNone(self.wrapped(FIRST, BOB.id))

    async def test_a_member_who_asked_not_to_be_featured_is_in_nobodys_fan_lists(self):
        opt_out_repo.set_opted_out(self.connection, BOB.id, True)
        await self.generate(FIRST)

        alice = self.wrapped(FIRST, ALICE.id)
        self.assertEqual({}, alice["users_fans"])
        self.assertEqual({}, alice["fan_of_users"])

    async def test_a_member_who_asked_not_to_be_featured_is_not_ranked(self):
        opt_out_repo.set_opted_out(self.connection, ALICE.id, True)
        await self.generate(FIRST)

        self.assertEqual(1, self.wrapped(FIRST, BOB.id)["user_ranks"]["hallOfFameMessagePosts"])


class OptedOutFriendTests(WrappedTestCase):
    """
    A member's friends asking not to be featured: Alice and Bob react to each other's posts, and Alice also
    reacts to Dave's post in the second server. Whoever opts out must vanish from the others' Wrapped, from
    the day they ask, including a Wrapped generated before they asked
    """

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(main, "connection_pool", SingleConnectionPool(self.connection))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def as_member(author):
        return types.SimpleNamespace(id=author.id, mention=f"<@{author.id}>", avatar=None)

    async def shown_to(self, author, guild_id=FIRST):
        """Everything /hof_wrapped shows the member, as one text"""
        row = hof_wrapped_repo.get_hof_wrapped(self.connection, guild_id, author.id, version.WRAPPED_YEAR)
        embed = await hof_wrapped.create_embed(self.as_member(author), row, self.bot)
        return " ".join([embed.description or ""] + [f"{field.name} {field.value}" for field in embed.fields])

    async def test_a_friend_who_opts_out_after_wrapped_vanishes_from_the_stored_fan_lists(self):
        await self.generate(FIRST)
        self.assertIn(str(BOB.id), self.wrapped(FIRST, ALICE.id)["users_fans"])
        await main.stop_featuring_member(BOB.id)

        alice = self.wrapped(FIRST, ALICE.id)
        self.assertEqual({}, alice["users_fans"])
        self.assertEqual({}, alice["fan_of_users"])

    async def test_a_friend_who_opts_out_after_wrapped_is_not_shown_in_it(self):
        await self.generate(FIRST)
        await main.stop_featuring_member(BOB.id)

        self.assertNotIn(f"<@{BOB.id}>", await self.shown_to(ALICE))

    async def test_their_reactions_no_longer_count_as_received(self):
        await self.generate(FIRST)
        await main.stop_featuring_member(BOB.id)

        self.assertIn("0 reactions on your HOF posts", await self.shown_to(ALICE))

    async def test_their_own_earlier_wrapped_stays_for_them(self):
        """Like the rest of their earlier data, until they delete it."""
        await self.generate(FIRST)
        await main.stop_featuring_member(BOB.id)

        self.assertIsNotNone(self.wrapped(FIRST, BOB.id))

    async def test_the_servers_wrapped_leaves_them_out(self):
        await self.generate(FIRST)
        await main.stop_featuring_member(BOB.id)
        rows = hof_wrapped_repo.get_all_hof_wrapped_for_guild(self.connection, FIRST, version.WRAPPED_YEAR)
        embed = hof_wrapped.create_server_embed(types.SimpleNamespace(id=FIRST, name="First", icon=None), rows)
        shown = " ".join([embed.description or ""] + [f"{field.name} {field.value}" for field in embed.fields])

        self.assertEqual([ALICE.id], [row["user_id"] for row in rows])
        self.assertNotIn(f"<@{BOB.id}>", shown)
        self.assertIn(f"<@{ALICE.id}>", shown)

    async def test_a_friend_who_opts_out_while_wrapped_runs_is_left_out(self):
        read_posts = hof_wrapped.process_hof_messages_from_db

        async def read_then_opt_out(guild, connection):
            result = await read_posts(guild, connection)
            opt_out_repo.set_opted_out(self.connection, BOB.id, True)
            return result

        with mock.patch.object(hof_wrapped, "process_hof_messages_from_db", read_then_opt_out):
            await self.generate(FIRST)

        self.assertIsNone(self.wrapped(FIRST, BOB.id))
        self.assertEqual({}, self.wrapped(FIRST, ALICE.id)["users_fans"])

    async def test_a_friend_who_opted_out_is_left_out_in_every_server(self):
        """Alice reacted to Dave's post in the second server, where she never posted herself."""
        await self.generate(SECOND)
        self.assertEqual({}, self.wrapped(SECOND, DAVE.id)["users_fans"])

        self.feature(self.second_channel, 11, ALICE, {"🔥": [DAVE.id]})
        opt_out_repo.set_opted_out(self.connection, ALICE.id, True)
        await self.generate(SECOND)

        self.assertIsNone(self.wrapped(SECOND, ALICE.id))
        self.assertEqual({}, self.wrapped(SECOND, DAVE.id)["fan_of_users"])

    async def test_featuring_again_puts_them_back_in_the_next_wrapped(self):
        await main.stop_featuring_member(BOB.id)
        opt_out_repo.set_opted_out(self.connection, BOB.id, False)
        await self.generate(FIRST)

        self.assertEqual({str(BOB.id): 2}, self.wrapped(FIRST, ALICE.id)["users_fans"])


if __name__ == "__main__":
    unittest.main()
