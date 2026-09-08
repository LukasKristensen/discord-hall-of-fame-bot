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


class FakeSticker:
    def __init__(self, url):
        self.url = url


def embed_with(type_name=None, url=None, image_url=None, thumbnail_url=None):
    """A message embed as discord.py exposes it, used for the link preview fallbacks."""
    return types.SimpleNamespace(
        type=type_name,
        url=url,
        image=types.SimpleNamespace(url=image_url) if image_url else None,
        thumbnail=types.SimpleNamespace(url=thumbnail_url) if thumbnail_url else None
    )


class CreateEmbedContentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch("utils.random.random", return_value=1.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def field_named(embed, name):
        return next((field for field in embed.fields if field.name == name), None)

    async def test_does_not_change_the_message_it_was_given(self):
        # The message comes from the discord.py cache, so truncating it in place corrupts the cache
        message = FakeEmbedMessage(content="a" * 2000)
        await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual(2000, len(message.content))

    async def test_truncates_long_content_in_the_embed(self):
        embed = await utils.create_embed(FakeEmbedMessage(content="a" * 2000), 5, None, REACTION_CONFIG)

        self.assertEqual(1024, len(embed.description))
        self.assertTrue(embed.description.endswith("..."))

    async def test_shows_the_reaction_count_and_the_top_emoji(self):
        message = FakeEmbedMessage(reactions=[FakeReaction("😂", [1, 2, 3]), FakeReaction("👍", [4])])
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("3 😂", self.field_named(embed, "Reactions").value)

    async def test_uses_the_attachment_as_the_image(self):
        message = FakeEmbedMessage(content="look", attachments=[FakeAttachment("https://cdn/x.png", "image/png")])
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/x.png", embed.image.url)

    async def test_falls_back_to_an_embedded_image_from_a_link(self):
        message = FakeEmbedMessage(content="https://example.com/x")
        message.embeds = [embed_with(type_name="image", url="https://example.com/x.png")]
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://example.com/x.png", embed.image.url)

    async def test_falls_back_to_an_embedded_thumbnail(self):
        message = FakeEmbedMessage(content="https://example.com/x")
        message.embeds = [embed_with(type_name="link", thumbnail_url="https://example.com/thumb.png")]
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://example.com/thumb.png", embed.image.url)

    async def test_shows_a_sticker_as_the_image(self):
        message = FakeEmbedMessage(content="nice")
        message.stickers = [FakeSticker("https://cdn/sticker.png")]
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/sticker.png", embed.image.url)
        self.assertEqual("nice", embed.description)

    async def test_shows_a_sticker_sent_as_a_reply_with_the_original_message(self):
        referenced_message = FakeEmbedMessage(content="what do you think", author_name="original")
        message = FakeEmbedMessage(content="", reference_message_id=42, channel=FakeChannel(referenced_message))
        message.stickers = [FakeSticker("https://cdn/sticker.png")]
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/sticker.png", embed.image.url)
        self.assertEqual("what do you think", self.field_named(embed, "original's message:").value)

    async def test_shows_a_reply_with_an_image_attachment(self):
        referenced_message = FakeEmbedMessage(content="original text", author_name="original")
        message = FakeEmbedMessage(content="my reply", reference_message_id=42,
                                   channel=FakeChannel(referenced_message),
                                   attachments=[FakeAttachment("https://cdn/reply.png", "image/png")])
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/reply.png", embed.image.url)
        self.assertEqual("original text", self.field_named(embed, "original's message:").value)
        self.assertEqual("my reply", self.field_named(embed, "author's reply:").value)

    async def test_links_a_reply_attachment_that_is_not_an_image(self):
        referenced_message = FakeEmbedMessage(content="original text", author_name="original")
        message = FakeEmbedMessage(content="my reply", reference_message_id=42,
                                   channel=FakeChannel(referenced_message),
                                   attachments=[FakeAttachment("https://cdn/clip.mp4", "video/mp4")])
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/clip.mp4", self.field_named(embed, "Attachment").value)

    async def test_shows_the_image_of_the_message_that_was_replied_to(self):
        referenced_message = FakeEmbedMessage(content="original", author_name="original",
                                              attachments=[FakeAttachment("https://cdn/original.png", "image/png")])
        message = FakeEmbedMessage(content="my reply", reference_message_id=42,
                                   channel=FakeChannel(referenced_message))
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/original.png", embed.image.url)


class SetFooterTests(unittest.IsolatedAsyncioTestCase):
    async def test_usually_leaves_the_embed_alone(self):
        with mock.patch("utils.random.random", return_value=1.0):
            embed = await utils.set_footer(discord.Embed())

        self.assertEqual([], embed.fields)

    async def test_occasionally_asks_for_a_vote(self):
        with mock.patch("utils.random.random", return_value=0.0):
            embed = await utils.set_footer(discord.Embed())

        self.assertEqual(1, len(embed.fields))
        self.assertIn("top.gg", embed.fields[0].value)

    async def test_never_asks_for_a_vote_on_an_embed_with_an_image(self):
        embed_with_image = discord.Embed()
        embed_with_image.set_image(url="https://cdn/x.png")

        with mock.patch("utils.random.random", return_value=0.0):
            embed = await utils.set_footer(embed_with_image)

        self.assertEqual([], embed.fields)
