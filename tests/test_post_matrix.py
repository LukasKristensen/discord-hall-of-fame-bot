"""Every kind of media a message can carry, alone, mixed and in replies, as a board post.

Listing cases one by one missed the crossings: a reply to a GIF quoted its raw link because replies and link
previews were only ever tested apart, and a message with an attachment dropped its link preview. So every kind
of message below is crossed with every reply target, every two kinds of media are mixed into one message, and
each post is checked against what must hold for all of them: every piece of the message and the one it answers
can be recognised, a link never shows next to the picture standing in for it, spoilers stay covered, media
Discord flagged is never shown from a reply, nothing of a member who asked not to be featured appears, and the
post stays inside Discord's limits.

What only Discord's rendering shows, such as a GIF looping rather than playing as a video, is not checked
here. RELEASE_TEST_PLAN.md lists those.
"""

import asyncio
import itertools
import types
import unittest
from unittest import mock

import discord

import board_post
import utils

OPTED_OUT_ID = 66
TENOR_PAGE = "https://tenor.com/view/the-big-leagues-gif-1592824968"
TENOR_MP4 = "https://media.tenor.com/8d3ZrTvq4f0AAAPo/the-big-leagues.mp4"
TENOR_GIF = "the-big-leagues.gif"
CONFIG = {"custom_emoji_check_logic": False, "whitelisted_emojis": []}
# Discord's limits on one Components V2 message
MAX_COMPONENTS = 40
MAX_TEXT = 4000


def attachment(name, content_type, spoiler=False, flags=0):
    item = types.SimpleNamespace(url=f"https://cdn.example/{name}?ex=1&hm=abcdef", content_type=content_type,
                                 filename=name, flags=types.SimpleNamespace(value=flags))
    item.is_spoiler = lambda: spoiler
    return item


def embed(kind, url=None, image=None, thumbnail=None, video=None):
    wrap = lambda link: types.SimpleNamespace(url=link) if link else None  # noqa: E731
    return types.SimpleNamespace(type=kind, url=url, image=wrap(image), thumbnail=wrap(thumbnail), video=wrap(video),
                                 flags=None)


def sticker(name, lottie=False):
    return types.SimpleNamespace(name=name, url=f"https://media.example/{name.lower()}.{'json' if lottie else 'png'}",
                                 format=discord.StickerFormatType.lottie if lottie else discord.StickerFormatType.png)


class Message:
    def __init__(self, content="", attachments=(), stickers=(), embeds=(), author_id=1, name="Mia", voice=False):
        self.id = author_id * 100
        self.content = content
        self.attachments = list(attachments)
        self.stickers = list(stickers)
        self.embeds = list(embeds)
        self.flags = types.SimpleNamespace(voice=voice)
        self.author = types.SimpleNamespace(id=author_id, name=name.lower(), display_name=name,
                                            display_avatar=types.SimpleNamespace(url=f"https://cdn.example/{name}.png"))
        self.guild = types.SimpleNamespace(id=9)
        self.reference = None
        self.reactions = [types.SimpleNamespace(emoji="<:pepe_laughing_really_hard:123456789012345678>", count=7),
                          types.SimpleNamespace(emoji="\U0001F525", count=3)]
        self.jump_url = "https://discord.com/channels/9/500/1"
        self.channel = Channel()


class Channel:
    def __init__(self, replied=None, deleted=False):
        self.id = 500
        self.mention = "<#500>"
        self.replied = replied
        self.deleted = deleted

    async def fetch_message(self, _message_id):
        if self.deleted or self.replied is None:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.replied


def forward(**kwargs):
    message = Message(**kwargs)
    message.reference = types.SimpleNamespace(message_id=5, channel_id=777, guild_id=9,
                                              type=discord.MessageReferenceType.forward)
    # The original is fetched to check its author has not opted out, so the matrix gives it one who has not
    original = Message(author_id=7, name="Ola")
    message.guild = types.SimpleNamespace(id=9, get_channel_or_thread=lambda _channel_id: Channel(replied=original))
    message.message_snapshots = [types.SimpleNamespace(
        content="forwarded words", attachments=[attachment("forwarded.png", "image/png")], embeds=[], stickers=[],
        flags=types.SimpleNamespace(voice=False))]
    return message


def poll(**kwargs):
    message = Message(**kwargs)
    message.poll = types.SimpleNamespace(question="Best topping?", answers=[
        types.SimpleNamespace(text="Pineapple", emoji=None, vote_count=3),
        types.SimpleNamespace(text="", emoji="\U0001F355", vote_count=1)])
    return message


LONG_NAMES = [attachment(f"{'very-long-file-name-' * 9}{index}.pdf", "application/pdf") for index in range(7)]

# Each kind: how to build it, then what of it must show on a post: links of the gallery, and words
KINDS = {
    "text": (lambda **k: Message("a joke worth keeping", **k), [], ["a joke worth keeping"]),
    "long text": (lambda **k: Message("long " * 500, **k), [], ["long long long"]),
    "image": (lambda **k: Message(attachments=[attachment("cat.png", "image/png")], **k), ["cat.png"], []),
    "gif file": (lambda **k: Message(attachments=[attachment("party.gif", "image/gif")], **k), ["party.gif"], []),
    "video": (lambda **k: Message(attachments=[attachment("jump.mp4", "video/mp4")], **k), ["jump.mp4"], []),
    "mov video": (lambda **k: Message(attachments=[attachment("phone.mov", "video/quicktime")], **k), ["phone.mov"], []),
    "spoilered image": (lambda **k: Message(attachments=[attachment("finale.png", "image/png", spoiler=True)], **k),
                        ["finale.png"], []),
    "file": (lambda **k: Message(attachments=[attachment("rules.pdf", "application/pdf")], **k), [], ["rules.pdf"]),
    "long file names": (lambda **k: Message("text " * 380, attachments=LONG_NAMES, **k), [], ["text text"]),
    "audio": (lambda **k: Message(attachments=[attachment("song.mp3", "audio/mpeg")], **k), [], ["song.mp3"]),
    "voice message": (lambda **k: Message(attachments=[attachment("voice-message.ogg", "audio/ogg")], voice=True, **k),
                      [], ["Voice message"]),
    "sticker": (lambda **k: Message(stickers=[sticker("Wave")], **k), ["wave.png"], []),
    "animated sticker": (lambda **k: Message(stickers=[sticker("Wumpus", lottie=True)], **k), [], ["Wumpus"]),
    "three stickers": (lambda **k: Message(stickers=[sticker("Wave"), sticker("Clap"), sticker("Wumpus", lottie=True)], **k),
                       ["wave.png", "clap.png"], ["Wumpus"]),
    "image link": (lambda **k: Message("https://i.example/meme.png", embeds=[embed("image", url="https://i.example/meme.png")], **k),
                   ["meme.png"], []),
    "two image links": (lambda **k: Message("https://i.example/a.png https://i.example/b.png", embeds=[
        embed("image", url="https://i.example/a.png"), embed("image", url="https://i.example/b.png")], **k), ["a.png", "b.png"], []),
    "gif": (lambda **k: Message(TENOR_PAGE, embeds=[embed("gifv", url=TENOR_PAGE, thumbnail="https://media.tenor.com/x.png",
                                                          video=TENOR_MP4)], **k), [TENOR_GIF], []),
    "gif with words": (lambda **k: Message(f"so true {TENOR_PAGE}", embeds=[embed(
        "gifv", url=TENOR_PAGE, thumbnail="https://media.tenor.com/x.png", video=TENOR_MP4)], **k), [TENOR_GIF], ["so true"]),
    "video file link": (lambda **k: Message("https://files.example/clip.webm", embeds=[embed(
        "video", url="https://files.example/clip.webm", thumbnail="https://files.example/clip.jpg",
        video="https://files.example/clip.webm")], **k), ["clip.webm"], []),
    "youtube link": (lambda **k: Message("https://youtu.be/abc", embeds=[embed(
        "video", url="https://youtu.be/abc", thumbnail="https://i.ytimg.example/abc.jpg",
        video="https://www.youtube.com/embed/abc")], **k), ["abc.jpg"], ["youtu.be/abc"]),
    "article": (lambda **k: Message("we made the news https://news.example/a", embeds=[embed(
        "rich", url="https://news.example/a", image="https://news.example/hero.jpg")], **k), ["hero.jpg"], ["we made the news"]),
    "multi-image preview": (lambda **k: Message("https://social.example/post/1", embeds=[
        embed("rich", url="https://social.example/post/1", image=f"https://social.example/{index}.jpg") for index in range(4)], **k),
                            [f"{index}.jpg" for index in range(4)], []),
    "image and article": (lambda **k: Message("source https://news.example/a", attachments=[attachment("shot.png", "image/png")],
                                              embeds=[embed("rich", url="https://news.example/a", image="https://news.example/hero.jpg")], **k),
                          ["shot.png", "hero.jpg"], ["source"]),
    "forward": (forward, ["forwarded.png"], ["forwarded words", board_post.messages.POST_FORWARDED]),
    "poll": (poll, [], ["Best topping?", "Pineapple", "\U0001F355"]),
}
# Kinds that are a whole message in their own right, never mixed with others. Long text is cut at 2,000
# characters, which would cut the other kind's words; it is crossed with every reply on its own
WHOLE_MESSAGES = ("forward", "poll", "long file names", "voice message", "long text")
REPLY_STATES = ("no reply", "deleted", "opted out", "flagged image")
FLAGGED = "flagged.png"


def build(make, reply):
    message = make()
    if reply == "no reply" or getattr(message, "message_snapshots", None):
        return message, None
    message.reference = types.SimpleNamespace(message_id=8)
    if reply == "deleted":
        message.channel = Channel(deleted=True)
        return message, None
    if reply == "opted out":
        replied = Message("my words", attachments=[attachment("private.png", "image/png")], author_id=OPTED_OUT_ID, name="Private")
    elif reply == "flagged image":
        replied = Message(attachments=[attachment(FLAGGED, "image/png", flags=board_post.GORE_CONTENT)], author_id=2, name="Jonas")
    else:
        replied = KINDS[reply][0](author_id=2, name="Jonas")
    message.channel = Channel(replied)
    return message, replied


def mixed(first, second):
    """One message carrying both kinds: their words, attachments, stickers and link previews together"""
    def make(**kwargs):
        one, two = KINDS[first][0](**kwargs), KINDS[second][0](**kwargs)
        return Message(" ".join(part for part in (one.content, two.content) if part),
                       attachments=one.attachments + two.attachments, stickers=one.stickers + two.stickers,
                       embeds=one.embeds + two.embeds, **kwargs)
    return make, KINDS[first][1] + KINDS[second][1], KINDS[first][2] + KINDS[second][2]


def walk(components):
    for component in components:
        yield component
        yield from walk(component.get("components", []))
        if "accessory" in component:
            yield component["accessory"]


def texts(payload):
    return [component["content"] for component in walk(payload) if component["type"] == 10]


def gallery_items(payload):
    return [item for component in walk(payload) if component["type"] == 12 for item in component["items"]]


class PostMatrixTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(utils.opt_out_repo, "is_opted_out", lambda _c, user_id: user_id == OPTED_OUT_ID)
        patcher.start()
        self.addCleanup(patcher.stop)

    def payload(self, message):
        return asyncio.run(board_post.create_post_view(message, None, CONFIG, 7)).to_components()

    def test_every_kind_with_every_reply(self):
        for kind, (make, links, words) in KINDS.items():
            for reply in (*REPLY_STATES, *KINDS):
                with self.subTest(featured=kind, replies_to=reply):
                    message, replied = build(make, reply)
                    self.check(message, replied, reply, links, words)

    def test_every_two_kinds_mixed_in_one_message(self):
        mixable = [kind for kind in KINDS if kind not in WHOLE_MESSAGES]
        for first, second in itertools.combinations(mixable, 2):
            make, links, words = mixed(first, second)
            for reply in ("no reply", "image", "gif"):
                with self.subTest(mixes=f"{first} + {second}", replies_to=reply):
                    message, replied = build(make, reply)
                    self.check(message, replied, reply, links, words)

    def check(self, message, replied, reply, links, words):
        payload = self.payload(message)
        all_text = "\n".join(texts(payload))
        items = gallery_items(payload)
        shown = [item["media"]["url"] for item in items]

        # Inside Discord's limits, and no section left with only the name beside the avatar
        self.assertLessEqual(sum(1 for _ in walk(payload)), MAX_COMPONENTS)
        self.assertLessEqual(len(all_text), MAX_TEXT)
        for component in walk(payload):
            if component["type"] == 12:
                self.assertLessEqual(len(component["items"]), board_post.post_media_limit)
            if component["type"] == 9:
                self.assertGreaterEqual(len(component["components"]), 2, "a name alone beside the avatar")

        # Every piece of the message can be recognised: in the gallery, or counted in a note when it did not fit
        own_media = [link for link in links if any(link in url for url in shown)]
        if len(own_media) < len(links):
            self.assertIn("more in the original message", all_text, f"{set(links) - set(own_media)} vanished")
        for word in words:
            self.assertIn(word, all_text)
        for item in items:
            if "finale.png" in item["media"]["url"]:
                self.assertTrue(item["spoiler"], "a spoiler shown uncovered")

        # A link that is the whole message never shows on a line of its own: its picture stands in for it
        lines = [line.removeprefix(">>> ").strip() for text in texts(payload) for line in text.split("\n")]
        for source in (message, replied):
            if source is not None and source.content.startswith("https://") and " " not in source.content and \
                    source.embeds and all(kind in board_post.PREVIEWS_REPLACING_LINK for kind in board_post.preview_media(source)[1]):
                self.assertNotIn(source.content, lines)
        # A link straight to a video file is one of them, as Discord shows only the video
        if message.content == "https://files.example/clip.webm":
            self.assertNotIn(message.content, lines)

        # The message it answers. A forward is never a reply, and nothing of a member who opted out shows
        is_forward = bool(getattr(message, "message_snapshots", None))
        if reply in ("no reply", "opted out") or is_forward:
            self.assertNotIn("Replying to", all_text)
            self.assertFalse(any("private.png" in url for url in shown))
            self.assertNotIn("Private", all_text)
            self.assertNotIn("my words", all_text)
        elif reply == "deleted":
            self.assertIn(board_post.messages.POST_REPLYING_TO_DELETED, all_text)
        else:
            reply_line = next(text for text in texts(payload) if "Replying to **Jonas**" in text)
            self.assertFalse(any(FLAGGED in url for url in shown), "flagged media shown from a reply")
            answered = KINDS[reply][1] if reply in KINDS else []
            identified = reply_line.strip() != "-# Replying to **Jonas**" or any(
                link in url for link in answered for url in shown)
            self.assertTrue(identified, "nothing says what was replied to")

        # Who wrote what: the message answered comes first, then the poster's name above their own words
        ordered = texts(payload)
        name_at = next(index for index, text in enumerate(ordered) if text.startswith("**Mia**"))
        for index, text in enumerate(ordered):
            if "Replying to" in text:
                self.assertLess(index, name_at, "the reply sits under the poster's name")
        for word in words:
            # The quote above may hold the same words when a message answers one of its own kind
            if word != board_post.messages.POST_FORWARDED:
                self.assertTrue(any(word in text for text in ordered[name_at:]),
                                f"{word!r} is not under the name of who wrote it")


if __name__ == "__main__":
    unittest.main()
