"""/my_data journeys: a member downloading, hiding, pausing and deleting what the bot stores about them.

Each test is one member's path through the /my_data panel and its buttons, with their messages going
through the real reaction path before and after each choice, so what the panel says is checked against
what the bot then does. See tests/JOURNEYS.md.
"""

import json
import unittest
from unittest import mock

import main
from enums import command_refs
from repositories import global_profile_repo, hall_of_fame_message_repo, opt_out_repo
from translations import messages

from tests.integration.database import skip_without_database
from tests.integration.discord_world import Guild, SourceChannel
from tests.integration.journeys import ADMIN, AUTHOR, FANS, JourneyTestCase

OTHER_GUILD = 9302


@skip_without_database
class MyDataJourneyTestCase(JourneyTestCase):
    async def feature(self, message_id, author=AUTHOR, channel=None):
        message = (channel or self.general).add(message_id, author)
        await self.react(message, *FANS[:3])
        return message

    async def open_my_data(self, user=AUTHOR, guild=...):
        opened = self.command(user, guild=guild)
        await main.my_data.callback(opened)
        self.assertTrue(opened.last.ephemeral)
        return opened, opened.last.view

    async def run_daily_task(self):
        with mock.patch("builtins.print"):
            await main.daily_task.coro()


class DownloadAndTotalsTests(MyDataJourneyTestCase):
    async def test_from_nothing_stored_to_a_download(self):
        await self.set_up()
        opened, view = await self.open_my_data()
        self.assertIn(messages.MY_DATA_NOTHING_AT_ALL, opened.last.content)
        self.assertTrue(view.download_button.disabled)
        self.assertTrue(view.delete_button.disabled)

        await self.feature(1)
        await self.feature(2)
        opened, view = await self.open_my_data()
        self.assertIn("2 featured posts", opened.last.content)
        self.assertFalse(view.download_button.disabled)

        downloaded = await self.press_button(view, view.download_button, AUTHOR)
        [export] = downloaded.last.files
        document = json.loads(export.fp.read())
        self.assertTrue(downloaded.last.ephemeral)
        self.assertEqual(str(AUTHOR.id), document["user_id"])
        self.assertEqual({"1", "2"}, {post["message_id"] for post in document["featured_posts"]})
        self.assertFalse(document["not_counted"])

        again = await self.press_button(view, view.download_button, AUTHOR)
        self.assertEqual(messages.MY_DATA_DOWNLOAD_ON_COOLDOWN, again.last.content)

        # Somebody else cannot press the buttons
        stranger = await self.press_button(view, view.download_button, FANS[0])
        self.assertEqual(messages.MY_DATA_NOT_YOURS, stranger.last.content)

        # The daily task lifts the limit
        await self.run_daily_task()
        tomorrow = await self.press_button(view, view.download_button, AUTHOR)
        self.assertEqual(1, len(tomorrow.last.files))

    async def test_hiding_and_showing_the_totals_across_servers(self):
        await self.set_up()
        other = Guild(OTHER_GUILD, member_count=50)
        other_channel = SourceChannel(901, other)
        self.bot.guilds.append(other)
        await self.install(other)
        await main.configure_bot.callback(self.command(ADMIN, guild=other), 3)
        await self.feature(1)
        await self.feature(2, channel=other_channel)
        await self.run_daily_task()

        profile = self.command(AUTHOR)
        await main.user_server_profile.callback(profile, None)
        self.assertIn(messages.GLOBAL_PROFILE_HEADING, profile.last.text())

        _opened, view = await self.open_my_data()
        hidden = await self.press_button(view, view.totals_button, AUTHOR)
        self.assertIn(messages.MY_DATA_TOTALS_HIDDEN.split("{")[0], hidden.edits[-1].content)
        self.assertTrue(global_profile_repo.is_hidden(self.connection, AUTHOR.id))
        self.assertEqual(messages.SHOW_TOTALS_BUTTON, view.totals_button.label)

        # Their own profile leaves the column out too, since it is posted in the channel
        profile = self.command(AUTHOR)
        await main.user_server_profile.callback(profile, None)
        self.assertNotIn(messages.GLOBAL_PROFILE_HEADING, profile.last.text())
        # And through a user install in a DM there is nothing to show
        in_dm = self.command(AUTHOR, guild=None)
        await main.user_server_profile.callback(in_dm, None)
        self.assertEqual(messages.PROFILE_HIDDEN_OUTSIDE_SERVER_SELF.format(command=command_refs.MY_DATA),
                         in_dm.last.content)
        self.assertTrue(in_dm.last.ephemeral)

        await self.press_button(view, view.totals_button, AUTHOR)
        self.assertFalse(global_profile_repo.is_hidden(self.connection, AUTHOR.id))
        in_dm = self.command(AUTHOR, guild=None)
        await main.user_server_profile.callback(in_dm, None)
        self.assertIsNotNone(in_dm.last.embed)
        self.assertFalse(in_dm.last.ephemeral)


class NotBeingFeaturedTests(MyDataJourneyTestCase):
    async def why(self, message, asked_by):
        asked = self.command(asked_by)
        await main.why_not_on_board.callback(asked, message)
        return asked.last.content

    async def test_stopping_and_starting_again(self):
        await self.set_up()
        earlier = await self.feature(1)
        _opened, view = await self.open_my_data()

        stopped = await self.press_button(view, view.featuring_button, AUTHOR)
        self.assertIn(messages.STOPPED_FEATURING, stopped.edits[-1].content)
        self.assertIn(messages.MY_DATA_EARLIER_KEPT, stopped.edits[-1].content)
        self.assertEqual(messages.FEATURE_ME_AGAIN_BUTTON, view.featuring_button.label)
        self.assertTrue(opt_out_repo.is_opted_out(self.connection, AUTHOR.id))

        # A new message over the threshold is neither reposted nor stored
        new = await self.feature(2)
        self.assertIsNone(self.stored(new))
        self.assertEqual(1, len(self.reposts()))
        # The earlier post stays credited and keeps counting
        await self.react(earlier, FANS[3])
        self.assertEqual(4, self.stored(earlier)["reaction_count"])
        self.assertEqual(AUTHOR.id, self.stored(earlier)["author_id"])
        # A friend is told only that it cannot be featured, the author that it was their choice
        self.assertEqual(messages.WHY_CANNOT_FEATURE, await self.why(new, FANS[0]))
        self.assertEqual(messages.WHY_AUTHOR_OPTED_OUT.format(command=command_refs.MY_DATA),
                         await self.why(new, AUTHOR))
        # Everybody else is featured as usual
        friend = await self.feature(3, author=FANS[9])
        self.assertIsNotNone(self.stored(friend))

        downloaded = await self.press_button(view, view.download_button, AUTHOR)
        self.assertTrue(json.loads(downloaded.last.files[0].fp.read())["not_counted"])

        started = await self.press_button(view, view.featuring_button, AUTHOR)
        self.assertIn(messages.COUNTED_AGAIN, started.edits[-1].content)
        latest = await self.feature(4)
        self.assertEqual(AUTHOR.id, self.stored(latest)["author_id"])
        self.assert_no_errors_logged()

    async def test_a_member_who_stopped_gets_no_wrapped_and_hears_why(self):
        await self.set_up()
        await self.feature(1)
        _opened, view = await self.open_my_data()
        await self.press_button(view, view.featuring_button, AUTHOR)

        asked = self.command(AUTHOR)
        await main.hof_wrapped_command.callback(asked)

        self.assertEqual(messages.WRAPPED_NONE_OPTED_OUT.format(command=command_refs.MY_DATA), asked.last.content)
        self.assertTrue(asked.last.ephemeral)


class DeletingTests(MyDataJourneyTestCase):
    async def confirm_view(self, view):
        asked = await self.press_button(view, view.delete_button, AUTHOR)
        return asked, asked.edits[-1].view

    async def test_deleting_and_coming_back(self):
        await self.set_up()
        self.guild.members = {AUTHOR.id: AUTHOR}
        message = await self.feature(1)
        await self.run_daily_task()
        post = self.post_of(message)

        _opened, view = await self.open_my_data()
        asked, confirm = await self.confirm_view(view)
        self.assertEqual(messages.DELETE_MY_DATA_CONFIRM, asked.edits[-1].content)
        # Cancelling deletes nothing
        cancelled = await self.press_button(confirm, self.button(confirm, label=messages.CANCEL_BUTTON), AUTHOR)
        self.assertEqual(messages.DELETE_MY_DATA_CANCELLED, cancelled.edits[-1].content)
        self.assertEqual(AUTHOR.id, self.stored(message)["author_id"])

        _opened, view = await self.open_my_data()
        _asked, confirm = await self.confirm_view(view)
        done = await self.press_button(confirm, self.button(confirm, label=messages.DELETE_MY_DATA_BUTTON), AUTHOR)
        self.assertEqual(messages.DELETE_MY_DATA_DONE.format(command=command_refs.MY_DATA), done.edits[-1].content)

        # The post stays on the board, credited to nobody, and the member is off the leaderboard
        self.assertTrue(main.utils.post_shows(post))
        self.assertEqual(hall_of_fame_message_repo.NO_AUTHOR_ID, self.stored(message)["author_id"])
        await self.run_daily_task()
        board = self.command(FANS[0])
        await main.leaderboard.callback(board)
        self.assertNotIn(AUTHOR.name, board.last.text())
        profile = self.command(AUTHOR)
        await main.user_server_profile.callback(profile, None)
        self.assertEqual(messages.PROFILE_NO_DATA, profile.last.content)

        # The done message offers to stop featuring them, which works right away
        offer = done.edits[-1].view
        stopped = await self.press_button(offer, offer.children[0], AUTHOR)
        self.assertEqual(messages.DELETE_MY_DATA_DONE_STOPPED.format(command=command_refs.MY_DATA),
                         stopped.edits[-1].content)
        self.assertTrue(opt_out_repo.is_opted_out(self.connection, AUTHOR.id))

        # With only that choice stored, deleting again the same day is allowed and removes it too
        _opened, view = await self.open_my_data()
        asked, confirm = await self.confirm_view(view)
        self.assertIn(messages.DELETE_MY_DATA_CONFIRM_OPT_OUT, asked.edits[-1].content)
        await self.press_button(confirm, self.button(confirm, label=messages.DELETE_MY_DATA_BUTTON), AUTHOR)
        self.assertFalse(opt_out_repo.is_opted_out(self.connection, AUTHOR.id))
        latest = await self.feature(2)
        self.assertEqual(AUTHOR.id, self.stored(latest)["author_id"])

        # Now with a post stored again, a second deletion today is refused
        _opened, view = await self.open_my_data()
        refused = await self.press_button(view, view.delete_button, AUTHOR)
        self.assertEqual(messages.MY_DATA_DELETE_ON_COOLDOWN, refused.last.content)
        self.assert_no_errors_logged()

    async def test_my_data_works_from_a_dm(self):
        await self.set_up()
        await self.feature(1)

        opened, view = await self.open_my_data(guild=None)

        self.assertIn("1 featured post,", opened.last.content)
        downloaded = await self.press_button(view, view.download_button, AUTHOR, guild=None)
        self.assertEqual(1, len(downloaded.last.files))


if __name__ == "__main__":
    unittest.main()
