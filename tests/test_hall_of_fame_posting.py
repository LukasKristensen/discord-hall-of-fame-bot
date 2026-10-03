"""Tests for the helpers that put a message on the board and keep it up to date.

``validate_message`` decides what should happen; these are the three things it can decide on. They
are where the bot writes to Discord and to the database in the same breath, so the cases that matter
are the ones where the two can disagree: a database write that fails after the message is already
posted, a post whose embed was removed while it was hidden, and a video that has to survive as a
separate message.
"""

import unittest
from unittest import mock

import discord

import utils
from caches import ExpiringSet

from tests.fakes import FakeConnection
from tests.test_server_class import build_server

GUILD_ID = 200
SOURCE_CHANNEL_ID = 100
TARGET_CHANNEL_ID = 999
MESSAGE_ID = 4242
HALL_OF_FAME_MESSAGE_ID = 5555
VIDEO_LINK_MESSAGE_ID = 6666
AUTHOR_ID = 77


class FakeAttachment:
    def __init__(self, url="https://cdn.example/clip.mp4"):
        self.url = url


class FakeAuthor:
    def __init__(self):
        self.id = AUTHOR_ID
        self.name = "Author"


class FakeGuild:
    def __init__(self):
        self.id = GUILD_ID
        self.name = "Test Server"


class FakeChannelStub:
    def __init__(self, channel_id=SOURCE_CHANNEL_ID):
        self.id = channel_id


class FakeSourceMessage:
    def __init__(self, attachments=(), message_id=MESSAGE_ID):
        self.id = message_id
        self.guild = FakeGuild()
        self.channel = FakeChannelStub()
        self.author = FakeAuthor()
        self.attachments = list(attachments)
        self.reactions = []
        self.content = "a memorable message"


class FakePostedMessage:
    def __init__(self, message_id, embeds=(), content=""):
        self.id = message_id
        self.embeds = list(embeds)
        self.content = content
        self.edits = []
        self.deleted = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)

    async def delete(self):
        self.deleted = True


class FakeTargetChannel:
    def __init__(self, messages=None, next_id=7000):
        self.id = TARGET_CHANNEL_ID
        self.messages = messages if messages is not None else {}
        self.sent = []
        self.next_id = next_id

    async def send(self, content=None, embed=None):
        message = FakePostedMessage(self.next_id, embeds=[embed] if embed else [], content=content or "")
        self.next_id += 1
        self.sent.append(message)
        return message

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise AssertionError(f"fetched an unexpected message id: {message_id!r}")
        return self.messages[message_id]


class FakeBot:
    def __init__(self, channels):
        self.channels = channels

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


class PostingTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logged = []

        async def record_log(_bot, message, *args, **kwargs):
            self.logged.append(str(message))

        self.reaction_total = 12

        async def count_reactions(*_args, **_kwargs):
            return self.reaction_total

        self.embed = discord.Embed(title="an embed")

        async def build_embed(*_args, **_kwargs):
            return self.embed

        self.patch(utils, "logging", record_log)
        self.patch(utils, "reaction_count", count_reactions)
        self.patch(utils, "create_embed", build_embed)

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch(self, target, name, replacement):
        patcher = mock.patch.object(target, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def patch_repo(self, insert=None):
        self.inserted = []

        def record_insert(*args):
            self.inserted.append(args)
            if insert:
                insert()

        repo = mock.Mock()
        repo.insert_hall_of_fame_message = record_insert
        self.patch(utils, "hall_of_fame_message_repo", repo)
        return repo


class PostHallOfFameMessageTests(PostingTestCase):
    def setUp(self):
        super().setUp()
        self.target_channel = FakeTargetChannel()
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.target_channel})

    async def post(self, message=None):
        await utils.post_hall_of_fame_message(
            message or FakeSourceMessage(), self.bot, FakeConnection(), TARGET_CHANNEL_ID, 5)

    async def test_posts_the_embed_to_the_hall_of_fame_channel(self):
        self.patch_repo()
        await self.post()

        self.assertEqual(1, len(self.target_channel.sent))
        self.assertEqual([self.embed], self.target_channel.sent[0].embeds)

    async def test_records_the_message_on_the_board(self):
        self.patch_repo()
        await self.post()

        _connection, message_id, channel_id, guild_id, hall_of_fame_id = self.inserted[0][:5]
        self.assertEqual((MESSAGE_ID, SOURCE_CHANNEL_ID, GUILD_ID), (message_id, channel_id, guild_id))
        self.assertEqual(self.target_channel.sent[0].id, hall_of_fame_id)

    async def test_records_the_count_and_the_author(self):
        self.patch_repo()
        self.reaction_total = 9
        await self.post()

        self.assertEqual(9, self.inserted[0][5])
        self.assertEqual(AUTHOR_ID, self.inserted[0][6])

    async def test_posts_a_video_as_its_own_message_so_it_stays_playable(self):
        self.patch_repo()
        await self.post(FakeSourceMessage(attachments=[FakeAttachment("https://cdn.example/clip.mp4")]))

        self.assertEqual(2, len(self.target_channel.sent))
        self.assertEqual("https://cdn.example/clip.mp4", self.target_channel.sent[0].content)

    async def test_records_the_video_message_alongside_the_post(self):
        self.patch_repo()
        await self.post(FakeSourceMessage(attachments=[FakeAttachment("https://cdn.example/clip.mp4")]))

        self.assertEqual(self.target_channel.sent[0].id, self.inserted[0][8])

    async def test_records_no_video_message_for_an_image(self):
        self.patch_repo()
        await self.post(FakeSourceMessage(attachments=[FakeAttachment("https://cdn.example/photo.png")]))

        self.assertIsNone(self.inserted[0][8])

    async def test_takes_the_post_back_down_when_it_cannot_be_recorded(self):
        """A post the database does not know about can never be updated or hidden again."""
        self.patch_repo(insert=lambda: (_ for _ in ()).throw(RuntimeError("write failed")))
        await self.post()

        self.assertTrue(self.target_channel.sent[0].deleted)

    async def test_takes_the_video_message_down_too(self):
        self.patch_repo(insert=lambda: (_ for _ in ()).throw(RuntimeError("write failed")))
        await self.post(FakeSourceMessage(attachments=[FakeAttachment("https://cdn.example/clip.mp4")]))

        self.assertTrue(all(message.deleted for message in self.target_channel.sent))

    async def test_reports_a_failed_write(self):
        self.patch_repo(insert=lambda: (_ for _ in ()).throw(RuntimeError("write failed")))
        await self.post()

        self.assertTrue(any("write failed" in entry for entry in self.logged))

    async def test_posts_nothing_when_the_hall_of_fame_channel_is_gone(self):
        self.patch_repo()
        self.bot = FakeBot({})
        await self.post()

        self.assertEqual([], self.target_channel.sent)
        self.assertEqual([], self.inserted)

    async def test_reports_a_missing_hall_of_fame_channel(self):
        self.patch_repo()
        self.bot = FakeBot({})
        await self.post()

        self.assertTrue(any("Could not find the Hall of Fame channel" in entry for entry in self.logged))


class UpdateReactionCounterTests(PostingTestCase):
    def setUp(self):
        super().setUp()
        self.posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[self.embed_with_reactions("5 🔥")])
        self.target_channel = FakeTargetChannel(messages={HALL_OF_FAME_MESSAGE_ID: self.posted})
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.target_channel})

    @staticmethod
    def embed_with_reactions(value, name="Reactions"):
        embed = discord.Embed(title="a featured message")
        embed.add_field(name="Message", value="a memorable message", inline=False)
        embed.add_field(name=name, value=value, inline=True)
        return embed

    async def update(self, db_message=None, corrected_reactions=20):
        await utils.update_reaction_counter(
            db_message if db_message is not None else {"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID},
            self.bot, TARGET_CHANNEL_ID, 5, FakeConnection(),
            FakeSourceMessage(), corrected_reactions)

    def edited_embed(self):
        return self.posted.edits[-1]["embed"]

    async def test_writes_the_new_count_into_the_embed(self):
        await self.update(corrected_reactions=20)

        reactions = [field for field in self.edited_embed().fields if field.name == "Reactions"][0]
        self.assertIn("20", reactions.value)

    async def test_leaves_the_other_fields_alone(self):
        await self.update()

        names = [field.name for field in self.edited_embed().fields]
        self.assertEqual(["Message", "Reactions"], names)

    async def test_finds_the_field_when_its_name_carries_the_emoji(self):
        """Older posts were written with the top emoji in the field name."""
        self.posted.embeds = [self.embed_with_reactions("5 🔥", name="🔥 Reactions")]
        await self.update(corrected_reactions=20)

        reactions = [field for field in self.edited_embed().fields if field.name == "Reactions"][0]
        self.assertIn("20", reactions.value)

    async def test_counts_the_reactions_itself_when_it_is_not_told(self):
        self.reaction_total = 31
        await self.update(corrected_reactions=None)

        reactions = [field for field in self.edited_embed().fields if field.name == "Reactions"][0]
        self.assertIn("31", reactions.value)

    async def test_rebuilds_a_post_whose_embed_was_removed(self):
        """A hidden post keeps its message but loses its embed, and climbing back restores it."""
        self.posted.embeds = []
        await self.update()

        self.assertEqual(self.embed, self.posted.edits[-1]["embed"])

    async def test_does_nothing_for_a_row_with_no_posted_message(self):
        await self.update(db_message={"hall_of_fame_message_id": None})

        self.assertEqual([], self.posted.edits)

    async def test_does_nothing_when_the_hall_of_fame_channel_is_gone(self):
        self.bot = FakeBot({})
        await self.update()

        self.assertEqual([], self.posted.edits)


class RemoveEmbedTests(PostingTestCase):
    def setUp(self):
        super().setUp()
        self.posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[self.embed])
        self.target_channel = FakeTargetChannel(messages={HALL_OF_FAME_MESSAGE_ID: self.posted})
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.target_channel})

    async def test_drops_the_embed_but_keeps_the_message(self):
        """The message stays so that the post can be restored in place if it climbs back."""
        await utils.remove_embed({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID},
                                 self.bot, TARGET_CHANNEL_ID)

        self.assertEqual([{"content": "** **", "embed": None}], self.posted.edits)

    async def test_does_nothing_for_a_row_that_was_never_posted(self):
        await utils.remove_embed({}, self.bot, TARGET_CHANNEL_ID)

        self.assertEqual([], self.posted.edits)

    async def test_does_nothing_when_the_hall_of_fame_channel_is_gone(self):
        await utils.remove_embed({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID},
                                 FakeBot({}), TARGET_CHANNEL_ID)

        self.assertEqual([], self.posted.edits)


class UpdateLeaderboardTests(PostingTestCase):
    def setUp(self):
        super().setUp()
        self.leaderboard_ids = [8001, 8002]
        self.leaderboard_messages = {message_id: FakePostedMessage(message_id)
                                     for message_id in self.leaderboard_ids}
        self.hall_of_fame_channel = FakeTargetChannel(messages=self.leaderboard_messages)
        self.source_messages = {MESSAGE_ID: FakeSourceMessage(message_id=MESSAGE_ID),
                                MESSAGE_ID + 1: FakeSourceMessage(message_id=MESSAGE_ID + 1)}
        self.source_channel = FakeTargetChannel(messages=self.source_messages)
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.hall_of_fame_channel,
                            SOURCE_CHANNEL_ID: self.source_channel})
        self.top_messages = [
            {"channel_id": SOURCE_CHANNEL_ID, "message_id": MESSAGE_ID},
            {"channel_id": SOURCE_CHANNEL_ID, "message_id": MESSAGE_ID + 1},
        ]

    def patch_leaderboard_repo(self):
        self.updated_fields = []
        repo = mock.Mock()
        repo.find_top_messages_by_reaction_count = lambda *_args, **_kwargs: self.top_messages
        repo.update_field_for_message = lambda *args: self.updated_fields.append(args)
        self.patch(utils, "hall_of_fame_message_repo", repo)

    def config(self, **overrides):
        values = dict(guild_id=GUILD_ID, hall_of_fame_channel_id=TARGET_CHANNEL_ID,
                      leaderboard_message_ids=self.leaderboard_ids)
        values.update(overrides)
        return build_server(**values)

    async def test_does_nothing_for_a_server_without_a_leaderboard(self):
        self.patch_leaderboard_repo()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config(leaderboard_message_ids=[]))

        self.assertEqual([], self.updated_fields)

    async def test_does_nothing_when_the_hall_of_fame_channel_is_gone(self):
        self.patch_leaderboard_repo()
        await utils.update_leaderboard(FakeConnection(), FakeBot({}), self.config())

        self.assertEqual([], self.updated_fields)

    async def test_refreshes_the_stored_count_of_every_top_message(self):
        self.patch_leaderboard_repo()
        self.reaction_total = 44
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual(2, len(self.updated_fields))
        self.assertEqual("reaction_count", self.updated_fields[0][4])
        self.assertEqual(44, self.updated_fields[0][5])

    async def test_edits_each_leaderboard_message_once(self):
        """Editing the same message three times tripled the daily rate limit cost."""
        self.patch_leaderboard_repo()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        for message in self.leaderboard_messages.values():
            with self.subTest(message=message.id):
                self.assertEqual(1, len(message.edits))

    async def test_ranks_the_messages_in_the_content(self):
        self.patch_leaderboard_repo()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertIn("HallOfFame#1", self.leaderboard_messages[8001].edits[0]["content"])
        self.assertIn("HallOfFame#2", self.leaderboard_messages[8002].edits[0]["content"])

    async def test_carries_the_attachment_into_the_leaderboard_message(self):
        self.patch_leaderboard_repo()
        self.source_messages[MESSAGE_ID].attachments = [FakeAttachment("https://cdn.example/clip.mp4")]
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertIn("https://cdn.example/clip.mp4", self.leaderboard_messages[8001].edits[0]["content"])

    async def test_stops_at_the_leaderboard_messages_it_has(self):
        self.patch_leaderboard_repo()
        self.top_messages = self.top_messages * 15
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        edits = sum(len(message.edits) for message in self.leaderboard_messages.values())
        self.assertEqual(len(self.leaderboard_ids), edits)

    async def test_skips_a_message_whose_channel_the_bot_can_no_longer_see(self):
        self.patch_leaderboard_repo()
        self.top_messages = [{"channel_id": 12345, "message_id": MESSAGE_ID}]
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([], self.updated_fields)

    async def test_one_deleted_channel_does_not_cost_the_rest_of_the_leaderboard(self):
        """A featured message can outlive its channel, and the other places are still valid."""
        self.patch_leaderboard_repo()
        self.top_messages = [{"channel_id": 12345, "message_id": MESSAGE_ID},
                             {"channel_id": SOURCE_CHANNEL_ID, "message_id": MESSAGE_ID + 1}]
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([], self.leaderboard_messages[8001].edits)
        self.assertIn("HallOfFame#2", self.leaderboard_messages[8002].edits[0]["content"])


if __name__ == "__main__":
    unittest.main()
