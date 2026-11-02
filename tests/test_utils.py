import types
import unittest
from unittest import mock

from tests.fakes import FakeAttachment, FakeGuild, FakeReaction, FakeUser

import discord
import board_post
import json
import utils
from enums import calculation_method_type
from translations import messages


class FakeAuthor(FakeUser):
    def __init__(self, user_id: int, name: str):
        super().__init__(user_id)
        self.name = name
        self.avatar = None
        self.display_avatar = types.SimpleNamespace(url=f"https://cdn.example/avatars/{user_id}.png")


class FakeChannel:
    """Channel that either resolves a referenced message or reports it as deleted."""

    def __init__(self, referenced_message=None):
        self.referenced_message = referenced_message
        self.mention = "<#2>"

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

    def test_truncates_to_a_lower_limit_when_the_field_holds_other_text(self):
        truncated = utils.truncate_content("a" * 2000, limit=900)
        self.assertEqual(900, len(truncated))
        self.assertTrue(truncated.endswith("..."))

    def test_keeps_content_exactly_at_the_limit(self):
        self.assertEqual("a" * 900, utils.truncate_content("a" * 900, limit=900))


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


class EmbedTestCase(unittest.IsolatedAsyncioTestCase):
    """Building posts without a database: the replied-to author is checked against self.opted_out"""

    def setUp(self):
        self.opted_out = set()
        patcher = mock.patch.object(utils.opt_out_repo, "is_opted_out",
                                    lambda _connection, user_id: user_id in self.opted_out)
        patcher.start()
        self.addCleanup(patcher.stop)


class CreateEmbedTests(EmbedTestCase):
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


class PostFooterTests(EmbedTestCase):
    async def test_every_post_layout_carries_the_footer(self):
        referenced_message = FakeEmbedMessage(content="original text", author_name="original")
        sticker_message = FakeEmbedMessage(content="nice")
        sticker_message.stickers = [FakeSticker("https://cdn/sticker.png")]
        layouts = {
            "plain": FakeEmbedMessage(content="a legendary moment"),
            "sticker": sticker_message,
            "reply": FakeEmbedMessage(content="my reply", reference_message_id=42,
                                      channel=FakeChannel(referenced_message)),
            "reply with image": FakeEmbedMessage(content="my reply", reference_message_id=42,
                                                 channel=FakeChannel(referenced_message),
                                                 attachments=[FakeAttachment("https://cdn/r.png", "image/png")]),
            "reply with video": FakeEmbedMessage(content="my reply", reference_message_id=42,
                                                 channel=FakeChannel(referenced_message),
                                                 attachments=[FakeAttachment("https://cdn/c.mp4", "video/mp4")]),
        }
        for layout, message in layouts.items():
            with self.subTest(layout=layout):
                embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)
                self.assertEqual(messages.POST_FOOTER, embed.footer.text)

    async def test_uses_the_bots_global_avatar_as_the_icon(self):
        message = FakeEmbedMessage(content="a legendary moment")
        message.guild.me = types.SimpleNamespace(avatar=types.SimpleNamespace(url="https://cdn/bot.png"))
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual("https://cdn/bot.png", embed.footer.icon_url)

    async def test_leaves_out_the_icon_when_the_bot_has_no_avatar(self):
        message = FakeEmbedMessage(content="a legendary moment")
        message.guild.me = types.SimpleNamespace(avatar=None)
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        self.assertEqual(messages.POST_FOOTER, embed.footer.text)
        self.assertIsNone(embed.footer.icon_url)

    def test_fits_on_one_line(self):
        # Discord allows 2048 characters, but anything past one line turns the brand into a banner
        self.assertLessEqual(len(messages.POST_FOOTER), 60)

    def test_names_the_bot_without_asking_for_an_install(self):
        """The board is the server's showcase, so the install ask lives on replies a member asked for."""
        self.assertIn("Hall of Fame", messages.POST_FOOTER)
        self.assertNotIn("/invite", messages.POST_FOOTER)



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


class CreateEmbedContentTests(EmbedTestCase):
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

    async def test_a_reply_to_a_member_who_is_not_featured_leaves_them_out(self):
        """Their name, words and image would otherwise reach the board with someone else's reply."""
        referenced_message = FakeEmbedMessage(content="their words", author_name="not featured",
                                              attachments=[FakeAttachment("https://cdn/theirs.png", "image/png")])
        referenced_message.author.id = 55
        self.opted_out.add(55)
        message = FakeEmbedMessage(content="my reply", reference_message_id=42,
                                   channel=FakeChannel(referenced_message))
        embed = await utils.create_embed(message, 5, None, REACTION_CONFIG)

        shown = " ".join([embed.description or ""] + [f"{field.name} {field.value}" for field in embed.fields])
        self.assertIn("my reply", shown)
        self.assertNotIn("their words", shown)
        self.assertNotIn("not featured", shown)
        self.assertNotEqual("https://cdn/theirs.png", embed.image.url)


class SpoileredAttachment(FakeAttachment):
    def is_spoiler(self):
        return True


class PostViewTests(EmbedTestCase):
    """The Components V2 post, read from the payload Discord would receive."""

    async def payload(self, message, counted=2):
        view = await board_post.create_post_view(message, None, REACTION_CONFIG, counted)
        [container] = view.to_components()
        return container

    @staticmethod
    def of_type(container, component_type):
        return [component for component in container["components"] if component["type"] == component_type]

    async def test_is_one_gold_container_with_the_author_and_a_jump_button(self):
        container = await self.payload(FakeEmbedMessage("hello", author_name="mia"))

        self.assertEqual(17, container["type"])
        self.assertEqual(discord.Colour.gold().value, container["accent_color"])
        [section] = self.of_type(container, 9)
        self.assertEqual("**mia**\n-# in <#2>", section["components"][0]["content"])
        self.assertEqual("hello", section["components"][1]["content"])
        self.assertEqual("https://cdn.example/avatars/1.png", section["accessory"]["media"]["url"])
        [row] = self.of_type(container, 1)
        self.assertEqual("https://discord.com/channels/1/2/3", row["components"][0]["url"])

    async def test_shows_every_image_and_video_and_keeps_spoilers_covered(self):
        attachments = [SpoileredAttachment("https://cdn/finale.png", "image/png"),
                       FakeAttachment("https://cdn/clip.mp4", "video/mp4"),
                       FakeAttachment("https://cdn/still.jpg?ex=1", None)]
        [gallery] = self.of_type(await self.payload(FakeEmbedMessage("look", attachments=attachments)), 12)

        self.assertEqual(["https://cdn/finale.png", "https://cdn/clip.mp4", "https://cdn/still.jpg?ex=1"],
                         [item["media"]["url"] for item in gallery["items"]])
        self.assertEqual([True, False, False], [item["spoiler"] for item in gallery["items"]])

    async def test_encodes_a_file_name_outside_ascii(self):
        """A clip named ødelagt.mp4 failed to load in a post while the same kind of clip with a plain name played."""
        attachments = [FakeAttachment("https://cdn/a/ødelagt.mp4?ex=1&hm=2", "video/mp4")]
        [gallery] = self.of_type(await self.payload(FakeEmbedMessage(attachments=attachments)), 12)

        self.assertEqual("https://cdn/a/%C3%B8delagt.mp4?ex=1&hm=2", gallery["items"][0]["media"]["url"])

    def test_leaves_a_link_that_is_already_encoded_alone(self):
        url = "https://cdn/a/%C3%B8delagt%20clip.mp4?ex=1&is=2&hm=abc"
        self.assertEqual(url, board_post.ascii_url(url))

    async def test_holds_at_most_ten_pictures(self):
        attachments = [FakeAttachment(f"https://cdn/{index}.png", "image/png") for index in range(12)]
        [gallery] = self.of_type(await self.payload(FakeEmbedMessage(attachments=attachments)), 12)

        self.assertEqual(board_post.post_media_limit, len(gallery["items"]))

    async def test_links_files_that_are_not_pictures(self):
        notes = FakeAttachment("https://cdn/notes.txt", "text/plain")
        notes.filename = "notes.txt"
        container = await self.payload(FakeEmbedMessage("see file", attachments=[notes]))

        self.assertEqual([], self.of_type(container, 12))
        self.assertIn("[notes.txt](https://cdn/notes.txt)", [c["content"] for c in self.of_type(container, 10)])
        self.assertEqual("see file", self.of_type(container, 9)[0]["components"][1]["content"])

    async def test_quotes_the_message_it_replies_to(self):
        replied = FakeEmbedMessage("nobody spoil it", author_name="jonas")
        message = FakeEmbedMessage("covered it", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)

        self.assertEqual("-# Replying to **jonas**\n>>> nobody spoil it", container["components"][0]["content"])
        [section] = self.of_type(container, 9)
        self.assertEqual(["**author**\n-# in <#2>", "covered it"], [c["content"] for c in section["components"]])

    async def test_the_reply_comes_before_the_name_of_who_answered(self):
        """With the quote under the poster's name, the answer did not read as theirs."""
        replied = FakeEmbedMessage("nobody spoil it", author_name="jonas")
        message = FakeEmbedMessage("covered it", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)

        self.assertEqual([10, 14, 9], [component["type"] for component in container["components"]][:3])
        self.assertFalse(container["components"][1]["divider"])

    async def test_shows_the_replied_to_video_before_the_reply(self):
        """Below the reply text, the video looked like the reply's own."""
        replied = FakeEmbedMessage("", author_name="lukas", attachments=[FakeAttachment("https://cdn/clip.mp4", "video/mp4")])
        message = FakeEmbedMessage("test reply to a video", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)
        order = [component["type"] for component in container["components"]]

        self.assertEqual("-# Replying to **lukas**", container["components"][0]["content"])
        self.assertEqual([10, 12, 14, 9], order[:4])
        self.assertEqual("https://cdn/clip.mp4", container["components"][1]["items"][0]["media"]["url"])
        [section] = self.of_type(container, 9)
        self.assertEqual(["**author**\n-# in <#2>", "test reply to a video"],
                         [component["content"] for component in section["components"]])

    async def test_a_reply_with_pictures_of_its_own_shows_only_those(self):
        replied = FakeEmbedMessage("", attachments=[FakeAttachment("https://cdn/theirs.png", "image/png")])
        message = FakeEmbedMessage("mine", reference_message_id=9, channel=FakeChannel(replied),
                                   attachments=[FakeAttachment("https://cdn/mine.png", "image/png")])
        [gallery] = self.of_type(await self.payload(message), 12)

        self.assertEqual(["https://cdn/mine.png"], [item["media"]["url"] for item in gallery["items"]])

    async def test_names_people_as_members_see_them(self):
        message = FakeEmbedMessage("hi", author_name="lukasvamos")
        message.author.display_name = "Lukas"
        [section] = self.of_type(await self.payload(message), 9)

        self.assertEqual("**Lukas**\n-# in <#2>", section["components"][0]["content"])

    async def test_leaves_out_a_reply_to_a_member_who_asked_not_to_be_featured(self):
        replied = FakeEmbedMessage("my words", author_name="private")
        replied.author.id = 44
        self.opted_out.add(44)
        message = FakeEmbedMessage("a reply", reference_message_id=9, channel=FakeChannel(replied))
        [section] = self.of_type(await self.payload(message), 9)

        self.assertEqual(["**author**\n-# in <#2>", "a reply"], [component["content"] for component in section["components"]])

    async def test_lists_every_counted_emoji_and_the_count(self):
        reactions = [FakeReaction("🔥", [1, 2]), FakeReaction("😭", [1, 2, 3, 4]),
                     FakeReaction("👀", [5])]
        container = await self.payload(FakeEmbedMessage(reactions=reactions), counted=4)
        [line] = [c for c in self.of_type(container, 10) if c.get("id") == board_post.POST_REACTIONS_ID]

        self.assertEqual("😭 4 · 🔥 2 · 👀 1", line["content"])

    async def test_adds_the_count_only_when_the_method_counted_something_else(self):
        """Such as total reactions, or the author's own reaction left out."""
        reactions = [FakeReaction("🔥", [1, 2]), FakeReaction("👀", [5])]
        container = await self.payload(FakeEmbedMessage(reactions=reactions), counted=3)
        [line] = [c for c in self.of_type(container, 10) if c.get("id") == board_post.POST_REACTIONS_ID]

        self.assertEqual("🔥 2 · 👀 1\n-# " + messages.POST_COUNTED.format(count=3), line["content"])

    async def test_leaves_names_markdown_as_text(self):
        [section] = self.of_type(await self.payload(FakeEmbedMessage("hi", author_name="*star*")), 9)

        self.assertEqual("**\\*star\\***\n-# in <#2>", section["components"][0]["content"])

    @staticmethod
    def texts(container):
        return [component["content"] for component in container["components"] if component["type"] == 10]

    async def test_without_text_the_name_stands_alone_without_the_avatar(self):
        """A lone name beside the tall avatar left a gap above the picture."""
        container = await self.payload(FakeEmbedMessage(attachments=[FakeAttachment("https://cdn/cat.png", "image/png")]))

        self.assertEqual([], self.of_type(container, 9))
        self.assertEqual("**author**\n-# in <#2>", container["components"][0]["content"])

    async def test_long_text_goes_under_the_header_at_full_width(self):
        long_text = "word " * 100
        container = await self.payload(FakeEmbedMessage(long_text))

        self.assertEqual([], self.of_type(container, 9))
        self.assertIn(long_text.strip(), self.texts(container)[1])

    async def test_keeps_up_to_two_thousand_characters(self):
        container = await self.payload(FakeEmbedMessage("a" * 3000))

        self.assertEqual(board_post.post_text_limit, len(self.texts(container)[1]))

    async def test_quotes_a_long_replied_to_message_briefly(self):
        replied = FakeEmbedMessage("b" * 900, author_name="jonas")
        message = FakeEmbedMessage("short", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)

        quote = container["components"][0]["content"].split(">>> ")[1]
        self.assertEqual(board_post.post_quote_limit, len(quote))

    async def test_says_when_the_replied_to_message_was_deleted(self):
        message = FakeEmbedMessage("what did they say", reference_message_id=9, channel=FakeChannel(None))
        container = await self.payload(message)

        self.assertEqual("-# " + messages.POST_REPLYING_TO_DELETED, container["components"][0]["content"])

    def forward_of(self, original):
        """A forward from the same channel, whose original is fetched to see who wrote it"""
        message = FakeEmbedMessage("", channel=FakeChannel(original))
        message.reference = types.SimpleNamespace(message_id=9, type=discord.MessageReferenceType.forward)
        message.message_snapshots = [types.SimpleNamespace(
            content="the original words", attachments=[FakeAttachment("https://cdn/meme.png", "image/png")],
            embeds=[], stickers=[])]
        return message

    async def test_a_forward_of_a_member_who_opted_out_leaves_their_message_out(self):
        original = FakeEmbedMessage("the original words", author_name="private")
        original.author.id = 44
        self.opted_out.add(44)
        container = await self.payload(self.forward_of(original))
        shown = json.dumps(container, ensure_ascii=False)

        self.assertNotIn("the original words", shown)
        self.assertNotIn("meme.png", shown)
        self.assertIn(messages.POST_FORWARD_NOT_SHOWN, shown)

    async def test_a_reply_whose_author_opts_out_while_the_post_is_built_leaves_them_out(self):
        """The first check runs before the reactions are counted and the forward is fetched."""
        replied = FakeEmbedMessage("my words", author_name="private")
        replied.author.id = 44
        message = FakeEmbedMessage("a reply", reference_message_id=9, channel=FakeChannel(replied))
        shown_body = board_post.shown_body

        async def opt_out_meanwhile(source, connection):
            self.opted_out.add(44)
            return await shown_body(source, connection)

        with mock.patch.object(board_post, "shown_body", opt_out_meanwhile):
            shown = json.dumps(await self.payload(message), ensure_ascii=False)

        self.assertNotIn("my words", shown)
        self.assertNotIn("private", shown)
        self.assertIn("a reply", shown)

    async def test_a_forward_of_a_forward_leaves_it_out(self):
        """The message fetched was written by whoever forwarded it, not by whoever wrote the words."""
        middle = FakeEmbedMessage("", author_name="forwarder")
        middle.message_snapshots = [types.SimpleNamespace(content="the original words", attachments=[],
                                                          embeds=[], stickers=[])]
        shown = json.dumps(await self.payload(self.forward_of(middle)), ensure_ascii=False)

        self.assertNotIn("the original words", shown)
        self.assertIn(messages.POST_FORWARD_NOT_SHOWN, shown)

    async def test_a_forward_with_an_empty_snapshot_says_it_is_not_shown(self):
        """A forward of a forward reached the board as a name over nothing, without saying why."""
        message = self.forward_of(FakeEmbedMessage("the original words", author_name="someone"))
        message.message_snapshots = [types.SimpleNamespace(content="", attachments=[], embeds=[], stickers=[])]
        shown = json.dumps(await self.payload(message), ensure_ascii=False)

        self.assertIn(messages.POST_FORWARD_NOT_SHOWN, shown)

    async def test_a_forward_whose_original_cannot_be_read_leaves_it_out(self):
        """Nobody can tell whose it is, so it is treated like a member who opted out."""
        shown = json.dumps(await self.payload(self.forward_of(None)), ensure_ascii=False)

        self.assertNotIn("the original words", shown)
        self.assertIn(messages.POST_FORWARD_NOT_SHOWN, shown)

    async def test_a_forward_shows_the_message_it_forwards(self):
        message = self.forward_of(FakeEmbedMessage("the original words", author_name="someone"))
        container = await self.payload(message)
        [section] = self.of_type(container, 9)

        self.assertEqual(["**author**\n-# in <#2> · " + messages.POST_FORWARDED, "the original words"],
                         [component["content"] for component in section["components"]])
        [gallery] = self.of_type(container, 12)
        self.assertEqual("https://cdn/meme.png", gallery["items"][0]["media"]["url"])

    async def test_a_poll_shows_its_question_and_votes(self):
        message = FakeEmbedMessage("")
        message.poll = types.SimpleNamespace(question="Best pizza?", answers=[
            types.SimpleNamespace(text="Pineapple", vote_count=12), types.SimpleNamespace(text="Plain", vote_count=1)])
        [section] = self.of_type(await self.payload(message), 9)

        self.assertEqual("-# Poll\n**Best pizza?**\n- Pineapple · 12 votes\n- Plain · 1 vote",
                         section["components"][1]["content"])

    async def test_a_poll_with_words_shows_both(self):
        message = FakeEmbedMessage("Vote please")
        message.poll = types.SimpleNamespace(question="Best pizza?", answers=[
            types.SimpleNamespace(text="Pineapple", vote_count=12)])
        # Short text sits in the section beside the avatar, so the whole payload is searched
        shown = json.dumps(await self.payload(message), ensure_ascii=False)

        self.assertIn("Vote please", shown)
        self.assertIn("**Best pizza?**", shown)
        self.assertIn("Pineapple · 12 votes", shown)

    async def test_a_reply_with_more_than_ten_pictures_says_how_many_are_left_out(self):
        pictures = [FakeAttachment(f"https://cdn/{number}.png", "image/png") for number in range(12)]
        replied = FakeEmbedMessage("", attachments=pictures)
        message = FakeEmbedMessage("nice", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)

        [gallery] = self.of_type(container, 12)
        self.assertEqual(10, len(gallery["items"]))
        self.assertIn(board_post.more_note(2), self.texts(container))

    async def test_a_message_that_is_only_an_image_link_shows_the_picture_alone(self):
        message = FakeEmbedMessage("https://i.example/cat.png")
        message.embeds = [types.SimpleNamespace(type="image", url="https://i.example/cat.png", image=None,
                                                thumbnail=None, video=None)]
        container = await self.payload(message)

        self.assertEqual(["**author**\n-# in <#2>"], self.texts(container)[:1])
        self.assertNotIn("https://i.example/cat.png", " ".join(self.texts(container)))
        [gallery] = self.of_type(container, 12)
        self.assertEqual("https://i.example/cat.png", gallery["items"][0]["media"]["url"])

    @staticmethod
    def gif_message(content="https://tenor.com/view/the-big-leagues-gif-1592824968"):
        message = FakeEmbedMessage(content)
        message.embeds = [types.SimpleNamespace(
            type="gifv", url="https://tenor.com/view/the-big-leagues-gif-1592824968", image=None,
            thumbnail=types.SimpleNamespace(url="https://media.tenor.com/8d3ZrTvq4f0AAAAe/the-big-leagues.png"),
            video=types.SimpleNamespace(url="https://media.tenor.com/8d3ZrTvq4f0AAAPo/the-big-leagues.mp4"))]
        return message

    async def test_a_tenor_gif_shows_as_a_gif_in_place_of_its_link(self):
        """Its MP4 showed as a video player with controls rather than a looping GIF."""
        container = await self.payload(self.gif_message())
        [gallery] = self.of_type(container, 12)

        self.assertEqual("https://media.tenor.com/8d3ZrTvq4f0AAAAC/the-big-leagues.gif", gallery["items"][0]["media"]["url"])
        self.assertNotIn("tenor.com/view", " ".join(self.texts(container)))

    def test_a_gif_from_elsewhere_keeps_its_video(self):
        self.assertEqual("https://media.giphy.example/clip.mp4", board_post.gif_url("https://media.giphy.example/clip.mp4"))

    async def test_a_reply_to_a_gif_shows_the_gif_and_not_its_link(self):
        replied = self.gif_message()
        replied.author = FakeAuthor(3, "Lukas")
        message = FakeEmbedMessage("BIG", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)

        self.assertEqual("-# Replying to **Lukas**", container["components"][0]["content"])
        self.assertEqual("https://media.tenor.com/8d3ZrTvq4f0AAAAC/the-big-leagues.gif",
                         container["components"][1]["items"][0]["media"]["url"])
        [section] = self.of_type(container, 9)
        self.assertEqual("BIG", section["components"][1]["content"])

    async def test_a_reply_to_a_link_with_words_quotes_the_words(self):
        replied = self.gif_message("look at this https://tenor.com/view/the-big-leagues-gif-1592824968")
        message = FakeEmbedMessage("BIG", reference_message_id=9, channel=FakeChannel(replied))
        container = await self.payload(message)

        self.assertIn(">>> look at this", container["components"][0]["content"])

    async def test_a_link_with_words_keeps_its_text(self):
        message = FakeEmbedMessage("we made the news https://news.example/story")
        message.embeds = [types.SimpleNamespace(type="rich", url="https://news.example/story",
                                                image=types.SimpleNamespace(url="https://news.example/hero.jpg"),
                                                thumbnail=None, video=None)]
        [section] = self.of_type(await self.payload(message), 9)

        self.assertEqual("we made the news https://news.example/story", section["components"][1]["content"])

    async def test_an_animated_sticker_is_named(self):
        message = FakeEmbedMessage("")
        message.stickers = [types.SimpleNamespace(name="Wumpus", url="https://media/w.json",
                                                  format=discord.StickerFormatType.lottie)]
        container = await self.payload(message)

        self.assertEqual([], self.of_type(container, 12))
        [section] = self.of_type(container, 9)
        self.assertEqual("*" + messages.POST_STICKER.format(name="Wumpus") + "*", section["components"][1]["content"])

    async def test_an_animated_sticker_with_words_is_named_under_them(self):
        message = FakeEmbedMessage("hello")
        message.stickers = [types.SimpleNamespace(name="Wumpus", url="https://media/w.json",
                                                  format=discord.StickerFormatType.lottie)]

        self.assertIn("-# " + messages.POST_STICKER.format(name="Wumpus"), self.texts(await self.payload(message)))

    async def test_says_how_many_pictures_and_files_did_not_fit(self):
        pictures = [FakeAttachment(f"https://cdn/{index}.png", "image/png") for index in range(12)]
        files = []
        for index in range(7):
            file = FakeAttachment(f"https://cdn/{index}.pdf", "application/pdf")
            file.filename = f"{index}.pdf"
            files.append(file)
        texts = self.texts(await self.payload(FakeEmbedMessage("dump", attachments=pictures + files)))

        self.assertIn("-# " + messages.POST_MORE_IN_ORIGINAL.format(count=2), texts)
        self.assertTrue(texts[-2].endswith("-# " + messages.POST_MORE_IN_ORIGINAL.format(count=2)))

    async def test_counts_the_emojis_that_did_not_fit(self):
        reactions = [FakeReaction(chr(0x1F600 + index), [index]) for index in range(1, 12)]
        container = await self.payload(FakeEmbedMessage("chaos", reactions=reactions), counted=1)
        [line] = [c for c in self.of_type(container, 10) if c.get("id") == board_post.POST_REACTIONS_ID]

        self.assertTrue(line["content"].endswith(" · +3"))


class CustomProfileFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_field_is_a_label_around_its_input_with_the_current_url(self):
        modals = []

        async def send_modal(modal):
            modals.append(modal)

        interaction = types.SimpleNamespace(response=types.SimpleNamespace(send_modal=send_modal))
        await utils.create_custom_profile_picture_and_cover_form(interaction, None, "https://cdn/avatar.png")
        components = modals[0].to_components()

        self.assertEqual(["Custom Profile Picture URL", "Custom Cover Image URL"],
                         [component["label"] for component in components])
        self.assertEqual("https://cdn/avatar.png", components[0]["component"]["value"])
        self.assertTrue(all(component["component"].get("label") is None for component in components))


if __name__ == "__main__":
    unittest.main()
