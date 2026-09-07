import types
import unittest
from unittest import mock

from tests.fakes import FakeAttachment, FakeGuild, FakeReaction, FakeUser

import discord
import utils
from enums import calculation_method_type


class FakeAuthor(FakeUser):
    def __init__(self, user_id: int, name: str):
        super().__init__(user_id)
        self.name = name
        self.avatar = None


class FakeChannel:
    """Channel that either resolves a referenced message or reports it as deleted."""

    def __init__(self, referenced_message=None):
        self.referenced_message = referenced_message

    async def fetch_message(self, message_id):
        if self.referenced_message is None:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.referenced_message


class FakeEmbedMessage:
    def __init__(self, content="", author_name="author", reference_message_id=None, channel=None,
                 attachments=None, reactions=None):
        self.content = content
        self.author = FakeAuthor(1, author_name)
        self.guild = FakeGuild(1)
        self.channel = channel if channel is not None else FakeChannel()
        self.reference = types.SimpleNamespace(message_id=reference_message_id) if reference_message_id else None
        self.attachments = attachments if attachments is not None else []
        self.reactions = reactions if reactions is not None else [FakeReaction("👍", [2, 3])]
        self.stickers = []
        self.embeds = []
        self.jump_url = "https://discord.com/channels/1/2/3"


REACTION_CONFIG = {
    "reaction_count_calculation_method": calculation_method_type.MOST_REACTIONS_ON_EMOJI,
    "include_author_in_reaction_calculation": True,
    "custom_emoji_check_logic": False,
    "whitelisted_emojis": []
}


class TruncateContentTests(unittest.TestCase):
    def test_keeps_short_content(self):
        self.assertEqual("a short message", utils.truncate_content("a short message"))

    def test_handles_missing_content(self):
        self.assertEqual("", utils.truncate_content(""))
        self.assertEqual("", utils.truncate_content(None))

    def test_truncates_content_to_the_embed_field_limit(self):
        truncated = utils.truncate_content("a" * 2000)
        self.assertEqual(1024, len(truncated))
        self.assertTrue(truncated.endswith("..."))


class EmbedFieldValueTests(unittest.TestCase):
    def test_keeps_the_content(self):
        self.assertEqual("hello", utils.embed_field_value("hello"))

    def test_never_returns_an_empty_value(self):
        # Discord rejects embed fields without a value, which happens on messages that are only an attachment
        self.assertNotEqual("", utils.embed_field_value(""))


class FormatReactionsFieldValueTests(unittest.TestCase):
    def test_shows_the_top_emoji(self):
        self.assertEqual("12 😂", utils.format_reactions_field_value(12, "😂"))

    def test_falls_back_to_a_label_without_an_emoji(self):
        self.assertEqual("12 reactions", utils.format_reactions_field_value(12, ""))
        self.assertEqual("12 reactions", utils.format_reactions_field_value(12, None))


class CheckVideoExtensionTests(unittest.TestCase):
    def test_returns_none_without_attachments(self):
        self.assertIsNone(utils.check_video_extension(FakeEmbedMessage()))

    def test_returns_none_for_an_image(self):
        message = FakeEmbedMessage(attachments=[FakeAttachment("https://cdn.discordapp.com/a/cat.png")])
        self.assertIsNone(utils.check_video_extension(message))

    def test_strips_the_query_from_a_video_url(self):
        message = FakeEmbedMessage(attachments=[FakeAttachment("https://cdn.discordapp.com/a/clip.mp4?ex=1&is=2")])
        self.assertEqual("https://cdn.discordapp.com/a/clip.mp4", utils.check_video_extension(message))


class CreateEmbedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # The footer is added at random, so it is disabled to keep the assertions stable
        patcher = mock.patch("utils.random.random", return_value=1.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def field_names(embed):
        return [field.name for field in embed.fields]

    async def test_builds_an_embed_for_a_plain_message(self):
        message = FakeEmbedMessage(content="a legendary moment")
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("a legendary moment", embed.description)
        self.assertIn("Reactions", self.field_names(embed))
        self.assertIn("Jump to Message", self.field_names(embed))

    async def test_falls_back_when_the_message_that_was_replied_to_is_deleted(self):
        message = FakeEmbedMessage(content="a reply", reference_message_id=42, channel=FakeChannel(None))
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("a reply", embed.description)
        self.assertIn("Reactions", self.field_names(embed))

    async def test_never_writes_an_empty_field_value_for_a_reply(self):
        referenced_message = FakeEmbedMessage(content="", author_name="referenced")
        message = FakeEmbedMessage(content="", reference_message_id=42,
                                   channel=FakeChannel(referenced_message))
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        for field in embed.fields:
            self.assertTrue(field.value, f"Field {field.name} has an empty value")


if __name__ == "__main__":
    unittest.main()
