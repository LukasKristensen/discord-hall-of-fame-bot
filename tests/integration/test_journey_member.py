"""Member journeys: a message climbing onto the board and off it, and the commands members use.

Each test is one member's path from start to end through main's own handlers, with Discord faked and the
database real, and checks what the members see at every step. See tests/JOURNEYS.md.
"""

import datetime
import json
import types
import unittest
from unittest import mock

import hof_wrapped
import main
from constants import version
from enums import command_refs
from repositories import hall_of_fame_message_repo, hof_wrapped_repo
from translations import messages

from tests.integration.database import database_url, skip_without_database
from tests.integration.discord_world import Author, Board, Guild, post_text
from tests.integration.journeys import AUTHOR, FANS, GUILD, JourneyTestCase

SECOND_AUTHOR = Author(2002)


def opening(template):
    """The fixed start of a message template, for answers that fill in values after it"""
    return template.split("{")[0]


@skip_without_database
class BoardLifeTests(JourneyTestCase):
    async def why(self, message, asked_by):
        interaction = self.command(asked_by)
        await main.why_not_on_board.callback(interaction, message)
        self.assertTrue(interaction.last.ephemeral, "only the member who asked sees the answer")
        return interaction.last.content

    async def test_a_message_reaches_the_board_hides_and_comes_back(self):
        await self.set_up(threshold=3)
        message = self.general.add(1, AUTHOR)

        # Two reactions: not yet, and Why says how far it is
        await self.react(message, *FANS[:2])
        self.assertEqual([], self.reposts())
        self.assertIn(messages.WHY_BELOW_THRESHOLD.format(count=2, threshold=3), await self.why(message, FANS[0]))

        # The third posts it, once, credited to the author, and nobody is pinged
        await self.react(message, FANS[2])
        [post] = self.reposts()
        self.assertEqual(AUTHOR.id, self.stored(message)["author_id"])
        self.assertIn(message.content, post_text(post))
        self.assertIn("🔥 3", post_text(post))
        self.assertEqual({"parse": []}, post.allowed_mentions.to_dict())
        self.assertIn(opening(messages.WHY_ALREADY_POSTED), await self.why(message, FANS[1]))

        # More reactions update the same post
        await self.react(message, FANS[3], FANS[4])
        self.assertEqual(1, len(self.reposts()))
        self.assertIn("🔥 5", post_text(post))
        self.assertEqual(5, self.stored(message)["reaction_count"])

        # Down to two: hidden in place, the row kept
        await self.unreact(message, FANS[0], FANS[1], FANS[2])
        self.assertNotIn(message.content, post_text(post))
        self.assertIsNotNone(self.stored(message))
        self.assertIn(messages.WHY_HIDDEN.format(count=2, threshold=3), await self.why(message, FANS[2]))

        # Back over: the same post shows again with the new count
        await self.react(message, FANS[5], FANS[6])
        self.assertEqual([post], self.reposts())
        self.assertIn("🔥 4", post_text(post))
        self.assertEqual(4, self.stored(message)["reaction_count"])
        self.assert_no_errors_logged()

    async def test_asking_why_twice_in_a_row_is_refused_for_a_few_seconds(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)

        await self.why(message, FANS[0])
        again = self.command(FANS[0])
        await main.why_not_on_board.callback(again, message)

        self.assertEqual(messages.WHY_ON_COOLDOWN, again.last.content)
        self.assertIn(opening(messages.WHY_BELOW_THRESHOLD), await self.why(message, FANS[1]))

    async def test_reactions_from_bots_and_on_the_board_itself_are_left_out(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:2], Author(6000, bot=True))
        self.assertEqual([], self.reposts(), "another bot's reaction does not tip it over")

        await self.react(message, FANS[2])
        [post] = self.reposts()
        # Members react to the post itself, which is never featured again
        repost = self.board.posts[post.id]
        on_board = types.SimpleNamespace(id=repost.id, channel=self.board, guild=self.guild)
        for fan in FANS[:5]:
            await main.on_raw_reaction_add(types.SimpleNamespace(channel_id=self.board.id, message_id=on_board.id,
                                                                 guild_id=GUILD, user_id=fan.id, member=fan))
        self.assertEqual(1, len(self.reposts()))
        self.assertEqual(messages.WHY_IS_BOARD, await self.why(on_board, FANS[3]))

    async def test_an_edited_message_shows_its_new_text_with_the_next_reaction(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        post = self.post_of(message)

        message.content = "edited: even funnier now"
        await self.react(message, FANS[3])

        self.assertIn("edited: even funnier now", post_text(post))
        self.assertIn("🔥 4", post_text(post))

    async def test_a_featured_message_that_is_deleted_leaves_its_post(self):
        """Discord sends the bot nothing it acts on for a deleted message, so the post and its row stay"""
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        post = self.post_of(message)

        self.general.delete(message.id)
        # A reaction removed from a message as it is deleted still reaches the bot
        await self.unreact(message, FANS[0])

        self.assertTrue(main.utils.post_shows(post))
        self.assertEqual(3, self.stored(message)["reaction_count"])
        self.assertEqual(messages.WHY_MESSAGE_GONE, await self.why(message, FANS[1]))
        self.assert_no_errors_logged()

    async def test_a_post_a_moderator_deleted_is_not_posted_again_but_keeps_counting(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        await self.post_of(message).delete()

        await self.react(message, FANS[3], FANS[4])

        self.assertEqual(1, len(self.reposts()))
        self.assertEqual(5, self.stored(message)["reaction_count"],
                         "the leaderboards and profiles read the stored count")
        self.assertIn(opening(messages.WHY_POSTED_ELSEWHERE), await self.why(message, FANS[0]))


@skip_without_database
class LeaderboardAndProfileTests(JourneyTestCase):
    async def feature_some_posts(self):
        await self.set_up()
        self.guild.members = {AUTHOR.id: AUTHOR, SECOND_AUTHOR.id: SECOND_AUTHOR}
        for message_id, author, fans in ((1, AUTHOR, 4), (2, AUTHOR, 3), (3, SECOND_AUTHOR, 5)):
            await self.react(self.general.add(message_id, author), *FANS[:fans])

    async def run_daily_task(self):
        with mock.patch("builtins.print"):
            await main.daily_task.coro()

    async def test_the_leaderboard_after_the_daily_update(self):
        await self.feature_some_posts()
        await self.run_daily_task()

        board = self.command(FANS[0])
        await main.leaderboard.callback(board)
        shown = board.last.text()
        self.assertFalse(board.last.ephemeral)
        self.assertLess(shown.index(f"1. {AUTHOR.name}: 2 messages"), shown.index(f"2. {SECOND_AUTHOR.name}: 1 messages"))

        # Once a day per member
        again = self.command(FANS[0])
        await main.leaderboard.callback(again)
        self.assertEqual(messages.COMMAND_ON_COOLDOWN, again.last.content)
        self.assertTrue(again.last.ephemeral)

        # The next daily task lifts it
        await self.run_daily_task()
        tomorrow = self.command(FANS[0])
        await main.leaderboard.callback(tomorrow)
        self.assertIsNotNone(tomorrow.last.embed)
        self.assert_no_errors_logged()

    async def test_a_member_looks_up_their_profile_and_someone_elses(self):
        await self.feature_some_posts()
        await self.run_daily_task()

        own = self.command(AUTHOR)
        await main.user_server_profile.callback(own, None)
        self.assertFalse(own.last.ephemeral)
        self.assertIn(AUTHOR.name, own.last.text())

        other = self.command(FANS[0])
        await main.user_server_profile.callback(other, SECOND_AUTHOR)
        self.assertIn(SECOND_AUTHOR.name, other.last.text())

        never = self.command(FANS[0])
        await main.user_server_profile.callback(never, FANS[1])
        self.assertEqual(messages.PROFILE_NO_DATA, never.last.content)

        robot = self.command(FANS[0])
        await main.user_server_profile.callback(robot, Author(6000, bot=True))
        self.assertEqual(messages.PROFILE_BOT_USER, robot.last.content)
        self.assertTrue(robot.last.ephemeral)

    async def test_a_profile_before_the_daily_update(self):
        """Statistics are rebuilt daily, so a member featured today is told when to look again"""
        await self.feature_some_posts()

        own = self.command(AUTHOR)
        await main.user_server_profile.callback(own, None)

        self.assertEqual(messages.PROFILE_NO_DATA, own.last.content)


@skip_without_database
class WrappedTests(JourneyTestCase):
    def setUp(self):
        super().setUp()
        settings = {"dsn": database_url(), "options": f"-c search_path={self.schema} -c TimeZone=UTC"}
        for target, name, value in ((hof_wrapped.environment, "database_settings", lambda: settings),
                                    (hof_wrapped, "users", {}), (hof_wrapped, "total_hall_of_fame_posts", 0),
                                    (hof_wrapped, "rankings", None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def generate(self):
        with mock.patch("builtins.print"):
            await hof_wrapped.main(GUILD, self.bot, self.config.reaction_threshold, self.connection)

    async def test_wrapped_before_and_after_it_is_made(self):
        await self.set_up()
        in_the_year = datetime.datetime(version.WRAPPED_YEAR, 6, 1, tzinfo=datetime.timezone.utc)
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        # A fan who was featured too, since Wrapped's fan lists only name members who have a Wrapped of their own
        fans_own = self.general.add(2, FANS[0])
        await self.react(fans_own, *FANS[1:4])
        # Wrapped covers the posts of its year
        self.execute("UPDATE hall_of_fame_message SET created_at = %s", (in_the_year.replace(tzinfo=None),))
        message.created_at = fans_own.created_at = in_the_year

        not_yet = self.command(AUTHOR)
        await main.server_hof_wrapped_command.callback(not_yet)
        self.assertEqual(opening(messages.WRAPPED_NONE_FOR_SERVER).format(year=version.WRAPPED_YEAR),
                         not_yet.last.content[:len(opening(messages.WRAPPED_NONE_FOR_SERVER).format(
                             year=version.WRAPPED_YEAR))])
        self.assertTrue(not_yet.last.ephemeral)

        await self.generate()

        own = self.command(AUTHOR)
        await main.hof_wrapped_command.callback(own)
        self.assertIsNotNone(own.last.embed)
        self.assertFalse(own.last.ephemeral)
        self.assertIn("1 posts", own.last.text())

        fan = self.command(FANS[4])
        await main.hof_wrapped_command.callback(fan)
        self.assertTrue(fan.last.ephemeral, "a member never featured is told privately")
        self.assertIn("not in this server's Hall of Fame Wrapped", fan.last.content)

        server = self.command(FANS[0])
        await main.server_hof_wrapped_command.callback(server)
        self.assertIsNotNone(server.last.embed)
        fans = json.loads(hof_wrapped_repo.get_hof_wrapped(self.connection, GUILD, AUTHOR.id,
                                                           version.WRAPPED_YEAR)["users_fans"])
        self.assertEqual({str(FANS[0].id)}, set(fans))


@skip_without_database
class LinkCommandTests(JourneyTestCase):
    """/help, /vote and /invite, in a server and through a user install in a DM"""

    async def test_help_vote_and_invite_answer_everywhere(self):
        await self.set_up()
        for guild in (self.guild, None):
            for command in (main.get_help, main.vote, main.invite):
                with self.subTest(command=command.name, where="server" if guild else "DM"):
                    asked = self.command(FANS[0], guild=guild)
                    await command.callback(asked)
                    self.assertEqual(1, len(asked.replies))
                    self.assertIsNotNone(asked.last.view)
                    self.assertTrue(any(getattr(item, "url", None) for item in asked.last.view.children))
        self.assert_no_errors_logged()

    async def test_help_names_the_commands_as_clickable_mentions(self):
        await self.set_up()
        asked = self.command(FANS[0])

        await main.get_help.callback(asked)

        self.assertIn(command_refs.LEADERBOARD, asked.last.text())
        self.assertIn(command_refs.MY_DATA, asked.last.text())


@skip_without_database
class FeedbackTests(JourneyTestCase):
    def setUp(self):
        super().setUp()
        self.support = Guild(1180006529575960616, name="Support")
        self.feedback_channel = Board(1345558910836412456, self.support, name="feedback")
        self.bot.guilds.append(self.support)

    async def send(self, guild=..., title="The board is slow", body="Posts take a minute to appear"):
        opened = self.command(FANS[0], guild=guild)
        await main.send_feedback.callback(opened, types.SimpleNamespace(name="Bug", value="bug"))
        if opened.modal is None:
            return opened
        opened.modal.fb_title._value = title
        opened.modal.message._value = body
        submitted = self.command(FANS[0], guild=guild)
        await opened.modal.on_submit(submitted)
        return submitted

    async def test_feedback_reaches_the_developer_up_to_the_daily_limit(self):
        await self.set_up()
        for _ in range(main.feedback_daily_limit):
            sent = await self.send()
            self.assertEqual(messages.FEEDBACK_SENT, sent.last.content)
            self.assertTrue(sent.last.ephemeral)
        self.assertEqual(main.feedback_daily_limit, len(self.feedback_channel.sent))
        self.assertIn("Posts take a minute to appear", post_text(self.feedback_channel.sent[0]))

        refused = await self.send()
        self.assertEqual(messages.FEEDBACK_ON_COOLDOWN.format(limit=main.feedback_daily_limit), refused.last.content)
        self.assertEqual(main.feedback_daily_limit, len(self.feedback_channel.sent))

    async def test_feedback_from_a_dm(self):
        sent = await self.send(guild=None)

        self.assertEqual(messages.FEEDBACK_SENT, sent.last.content)
        self.assertEqual(1, len(self.feedback_channel.sent))


if __name__ == "__main__":
    unittest.main()
