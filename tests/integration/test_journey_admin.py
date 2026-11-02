"""Server admin journeys: adding the bot, setting it up, every setting, and removing it again.

Each test is one admin's path from start to end through main's own handlers, with Discord faked and the
database real, and checks what the admin and the members see at every step. See tests/JOURNEYS.md.
"""

import datetime
import types
import unittest
from unittest import mock

import discord

import commands
import main
from enums import calculation_method_type, command_refs
from repositories import guild_lifecycle_event_repo, server_config_repo
from translations import messages

from tests.integration.database import skip_without_database
from tests.integration.discord_world import Author, Board, SourceChannel, attachment, post_text
from tests.integration.journeys import ADMIN, AUTHOR, FANS, GUILD, STARTING_THRESHOLD, JourneyTestCase

MEMBER = Author(4001)


def choice(name, value):
    return types.SimpleNamespace(name=name, value=value)


@skip_without_database
class InstallingTests(JourneyTestCase):
    async def test_from_install_to_the_first_post(self):
        """Added, welcomed, checked, threshold lowered, and the first message reaches the board"""
        board = await self.install()

        # A board of its own, with the welcome message and its buttons
        self.assertEqual("hall-of-fame", board.name)
        welcome = board.sent[0]
        self.assertIn("Welcome to the Hall of Fame", welcome.content)
        self.assertIn(str(STARTING_THRESHOLD), welcome.content)
        self.assertEqual({commands.CHECK_SETUP_CUSTOM_ID, commands.SETTINGS_CUSTOM_ID},
                         {item.custom_id for item in welcome.view.children if item.custom_id})
        self.assertEqual([("JOIN",)], self.rows("SELECT event_type FROM guild_lifecycle_event WHERE guild_id = %s",
                                                (GUILD,)))
        self.assertEqual(board.id, server_config_repo.get_parameter_value(self.connection, GUILD,
                                                                          "hall_of_fame_channel_id"))

        # Troubleshoot on the welcome message: the admin gets the findings privately, a member is refused
        checked = await self.press_button(welcome.view, self.button(welcome.view, commands.CHECK_SETUP_CUSTOM_ID),
                                          ADMIN)
        self.assertTrue(checked.last.ephemeral)
        self.assertIsNotNone(checked.last.embed)
        refused = await self.press_button(welcome.view, self.button(welcome.view, commands.CHECK_SETUP_CUSTOM_ID),
                                          MEMBER)
        self.assertEqual(messages.NOT_AUTHORIZED, refused.last.content)
        self.assertTrue(refused.last.ephemeral)

        # The admin lowers the threshold
        lowered = self.command(ADMIN)
        await main.configure_bot.callback(lowered, 3)
        self.assertEqual(3, self.config.reaction_threshold)
        self.assertEqual(3, server_config_repo.get_parameter_value(self.connection, GUILD, "reaction_threshold"))

        # /get_server_config shows it, with Troubleshoot and Change settings under it
        shown = self.command(MEMBER)
        await main.get_server_config.callback(shown)
        self.assertIn("3", shown.last.text())
        self.assertEqual({messages.TROUBLESHOOT_BUTTON, messages.SETTINGS_BUTTON},
                         {item.label for item in shown.last.view.children})

        # Three reactions now feature a message
        self.board = board
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])
        self.assertEqual(1, len(self.reposts()))
        self.assertIn("🔥 3", post_text(self.post_of(message)))
        self.assert_no_errors_logged()

    async def test_troubleshoot_finds_a_channel_the_bot_cannot_read(self):
        await self.set_up()
        hidden = SourceChannel(777, self.guild, readable=False)

        check = self.command(ADMIN)
        await main.troubleshoot.callback(check)

        self.assertTrue(check.last.ephemeral)
        self.assertIn(hidden.mention, check.last.text())

    async def test_a_member_cannot_run_troubleshoot(self):
        await self.set_up()
        check = self.command(MEMBER)

        await main.troubleshoot.callback(check)

        self.assertEqual(messages.NOT_AUTHORIZED, check.last.content)
        self.assertTrue(check.last.ephemeral)

    async def test_an_install_that_failed_is_finished_with_set_hall_of_fame_channel(self):
        """The bot could not make its board, says so once, and the admin points it at a channel instead"""
        notices = Board(880, self.guild, name="general-chat")
        self.guild.text_channels = [notices]

        async def refuse(_name):
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")

        self.guild.create_text_channel = refuse
        self.assertIsNone(await self.install())
        self.assertIsNone(self.config)
        self.assertEqual(1, len(notices.sent))
        self.assertIn(command_refs.SET_HALL_OF_FAME_CHANNEL, notices.sent[0].content)

        # Commands say it is not set up rather than failing
        threshold = self.command(ADMIN)
        await main.configure_bot.callback(threshold, 3)
        self.assertEqual(messages.ERROR_SERVER_NOT_SETUP, threshold.last.content)

        own_board = Board(881, self.guild, name="best-of")
        chosen = self.command(ADMIN)
        await main.set_hall_of_fame_channel.callback(chosen, own_board)

        self.assertEqual(own_board.id, self.config.hall_of_fame_channel_id)
        self.assertIn(messages.HOF_CHANNEL_SET.format(channel=own_board.mention), chosen.text())
        self.assertIn("Welcome to the Hall of Fame", own_board.sent[0].content)
        self.board = own_board
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:STARTING_THRESHOLD])
        self.assertEqual(1, len(self.reposts()))


@skip_without_database
class SettingCommandTests(JourneyTestCase):
    # Every setting command, the option it takes, a new value, and the column it changes
    SETTINGS = (
        ("include_author_own_reaction_in_threshold", False, "include_author_in_reaction_calculation", False),
        ("allow_messages_in_hof_channel", True, "allow_messages_in_hof_channel", True),
        ("require_image_or_video", True, "require_image_or_video", True),
        ("ignore_bot_messages", True, "ignore_bot_messages", True),
        ("hide_hall_of_fame_posts_when_they_are_below_threshold", False, "hide_hof_post_below_threshold", False),
        ("count_in_global_profiles", False, "count_in_global_profiles", False),
        ("set_post_due_date", 12, "post_due_date", 12),
        ("configure_bot", 4, "reaction_threshold", 4),
        ("custom_emoji_check_logic", choice("Only whitelisted emojis", "whitelisted_emojis"),
         "custom_emoji_check_logic", True),
        ("calculation_method", choice("Unique", calculation_method_type.UNIQUE_USERS),
         "reaction_count_calculation_method", calculation_method_type.UNIQUE_USERS),
    )

    async def test_every_setting_command_is_stored_confirmed_and_refused_to_members(self):
        await self.set_up()
        for command_name, option, column, stored in self.SETTINGS:
            command = getattr(main, command_name)
            with self.subTest(command=command_name):
                refused = self.command(MEMBER)
                await command.callback(refused, option)
                self.assertEqual(messages.NOT_AUTHORIZED, refused.last.content)
                self.assertTrue(refused.last.ephemeral)
                self.assertNotEqual(stored, getattr(self.config, column))

                changed = self.command(ADMIN)
                await command.callback(changed, option)
                self.assertEqual(stored, server_config_repo.get_parameter_value(self.connection, GUILD, column))
                self.assertEqual(stored, getattr(self.config, column))
                # A change is announced in the channel, so other admins see it
                self.assertFalse(changed.replies[0].ephemeral)

                again = self.command(ADMIN)
                await command.callback(again, option)
                self.assertIn("nothing changed", again.last.content)
                self.assertTrue(again.last.ephemeral)
        self.assert_no_errors_logged()

    async def test_the_settings_survive_a_restart(self):
        """What the commands stored is what the bot loads on its next start"""
        await self.set_up()
        for command_name, option, _column, _stored in self.SETTINGS:
            await getattr(main, command_name).callback(self.command(ADMIN), option)

        reloaded = server_config_repo.get_server_classes(self.connection)[GUILD]
        for _command_name, _option, column, stored in self.SETTINGS:
            with self.subTest(column=column):
                self.assertEqual(stored, getattr(reloaded, column))


@skip_without_database
class SettingEffectTests(JourneyTestCase):
    """Each setting changed by its command, then a member's message showing what it does"""

    async def test_leaving_out_the_authors_own_reaction(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await main.include_author_own_reaction_in_threshold.callback(self.command(ADMIN), False)

        await self.react(message, AUTHOR, *FANS[:2])
        self.assertEqual([], self.reposts())
        await self.react(message, FANS[2])
        self.assertEqual(1, len(self.reposts()))

    async def test_requiring_an_image_or_video(self):
        await self.set_up()
        await main.require_image_or_video.callback(self.command(ADMIN), True)
        text_only = self.general.add(1, AUTHOR)
        picture = self.general.add(2, AUTHOR, attachments=[attachment()])

        await self.react(text_only, *FANS[:3])
        await self.react(picture, *FANS[:3])

        self.assertIsNone(self.stored(text_only))
        self.assertIsNotNone(self.stored(picture))

    async def test_ignoring_other_bots(self):
        await self.set_up()
        bot_message = self.general.add(1, Author(5555, bot=True))
        await self.react(bot_message, *FANS[:3])
        self.assertIsNotNone(self.stored(bot_message), "bots are featured until the server says otherwise")

        await main.ignore_bot_messages.callback(self.command(ADMIN), True)
        another = self.general.add(2, Author(5555, bot=True))
        await self.react(another, *FANS[:3])
        self.assertIsNone(self.stored(another))

    async def test_counting_unique_members(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, FANS[0], emoji="😂")
        await self.react(message, FANS[1], emoji="❤️")
        await self.react(message, FANS[2], emoji="🔥")
        self.assertEqual([], self.reposts(), "one of each emoji is not three of one")

        await main.calculation_method.callback(self.command(ADMIN), choice("Unique", calculation_method_type.UNIQUE_USERS))
        await self.react(message, FANS[3], emoji="👍")
        self.assertEqual(4, self.stored(message)["reaction_count"])

    async def test_keeping_posts_up_below_the_threshold(self):
        await self.set_up()
        await main.hide_hall_of_fame_posts_when_they_are_below_threshold.callback(self.command(ADMIN), False)
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])

        await self.unreact(message, FANS[0], FANS[1])

        self.assertIn("🔥 3", post_text(self.post_of(message)), "the post keeps its last count above the threshold")

    async def test_a_shorter_post_due_date(self):
        await self.set_up()
        await main.set_post_due_date.callback(self.command(ADMIN), 1)
        old = self.general.add(1, AUTHOR)
        old.created_at -= datetime.timedelta(days=3)

        await self.react(old, *FANS[:3])

        self.assertIsNone(self.stored(old))

    async def test_the_whitelist_from_turning_it_on_to_clearing_it(self):
        await self.set_up()
        refused = self.command(ADMIN)
        await main.whitelist_emoji.callback(refused, "🔥")
        self.assertEqual(messages.CUSTOM_EMOJI_CHECK_DISABLED, refused.last.content)

        turned_on = self.command(ADMIN)
        await main.custom_emoji_check_logic.callback(turned_on, choice("Only whitelisted emojis", "whitelisted_emojis"))
        self.assertIn(messages.WHITELIST_EMPTY_NOTE.format(command=command_refs.WHITELIST_EMOJI).strip(),
                      turned_on.last.content)
        await main.whitelist_emoji.callback(self.command(ADMIN), "🔥")
        duplicate = self.command(ADMIN)
        await main.whitelist_emoji.callback(duplicate, "🔥")
        self.assertTrue(duplicate.last.ephemeral)
        self.assertEqual(["🔥"], server_config_repo.get_parameter_value(self.connection, GUILD, "whitelisted_emojis"))

        laughed = self.general.add(1, AUTHOR)
        await self.react(laughed, *FANS[:3], emoji="😂")
        self.assertIsNone(self.stored(laughed))
        fired = self.general.add(2, AUTHOR)
        await self.react(fired, *FANS[:3], emoji="🔥")
        self.assertIsNotNone(self.stored(fired))

        removed = self.command(ADMIN)
        await main.unwhitelist_emoji.callback(removed, "🔥")
        self.assertEqual([], self.config.whitelisted_emojis)
        await main.whitelist_emoji.callback(self.command(ADMIN), "😂")
        await main.clear_whitelist.callback(self.command(ADMIN))
        self.assertEqual([], server_config_repo.get_parameter_value(self.connection, GUILD, "whitelisted_emojis"))
        empty = self.command(ADMIN)
        await main.clear_whitelist.callback(empty)
        self.assertEqual(messages.WHITELIST_ALREADY_EMPTY, empty.last.content)

    async def test_chat_in_the_board(self):
        """Off by default: a member's message in the board is removed. Turned on, it stays"""
        await self.set_up()
        deleted = []

        def chat(message_id):
            message = types.SimpleNamespace(id=message_id, channel=self.board, guild=self.guild, author=MEMBER,
                                            type=discord.MessageType.default, mentions=[], role_mentions=[],
                                            content="hello", reference=None)

            async def delete():
                deleted.append(message_id)

            message.delete = delete
            return message

        async def no_wait(_seconds):
            pass

        with mock.patch.object(main.events.asyncio, "sleep", no_wait):
            await main.on_message(chat(1))
        self.assertEqual([1], deleted)

        await main.allow_messages_in_hof_channel.callback(self.command(ADMIN), True)
        await main.on_message(chat(2))
        self.assertEqual([1], deleted)

    async def test_member_commands_are_turned_away_in_a_board_closed_to_chat(self):
        await self.set_up()
        in_board = self.command(MEMBER, channel_id=self.board.id)

        await main.leaderboard.callback(in_board)

        self.assertTrue(in_board.last.ephemeral)
        self.assertIn(self.board.mention, in_board.last.content)


@skip_without_database
class SettingsFormTests(JourneyTestCase):
    async def open_form(self, user=ADMIN):
        config = self.command(user)
        await main.get_server_config.callback(config)
        view = config.last.view
        return await self.press_button(view, self.button(view, commands.SETTINGS_CUSTOM_ID), user)

    async def submit(self, form, threshold=None, due_date=None, method=None, rules=None, channel=None):
        if threshold is not None:
            form.threshold._value = threshold
        if due_date is not None:
            form.due_date._value = due_date
        form.method._value = method if method is not None else self.config.reaction_count_calculation_method
        form.rules._values = rules if rules is not None else [
            column for column in messages.SETTINGS_RULE_OPTIONS if getattr(self.config, column)]
        form.channel._values = [channel or self.board]
        sent = self.command(ADMIN)
        await form.on_submit(sent)
        return sent

    async def test_changing_several_settings_in_one_form(self):
        await self.set_up()
        opened = await self.open_form()
        form = opened.modal
        self.assertIsNotNone(form)
        self.assertEqual("3", form.threshold.default)

        rules = [column for column in messages.SETTINGS_RULE_OPTIONS if getattr(self.config, column)]
        rules.append("ignore_bot_messages")
        sent = await self.submit(form, threshold="5", due_date="10", rules=rules)

        self.assertTrue(sent.last.ephemeral)
        self.assertIn("5", sent.last.content)
        self.assertEqual(5, server_config_repo.get_parameter_value(self.connection, GUILD, "reaction_threshold"))
        self.assertEqual(10, self.config.post_due_date)
        self.assertTrue(self.config.ignore_bot_messages)

        unchanged = await self.submit((await self.open_form()).modal)
        self.assertEqual(messages.SETTINGS_NOTHING_CHANGED, unchanged.last.content)

    async def test_a_form_left_open_does_not_undo_another_admins_change(self):
        """Only what this form changed is stored, so the other admin's threshold stays."""
        await self.set_up()
        stale = (await self.open_form()).modal
        await self.submit((await self.open_form()).modal, threshold="5")

        rules = [column for column in messages.SETTINGS_RULE_OPTIONS if getattr(self.config, column)]
        rules.append("ignore_bot_messages")
        await self.submit(stale, rules=rules)

        self.assertEqual(5, server_config_repo.get_parameter_value(self.connection, GUILD, "reaction_threshold"))
        self.assertEqual(5, self.config.reaction_threshold)
        self.assertTrue(self.config.ignore_bot_messages)

    async def test_a_wrong_value_stores_nothing(self):
        await self.set_up()
        form = (await self.open_form()).modal

        sent = await self.submit(form, threshold="five", due_date="9")

        self.assertIn(messages.SETTINGS_NOT_SAVED, sent.last.content)
        self.assertTrue(sent.last.ephemeral)
        self.assertEqual(3, self.config.reaction_threshold)
        self.assertNotEqual(9, server_config_repo.get_parameter_value(self.connection, GUILD, "post_due_date"))

    async def test_a_member_cannot_open_the_form(self):
        await self.set_up()

        opened = await self.open_form(MEMBER)

        self.assertIsNone(opened.modal)
        self.assertEqual(messages.NOT_AUTHORIZED, opened.last.content)

    async def test_the_welcome_messages_set_up_button_opens_the_same_form(self):
        board = await self.install()
        welcome = board.sent[0]

        opened = await self.press_button(welcome.view, self.button(welcome.view, commands.SETTINGS_CUSTOM_ID), ADMIN)

        self.assertIsInstance(opened.modal, commands.SettingsForm)

    async def test_moving_the_board_from_the_form(self):
        await self.set_up()
        new_board = Board(882, self.guild, name="legends")
        form = (await self.open_form()).modal

        sent = await self.submit(form, channel=new_board)

        self.assertEqual(new_board.id, self.config.hall_of_fame_channel_id)
        self.assertTrue(sent.last.ephemeral)
        self.assertEqual(discord.AllowedMentions.none().to_dict(), new_board.sent[0].allowed_mentions.to_dict())


@skip_without_database
class MovingTheBoardTests(JourneyTestCase):
    async def test_moving_the_board_and_the_next_post_landing_there(self):
        await self.set_up()
        old_board = self.board
        first = self.general.add(1, AUTHOR)
        await self.react(first, *FANS[:3])

        locked = Board(883, self.guild, name="locked")
        locked.missing_permissions = {"send_messages"}
        refused = self.command(ADMIN)
        await main.set_hall_of_fame_channel.callback(refused, locked)
        self.assertTrue(refused.last.ephemeral)
        self.assertIn("Send Messages", refused.last.content)
        self.assertEqual(old_board.id, self.config.hall_of_fame_channel_id)

        new_board = Board(884, self.guild, name="legends")
        moved = self.command(ADMIN)
        await main.set_hall_of_fame_channel.callback(moved, new_board)
        self.assertEqual(new_board.id, server_config_repo.get_parameter_value(self.connection, GUILD,
                                                                              "hall_of_fame_channel_id"))
        announcement = new_board.sent[0]
        self.assertIn(command_refs.SET_REACTION_THRESHOLD, announcement.content)
        self.assertEqual(discord.AllowedMentions.none().to_dict(), announcement.allowed_mentions.to_dict())

        same = self.command(ADMIN)
        await main.set_hall_of_fame_channel.callback(same, new_board)
        self.assertTrue(same.last.ephemeral)

        self.board = new_board
        second = self.general.add(2, AUTHOR)
        await self.react(second, *FANS[:3])
        self.assertIsNotNone(self.post_of(second))
        self.assertEqual(1, len([post for post in old_board.sent if post.flags.components_v2]))

    async def test_a_post_on_the_old_board_still_counts_after_the_move(self):
        """Reactions on a message featured before the move keep updating its stored count"""
        await self.set_up()
        first = self.general.add(1, AUTHOR)
        await self.react(first, *FANS[:3])
        await main.set_hall_of_fame_channel.callback(self.command(ADMIN), Board(885, self.guild, name="legends"))

        await self.react(first, FANS[3])

        self.assertEqual(4, self.stored(first)["reaction_count"])
        self.assert_no_errors_logged()


@skip_without_database
class RemovalTests(JourneyTestCase):
    async def test_removing_the_bot_forgets_the_server(self):
        await self.set_up()
        message = self.general.add(1, AUTHOR)
        await self.react(message, *FANS[:3])

        await main.on_guild_remove(self.guild)

        self.assertNotIn(GUILD, main.server_classes)
        self.assertFalse(server_config_repo.check_if_guild_exists(self.connection, GUILD))
        self.assertEqual([(0,)], self.rows("SELECT COUNT(*) FROM hall_of_fame_message WHERE guild_id = %s", (GUILD,)))
        self.assertEqual("LEAVE", guild_lifecycle_event_repo.get_latest_event_type(self.connection, GUILD))

        # Reactions and commands that arrive afterwards change nothing
        await self.react(message, FANS[3])
        self.assertEqual(1, len(self.reposts()))
        leaderboard = self.command(MEMBER)
        await main.leaderboard.callback(leaderboard)
        self.assertEqual(messages.ERROR_SERVER_NOT_SETUP, leaderboard.last.content)

    async def test_adding_the_bot_back_starts_over(self):
        await self.set_up()
        await main.on_guild_remove(self.guild)
        self.guild.channels_by_id.pop(self.board.id)

        board = await self.install()

        self.assertEqual(STARTING_THRESHOLD, self.config.reaction_threshold)
        self.assertIn("Welcome to the Hall of Fame", board.sent[0].content)
        self.assertEqual(["JOIN", "LEAVE", "JOIN"], [row[0] for row in self.rows(
            "SELECT event_type FROM guild_lifecycle_event WHERE guild_id = %s ORDER BY id", (GUILD,))])


if __name__ == "__main__":
    unittest.main()
