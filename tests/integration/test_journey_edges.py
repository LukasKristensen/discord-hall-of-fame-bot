"""Edge path journeys: what members and admins run into when something stands in the way of a post.

Age-restricted channels, media Discord flagged, channels the bot cannot read, missing permissions, the
daily task, and commands used through a user install in DMs. Each test walks the path through main's own
handlers, with Discord faked and the database real. See tests/JOURNEYS.md.
"""

import types
import unittest
from unittest import mock

import main
import utils
from enums import command_refs
from repositories import permission_warning_repo, server_config_repo
from translations import messages

from tests.integration.database import skip_without_database
from tests.integration.discord_world import Board, Guild, SourceChannel, attachment, post_text
from tests.integration.journeys import ADMIN, AUTHOR, FANS, GUILD, JourneyTestCase


def opening(template):
    return template.split("{")[0]


@skip_without_database
class EdgeJourneyTestCase(JourneyTestCase):
    async def why(self, message, asked_by):
        asked = self.command(asked_by)
        # Answered every time, so each question here comes from a member who has not asked yet
        main.why_cooldown = type(main.why_cooldown)(ttl_seconds=main.why_cooldown_seconds)
        await main.why_not_on_board.callback(asked, message)
        self.assertTrue(asked.last.ephemeral)
        return asked.last.content

    async def troubleshoot(self):
        check = self.command(ADMIN)
        await main.troubleshoot.callback(check)
        self.assertTrue(check.last.ephemeral)
        return check.last.text()

    async def run_daily_task(self):
        with mock.patch("builtins.print"):
            await main.daily_task.coro()


class AgeRestrictedChannelTests(EdgeJourneyTestCase):
    async def test_an_age_restricted_channel_until_the_board_is_age_restricted_too(self):
        await self.set_up()
        restricted = SourceChannel(502, self.guild, nsfw=True)
        message = restricted.add(1, AUTHOR)

        await self.react(message, *FANS[:4])
        self.assertEqual([], self.reposts())
        self.assertIsNone(self.stored(message))
        self.assertEqual(messages.WHY_AGE_RESTRICTED, await self.why(message, FANS[0]))
        self.assertIn(restricted.mention, await self.troubleshoot())

        self.board.nsfw = True
        await self.react(message, FANS[4])
        self.assertIsNotNone(self.post_of(message))

    async def test_a_post_whose_channel_becomes_age_restricted_hides_and_comes_back(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        post = self.post_of(message)

        self.general.nsfw = True
        await self.react(message, FANS[3])
        self.assertFalse(utils.post_shows(post))
        self.assertEqual(messages.WHY_AGE_RESTRICTED, await self.why(message, FANS[0]))

        self.board.nsfw = True
        await self.react(message, FANS[4])
        self.assertTrue(utils.post_shows(post))
        self.assertIn("🔥 5", post_text(post))
        self.assertEqual(1, len(self.reposts()))


class FlaggedMediaTests(EdgeJourneyTestCase):
    async def test_gore_is_never_reposted_and_explicit_only_to_an_age_restricted_board(self):
        await self.set_up()
        gore = self.general.add(1, AUTHOR, attachments=[attachment("a.png", flags=utils.GORE_CONTENT)])
        explicit = self.general.add(2, AUTHOR, attachments=[attachment("b.png", flags=utils.EXPLICIT_CONTENT)])

        await self.react(gore, *FANS[:3])
        await self.react(explicit, *FANS[:3])
        self.assertEqual([], self.reposts())
        self.assertEqual(messages.WHY_FLAGGED_MEDIA, await self.why(gore, FANS[0]))

        self.board.nsfw = True
        await self.react(gore, FANS[3])
        await self.react(explicit, FANS[3])
        self.assertIsNone(self.stored(gore))
        self.assertIsNotNone(self.stored(explicit))

    async def test_a_post_flagged_after_it_was_sent_is_taken_down(self):
        """Scanning can finish later, and Discord sends the result as an edit of the bot's own post"""
        await self.set_up()
        message = self.general.add(1, AUTHOR, attachments=[attachment()])
        await self.react(message, *FANS[:3])
        post = self.post_of(message)
        self.assertTrue(utils.post_shows(post))

        # The gore bit of a Components V2 media item's scan result
        flagged = {"components": [{"items": [{"media": {}, "content_scan_metadata": {"flags": 1 << 1}}]}]}
        await main.on_raw_message_edit(types.SimpleNamespace(channel_id=self.board.id, guild_id=GUILD,
                                                             message=post, data=flagged))

        self.assertFalse(utils.post_shows(post))
        self.assertIsNotNone(self.stored(message), "kept, like a hidden post")

        # The source message carries the flag now too, so further reactions keep it down
        message.attachments = [attachment(flags=utils.GORE_CONTENT)]
        await self.react(message, FANS[3])
        self.assertFalse(utils.post_shows(post))


class UnreadableChannelTests(EdgeJourneyTestCase):
    async def test_a_channel_the_bot_cannot_read(self):
        await self.set_up()
        hidden = SourceChannel(503, self.guild, readable=False)
        message = hidden.add(1, AUTHOR)

        await self.react(message, *FANS[:5])

        self.assertEqual([], self.reposts())
        self.assertIn(opening(messages.WHY_CANNOT_READ), await self.why(message, FANS[0]))
        self.assertIn(hidden.mention, await self.troubleshoot())
        self.assert_no_errors_logged()

        # Once the bot can read it, the next reaction counts the ones already there
        hidden.readable = True
        await self.react(message, FANS[5])
        self.assertIsNotNone(self.post_of(message))


class MissingPermissionTests(EdgeJourneyTestCase):
    async def test_a_board_the_bot_cannot_post_in(self):
        await self.set_up()
        notices = Board(889, self.guild, name="general-chat", position=0)
        self.guild.text_channels = [notices]
        self.board.missing_permissions = {"send_messages"}
        message = self.general.add(1, AUTHOR)

        await self.react(message, *FANS[:3])
        self.assertEqual([], self.reposts())
        self.assertIsNone(self.stored(message))
        self.assertIn(opening(messages.WHY_CANNOT_POST), await self.why(message, FANS[0]))
        self.assertIn("Send Messages", await self.troubleshoot())

        # The daily task warns the server once, in a channel it can post in
        await self.run_daily_task()
        await self.run_daily_task()
        warnings = [post for post in notices.sent if "missing the required permissions" in post.content]
        self.assertEqual(1, len(warnings))
        self.assertIn(GUILD, permission_warning_repo.get_permission_warnings(self.connection))

        # Fixed: the next reaction posts it, and the warning is forgotten
        self.board.missing_permissions = set()
        await self.react(message, FANS[3])
        self.assertIsNotNone(self.post_of(message))
        await self.run_daily_task()
        self.assertNotIn(GUILD, permission_warning_repo.get_permission_warnings(self.connection))

    async def test_a_deleted_board(self):
        await self.set_up()
        self.guild.channels_by_id.pop(self.board.id)
        message = self.general.add(1, AUTHOR)

        await self.react(message, *FANS[:3])

        self.assertIsNone(self.stored(message))
        self.assertIn(opening(messages.WHY_NO_BOARD), await self.why(message, FANS[0]))
        self.assertIn(command_refs.SET_HALL_OF_FAME_CHANNEL, await self.troubleshoot())


class DailyTaskTests(EdgeJourneyTestCase):
    async def test_a_day_of_posts_then_the_daily_task(self):
        await self.set_up()
        self.guild.members = {AUTHOR.id: AUTHOR}
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        # Reactions added while the bot was offline only reach the stored count through the daily task
        message.react("🔥", *(fan.id for fan in FANS[3:6]))
        # Used up for today
        await main.leaderboard.callback(self.command(FANS[0]))

        await self.run_daily_task()

        self.assertEqual({}, main.daily_command_cooldowns)
        profile = self.command(AUTHOR)
        await main.user_server_profile.callback(profile, None)
        self.assertIsNotNone(profile.last.embed)
        board = self.command(FANS[0])
        await main.leaderboard.callback(board)
        self.assertIn(AUTHOR.name, board.last.text())
        self.assertEqual([(GUILD,)], self.rows("SELECT guild_id FROM guild_monthly_snapshot"))
        self.assert_no_errors_logged()

    async def test_the_daily_task_with_a_deleted_message_and_a_server_gone_offline(self):
        """Neither stops the rest of the run"""
        await self.set_up()
        gone = Guild(9303)
        self.bot.guilds.append(gone)
        await self.install(gone)
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        self.general.delete(message.id)
        self.bot.guilds.remove(gone)

        await self.run_daily_task()

        self.assertTrue(server_config_repo.check_if_guild_exists(self.connection, 9303),
                        "a server missing for one day is kept")
        self.assertIsNotNone(self.stored(message))
        self.assertEqual([], [entry for entry in self.logged if entry.startswith("Error in daily_task")])


class UserInstallTests(EdgeJourneyTestCase):
    """Commands a member added to their own account, used in a DM or a server without the bot"""

    async def test_a_profile_in_a_dm(self):
        await self.set_up()
        in_dm = self.command(AUTHOR, guild=None)
        await main.user_server_profile.callback(in_dm, None)
        self.assertIn(opening(messages.PROFILE_NOTHING_OUTSIDE_SERVER), in_dm.last.content)
        self.assertTrue(in_dm.last.ephemeral)

        await self.react(self.general.add(1, AUTHOR), *FANS[:3])
        in_dm = self.command(AUTHOR, guild=None)
        await main.user_server_profile.callback(in_dm, None)
        self.assertIsNotNone(in_dm.last.embed)

        someone_else = self.command(FANS[0], guild=None)
        await main.user_server_profile.callback(someone_else, AUTHOR)
        self.assertIn(opening(messages.PROFILE_OTHERS_OUTSIDE_SERVER), someone_else.last.content)
        self.assertTrue(someone_else.last.ephemeral)

    async def test_a_server_without_the_bot(self):
        """discord.py fills in a partial guild there, so only the bot's own guild list tells"""
        await self.set_up()
        await self.react(self.general.add(1, AUTHOR), *FANS[:3])
        elsewhere = self.command(AUTHOR, guild=types.SimpleNamespace(id=9999, name="Elsewhere"))

        await main.user_server_profile.callback(elsewhere, None)

        self.assertIsNotNone(elsewhere.last.embed)

    async def test_server_commands_in_a_dm_say_the_server_is_not_set_up(self):
        """Discord only offers them in servers, so this is the guard behind that"""
        await self.set_up()
        for command in (main.leaderboard, main.hof_wrapped_command, main.server_hof_wrapped_command,
                        main.get_server_config):
            with self.subTest(command=command.name):
                in_dm = self.command(FANS[0], guild=None)
                await command.callback(in_dm)
                self.assertEqual(messages.ERROR_SERVER_NOT_SETUP, in_dm.last.content)
                self.assertTrue(in_dm.last.ephemeral)


if __name__ == "__main__":
    unittest.main()
