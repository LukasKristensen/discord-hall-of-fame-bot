"""Tests for the card the bot answers a ping with.

Pinging a bot is how somebody asks what it is, and it usually happens in a server where nobody has
set it up yet. So the answer has to work without a configuration, and it has to be narrow about what
counts as a ping: an @everyone, a role ping and a reply all put the bot in a message's mentions
without anybody having addressed it.
"""

import types
import unittest

import discord

import commands
from caches import ExpiringSet
from constants import version

from tests.fakes import FakePermissions
from tests.test_server_class import build_server

BOT_ID = 1
GUILD_ID = 200
CHANNEL_ID = 100
HOF_CHANNEL_ID = 999


class FakeUser:
    def __init__(self, user_id, bot=False, name="Member"):
        self.id = user_id
        self.bot = bot
        self.name = name
        self.mention = f"<@{user_id}>"
        self.display_avatar = types.SimpleNamespace(url=f"https://cdn.example/{user_id}.png")


class FakeChannel:
    def __init__(self, channel_id=CHANNEL_ID, permissions=None):
        self.id = channel_id
        self.permissions = permissions if permissions is not None else FakePermissions()
        self.sent = []

    def permissions_for(self, _member):
        return self.permissions

    async def send(self, content=None, embed=None):
        self.sent.append(embed if embed is not None else content)


class FakeGuild:
    def __init__(self):
        self.id = GUILD_ID
        self.name = "Test Server"
        self.me = FakeUser(BOT_ID, bot=True)


class FakeMessage:
    def __init__(self, content="", mentions=(), reference=None, author=None, channel=None):
        self.content = content
        self.mentions = list(mentions)
        self.reference = reference
        self.author = author if author is not None else FakeUser(77)
        self.channel = channel if channel is not None else FakeChannel()
        self.guild = FakeGuild()


def ping(content=f"<@{BOT_ID}>", **kwargs):
    return FakeMessage(content=content, mentions=[FakeUser(BOT_ID, bot=True)], **kwargs)


class IsBotMentionTests(unittest.TestCase):
    def setUp(self):
        self.bot_user = FakeUser(BOT_ID, bot=True)

    def test_recognises_a_bare_ping(self):
        self.assertTrue(commands.is_bot_mention(ping(), self.bot_user))

    def test_recognises_the_nickname_form_of_a_ping(self):
        message = ping(content=f"<@!{BOT_ID}>")
        self.assertTrue(commands.is_bot_mention(message, self.bot_user))

    def test_allows_surrounding_whitespace(self):
        self.assertTrue(commands.is_bot_mention(ping(content=f"  <@{BOT_ID}>  "), self.bot_user))

    def test_ignores_a_ping_that_carries_a_question(self):
        """Somebody talking about the bot is having a conversation, not asking what it is."""
        message = ping(content=f"<@{BOT_ID}> why did my message not get featured")
        self.assertFalse(commands.is_bot_mention(message, self.bot_user))

    def test_ignores_an_everyone_ping(self):
        """mention_everyone puts the bot in mentions without anybody addressing it."""
        message = FakeMessage(content="@everyone the server is live", mentions=[])
        self.assertFalse(commands.is_bot_mention(message, self.bot_user))

    def test_ignores_a_message_that_mentions_somebody_else(self):
        message = FakeMessage(content="<@77> look at this", mentions=[FakeUser(77)])
        self.assertFalse(commands.is_bot_mention(message, self.bot_user))

    def test_ignores_a_reply(self):
        """Replying to a Hall of Fame post mentions the bot as the author being replied to."""
        message = ping(reference=object())
        self.assertFalse(commands.is_bot_mention(message, self.bot_user))

    def test_ignores_another_bot(self):
        message = ping(author=FakeUser(88, bot=True))
        self.assertFalse(commands.is_bot_mention(message, self.bot_user))

    def test_ignores_everything_before_the_bot_knows_who_it_is(self):
        self.assertFalse(commands.is_bot_mention(ping(), None))


class BotInfoEmbedTests(unittest.TestCase):
    def setUp(self):
        self.bot_user = FakeUser(BOT_ID, bot=True)

    def build(self, server_config=None):
        return commands.build_bot_info_embed(FakeGuild(), self.bot_user, server_config)

    def field_named(self, embed, fragment):
        for field in embed.fields:
            if fragment.lower() in (field.name or "").lower():
                return field
        return None

    def test_describes_the_bot_by_what_it_is_for(self):
        embed = self.build()

        self.assertIn("best moments", embed.description)
        self.assertIn("leaderboards", embed.description.lower())

    def test_names_the_board_and_the_threshold_of_a_configured_server(self):
        embed = self.build(build_server(guild_id=GUILD_ID, hall_of_fame_channel_id=HOF_CHANNEL_ID,
                                        reaction_threshold=6))
        field = self.field_named(embed, "Set up in this server")

        self.assertIn(f"<#{HOF_CHANNEL_ID}>", field.value)
        self.assertIn("**6**", field.value)

    def test_explains_how_to_set_up_a_server_that_is_not(self):
        embed = self.build(server_config=None)

        self.assertIsNotNone(self.field_named(embed, "Not set up"))
        values = " ".join(field.value for field in embed.fields)
        self.assertNotIn("Reactions needed", values)

    def test_points_an_unconfigured_server_at_the_commands_that_set_it_up(self):
        field = self.field_named(self.build(server_config=None), "Not set up")

        self.assertIn("set_hall_of_fame_channel", field.value)
        self.assertIn("set_reaction_threshold", field.value)

    def test_lists_the_commands_every_member_can_use(self):
        field = self.field_named(self.build(), "For everyone")

        for command in ("leaderboard", "user_profile", "hof_wrapped", "help"):
            with self.subTest(command=command):
                self.assertIn(command, field.value)

    def test_offers_the_invite_and_the_support_server(self):
        field = self.field_named(self.build(), "Links")

        self.assertIn("discord.com/oauth2/authorize", field.value)
        self.assertIn("discord.gg", field.value)

    def test_shows_the_version_it_is_running(self):
        self.assertIn(version.VERSION, self.build().footer.text)

    def test_shows_the_bot_avatar(self):
        self.assertEqual(self.bot_user.display_avatar.url, self.build().thumbnail.url)


class AnswerBotMentionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot_user = FakeUser(BOT_ID, bot=True)
        self.original_cooldown = commands.recently_answered_mentions
        commands.recently_answered_mentions = ExpiringSet(ttl_seconds=30)
        self.addCleanup(self.restore_cooldown)

    def restore_cooldown(self):
        commands.recently_answered_mentions = self.original_cooldown

    async def test_answers_with_an_embed(self):
        message = ping()
        self.assertTrue(await commands.answer_bot_mention(message, self.bot_user, None))

        self.assertEqual(1, len(message.channel.sent))
        self.assertIsInstance(message.channel.sent[0], discord.Embed)

    async def test_says_nothing_without_permission_to_post(self):
        message = ping(channel=FakeChannel(permissions=FakePermissions(send_messages=False)))
        self.assertFalse(await commands.answer_bot_mention(message, self.bot_user, None))

        self.assertEqual([], message.channel.sent)

    async def test_falls_back_to_text_without_permission_to_embed(self):
        """An embed sent without Embed Links is dropped silently, so the answer would vanish."""
        message = ping(channel=FakeChannel(permissions=FakePermissions(embed_links=False)))
        await commands.answer_bot_mention(message, self.bot_user, None)

        self.assertIsInstance(message.channel.sent[0], str)
        self.assertIn("Hall of Fame", message.channel.sent[0])

    async def test_does_not_answer_the_same_channel_twice_in_a_row(self):
        """Otherwise a ping is a way to make the bot flood a channel."""
        channel = FakeChannel()
        await commands.answer_bot_mention(ping(channel=channel), self.bot_user, None)
        answered_again = await commands.answer_bot_mention(ping(channel=channel), self.bot_user, None)

        self.assertFalse(answered_again)
        self.assertEqual(1, len(channel.sent))

    async def test_still_answers_a_different_channel(self):
        first, second = FakeChannel(channel_id=1), FakeChannel(channel_id=2)
        await commands.answer_bot_mention(ping(channel=first), self.bot_user, None)
        await commands.answer_bot_mention(ping(channel=second), self.bot_user, None)

        self.assertEqual(1, len(second.sent))

    async def test_answers_again_once_the_window_has_passed(self):
        clock = [1000.0]
        commands.recently_answered_mentions = ExpiringSet(ttl_seconds=30, time_source=lambda: clock[0])
        channel = FakeChannel()
        await commands.answer_bot_mention(ping(channel=channel), self.bot_user, None)
        clock[0] += 31
        await commands.answer_bot_mention(ping(channel=channel), self.bot_user, None)

        self.assertEqual(2, len(channel.sent))

    async def test_uses_the_configuration_of_the_server_it_was_pinged_in(self):
        message = ping()
        config = build_server(guild_id=GUILD_ID, hall_of_fame_channel_id=HOF_CHANNEL_ID,
                              reaction_threshold=4)
        await commands.answer_bot_mention(message, self.bot_user, config)

        values = " ".join(field.value for field in message.channel.sent[0].fields)
        self.assertIn(f"<#{HOF_CHANNEL_ID}>", values)


if __name__ == "__main__":
    unittest.main()
