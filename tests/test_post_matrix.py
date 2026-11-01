"""Every kind of featured message crossed with every kind of message it can reply to, as a board post.

Listing cases one by one missed the crossings: a reply to a GIF quoted its raw link because replies and link
previews were only ever tested apart. So each kind of message below is crossed with every reply target, and
each post is checked against what must hold for all of them: the message and the one it answers can be
recognised, a link is never shown next to the picture that stands in for it, nothing of a member who asked
not to be featured appears, and the post stays inside Discord's limits.

What only Discord's rendering can show, such as a GIF looping rather than playing as a video, is not
checked here. RELEASE_TEST_PLAN.md lists those.
"""

import asyncio
import types
import unittest
from unittest import mock

import discord

import utils

OPTED_OUT_ID = 66
TENOR_PAGE = "https://tenor.com/view/the-big-leagues-gif-1592824968"
TENOR_MP4 = "https://media.tenor.com/8d3ZrTvq4f0AAAPo/the-big-leagues.mp4"
CONFIG = {"custom_emoji_check_logic": False, "whitelisted_emojis": []}
# Discord's limits on one Components V2 message
MAX_COMPONENTS = 40
MAX_TEXT = 4000


def attachment(name, content_type, spoiler=False):
    item = types.SimpleNamespace(url=f"https://cdn.example/{name}?ex=1", content_type=content_type, filename=name)
    item.is_spoiler = lambda: spoiler
    return item


def embed(kind, url=None, image=None, thumbnail=None, video=None):
    wrap = lambda link: types.SimpleNamespace(url=link) if link else None  # noqa: E731
    return types.SimpleNamespace(type=kind, url=url, image=wrap(image), thumbnail=wrap(thumbnail), video=wrap(video))


class Message:
    def __init__(self, content="", attachments=(), stickers=(), embeds=(), author_id=1, name="Mia"):
        self.id = author_id * 100
        self.content = content
        self.attachments = list(attachments)
        self.stickers = list(stickers)
        self.embeds = list(embeds)
        self.author = types.SimpleNamespace(id=author_id, name=name.lower(), display_name=name,
                                            display_avatar=types.SimpleNamespace(url=f"https://cdn.example/{name}.png"))
        self.guild = types.SimpleNamespace(id=9)
        self.reference = None
        self.reactions = [types.SimpleNamespace(emoji="\U0001F525", count=7)]
        self.jump_url = "https://discord.com/channels/9/500/1"
        self.channel = Channel()


class Channel:
    def __init__(self, replied=None, deleted=False):
        self.mention = "<#500>"
        self.replied = replied
        self.deleted = deleted

    async def fetch_message(self, _message_id):
        if self.deleted or self.replied is None:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.replied


def forward(**kwargs):
    message = Message(**kwargs)
    message.reference = types.SimpleNamespace(message_id=5, type=discord.MessageReferenceType.forward)
    message.message_snapshots = [types.SimpleNamespace(
        content="forwarded words", attachments=[attachment("forwarded.png", "image/png")], embeds=[], stickers=[])]
    return message


def poll(**kwargs):
    message = Message(**kwargs)
    message.poll = types.SimpleNamespace(question="Best topping?", answers=[types.SimpleNamespace(text="Pineapple", vote_count=3)])
    return message


# Each kind: how to build it, and what of it must show on a post: a picture's link, or words
KINDS = {
    "text": (lambda **k: Message("a joke worth keeping", **k), "words", "a joke worth keeping"),
    "long text": (lambda **k: Message("long " * 500, **k), "words", "long long long"),
    "image": (lambda **k: Message(attachments=[attachment("cat.png", "image/png")], **k), "media", "cat.png"),
    "captioned image": (lambda **k: Message("look", attachments=[attachment("dog.png", "image/png")], **k), "media", "dog.png"),
    "video": (lambda **k: Message(attachments=[attachment("jump.mp4", "video/mp4")], **k), "media", "jump.mp4"),
    "spoilered image": (lambda **k: Message(attachments=[attachment("finale.png", "image/png", spoiler=True)], **k),
                        "media", "finale.png"),
    "file": (lambda **k: Message(attachments=[attachment("rules.pdf", "application/pdf")], **k), "words", "rules.pdf"),
    "sticker": (lambda **k: Message(stickers=[types.SimpleNamespace(name="Wave", url="https://media.example/wave.png",
                                                                    format=discord.StickerFormatType.png)], **k),
                "media", "wave.png"),
    "animated sticker": (lambda **k: Message(stickers=[types.SimpleNamespace(
        name="Wumpus", url="https://media.example/wumpus.json", format=discord.StickerFormatType.lottie)], **k),
                         "words", "Wumpus"),
    "image link": (lambda **k: Message("https://i.example/meme.png", embeds=[embed("image", url="https://i.example/meme.png")], **k),
                   "media", "meme.png"),
    "gif": (lambda **k: Message(TENOR_PAGE, embeds=[embed("gifv", url=TENOR_PAGE, thumbnail="https://media.tenor.com/x.png",
                                                          video=TENOR_MP4)], **k), "media", "the-big-leagues.gif"),
    "gif with words": (lambda **k: Message(f"so true {TENOR_PAGE}", embeds=[embed(
        "gifv", url=TENOR_PAGE, thumbnail="https://media.tenor.com/x.png", video=TENOR_MP4)], **k), "media", "the-big-leagues.gif"),
    "video link": (lambda **k: Message("https://youtu.be/abc", embeds=[embed("video", url="https://youtu.be/abc",
                                                                           thumbnail="https://i.ytimg.example/abc.jpg")], **k),
                   "media", "abc.jpg"),
    "article": (lambda **k: Message("we made the news https://news.example/a", embeds=[embed(
        "rich", url="https://news.example/a", image="https://news.example/hero.jpg")], **k), "media", "hero.jpg"),
    "forward": (forward, "media", "forwarded.png"),
    "poll": (poll, "words", "Best topping?"),
}
# What a featured message can reply to, besides every kind above
REPLY_STATES = ("no reply", "deleted", "opted out")


def build(kind, reply):
    make, _, _ = KINDS[kind]
    message = make()
    if reply == "no reply" or kind == "forward":
        return message, None
    message.reference = types.SimpleNamespace(message_id=8)
    if reply == "deleted":
        message.channel = Channel(deleted=True)
        return message, None
    if reply == "opted out":
        replied = KINDS["captioned image"][0](author_id=OPTED_OUT_ID, name="Private")
    else:
        replied = KINDS[reply][0](author_id=2, name="Jonas")
    message.channel = Channel(replied)
    return message, replied


def walk(components):
    for component in components:
        yield component
        yield from walk(component.get("components", []))
        if "component" in component:
            yield from walk([component["component"]])
        if "accessory" in component:
            yield component["accessory"]


def texts(payload):
    return [component["content"] for component in walk(payload) if component["type"] == 10]


def gallery_links(payload):
    return [item["media"]["url"] for component in walk(payload) if component["type"] == 12 for item in component["items"]]


class PostMatrixTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(utils.opt_out_repo, "is_opted_out", lambda _c, user_id: user_id == OPTED_OUT_ID)
        patcher.start()
        self.addCleanup(patcher.stop)

    def payload(self, message):
        return asyncio.run(utils.create_post_view(message, None, CONFIG, 7)).to_components()

    def test_every_crossing(self):
        for kind in KINDS:
            for reply in (*REPLY_STATES, *KINDS):
                with self.subTest(featured=kind, replies_to=reply):
                    message, replied = build(kind, reply)
                    self.check(kind, reply, message, replied, self.payload(message))

    def check(self, kind, reply, message, replied, payload):
        all_text = "\n".join(texts(payload))
        links = gallery_links(payload)

        # Inside Discord's limits, and no section left with only the name beside the avatar
        self.assertLessEqual(sum(1 for _ in walk(payload)), MAX_COMPONENTS)
        self.assertLessEqual(len(all_text), MAX_TEXT)
        for section in (c for c in walk(payload) if c["type"] == 9):
            self.assertGreaterEqual(len(section["components"]), 2, "a name alone beside the avatar")

        # The featured message can be recognised
        _, shows, mark = KINDS[kind]
        if shows == "media":
            self.assertTrue(any(mark in link for link in links), f"{mark} is not shown")
        else:
            self.assertIn(mark, all_text)
        if kind == "spoilered image":
            spoilers = [item["spoiler"] for c in walk(payload) if c["type"] == 12 for item in c["items"]
                        if "finale.png" in item["media"]["url"]]
            self.assertEqual([True], spoilers)

        # A link that is the whole message never shows on a line of its own: its picture stands in for it. A
        # link among words keeps its words, and so its link
        lines = [line.removeprefix(">>> ").strip() for text in texts(payload) for line in text.split("\n")]
        for source in (message, replied):
            if source is not None and source.content.startswith("https://") and " " not in source.content \
                    and source.embeds and source.embeds[0].type in utils.PREVIEWS_REPLACING_LINK:
                self.assertNotIn(source.content, lines)

        # The message it answers
        if reply in ("no reply",) or kind == "forward":
            self.assertNotIn("Replying to", all_text)
        elif reply == "deleted":
            self.assertIn(utils.messages.POST_REPLYING_TO_DELETED, all_text)
        elif reply == "opted out":
            self.assertNotIn("Replying to", all_text)
            self.assertNotIn("Private", all_text)
            self.assertFalse(any("dog.png" in link for link in links if kind != "captioned image"))
        else:
            self.assertIn("Replying to Jonas", all_text)
            reply_line = next(text for text in texts(payload) if "Replying to Jonas" in text)
            _, reply_shows, reply_mark = KINDS[reply]
            identified = reply_line.strip() != "-# Replying to Jonas" or \
                (reply_shows == "media" and any(reply_mark in link for link in links))
            self.assertTrue(identified, "nothing says what was replied to")


if __name__ == "__main__":
    unittest.main()
