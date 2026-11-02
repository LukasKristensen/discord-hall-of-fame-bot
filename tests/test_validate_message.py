"""Tests for the gate that decides whether a reacted message reaches the Hall of Fame.

``validate_message`` is the highest consequence function in the bot. Every reaction event runs
through it, and it decides between four outcomes: do nothing, hide a post that has fallen back under
the threshold, update a post that is already on the board, or post a new one.

Those three actions are stubbed out here, so each test can say plainly which outcome the
configuration in front of it should produce, without building a working Discord client to observe.
Reaction counting itself is stubbed for the same reason: what is being tested is the decision, and
the counting is already covered by ``test_message_reactions``.
"""

import asyncio
import datetime
import types
import unittest
from datetime import timezone

import discord
from unittest import mock

import utils
from enums import calculation_method_type, log_type

from tests.fakes import FakePermissions
from tests.test_server_class import build_server

GUILD_ID = 200
SOURCE_CHANNEL_ID = 100
TARGET_CHANNEL_ID = 999
MESSAGE_ID = 4242
HALL_OF_FAME_MESSAGE_ID = 5555
VIDEO_LINK_MESSAGE_ID = 6666
BOT_USER_ID = 1
AUTHOR_ID = 77


def server_config(**overrides):
    """The shared server builder, pointed at this module's channels and thresholds."""
    values = dict(
        hall_of_fame_channel_id=TARGET_CHANNEL_ID,
        guild_id=GUILD_ID,
        reaction_threshold=3,
        post_due_date=7,
        ignore_bot_messages=True,
        hide_hof_post_below_threshold=True,
        require_image_or_video=False,
    )
    values.update(overrides)
    return build_server(**values)


def database_row(hall_of_fame_message_id=HALL_OF_FAME_MESSAGE_ID, video_link_message_id=None):
    """A row as ``find_hall_of_fame_message`` returns it: every column, present even when null."""
    return {
        "message_id": MESSAGE_ID,
        "channel_id": SOURCE_CHANNEL_ID,
        "guild_id": GUILD_ID,
        "hall_of_fame_message_id": hall_of_fame_message_id,
        "reaction_count": 3,
        "author_id": AUTHOR_ID,
        "created_at": datetime.datetime.now(timezone.utc),
        "video_link_message_id": video_link_message_id,
    }


class Recorder:
    """Stands in for one of the actions the gate can take, and remembers being taken."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result

    @property
    def called(self) -> bool:
        return len(self.calls) > 0


class FakeAuthor:
    def __init__(self, author_id=AUTHOR_ID, bot=False):
        self.id = author_id
        self.bot = bot
        self.name = "Author"


class FakeGuild:
    def __init__(self):
        self.id = GUILD_ID
        self.name = "Test Server"
        self.me = object()


class FakeAttachment:
    def __init__(self, url="https://cdn.example/file.png", content_type="image/png", flags=0):
        self.url = url
        self.content_type = content_type
        self.flags = types.SimpleNamespace(value=flags)


class FakeEmbed:
    def __init__(self, embed_type="rich", image=None, video=None, flags=None):
        self.type = embed_type
        self.image = image
        self.video = video
        # None when Discord sent no flags, as on a real embed
        self.flags = types.SimpleNamespace(value=flags) if flags is not None else None


class FakeSourceMessage:
    def __init__(self, guild, age_days=0, author_bot=False, attachments=(), embeds=(), channel_nsfw=False):
        self.id = MESSAGE_ID
        self.guild = guild
        self.author = FakeAuthor(bot=author_bot)
        self.created_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=age_days)
        self.attachments = list(attachments)
        self.embeds = list(embeds)
        self.reactions = []
        self.channel = FakeSourceChannelStub(nsfw=channel_nsfw)


class FakeSourceChannelStub:
    """Only the channel's id and whether it is age-restricted are read, so this stays deliberately small."""

    def __init__(self, nsfw=False):
        self.id = SOURCE_CHANNEL_ID
        self.nsfw = nsfw

    def is_nsfw(self):
        return self.nsfw


class FakeSourceChannel:
    def __init__(self, guild, message, read_messages=True):
        self.id = SOURCE_CHANNEL_ID
        self.guild = guild
        self.message = message
        self.permissions = FakePermissions(read_messages=read_messages)

    def permissions_for(self, _member):
        return self.permissions

    async def fetch_message(self, _message_id):
        return self.message


class FakePostedMessage:
    """A message already sitting in the Hall of Fame channel."""

    def __init__(self, message_id, embeds=(), author_id=BOT_USER_ID, content=""):
        self.id = message_id
        self.embeds = list(embeds)
        self.author = FakeAuthor(author_id=author_id)
        self.content = content
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class FakeTargetChannel:
    def __init__(self, messages=None, nsfw=False):
        self.id = TARGET_CHANNEL_ID
        self.messages = messages if messages is not None else {}
        self.sent = []
        self.fetched = []
        self.nsfw = nsfw

    def is_nsfw(self):
        return self.nsfw

    async def fetch_message(self, message_id):
        self.fetched.append(message_id)
        if message_id not in self.messages:
            raise AssertionError(f"The gate fetched an unexpected message id: {message_id!r}")
        return self.messages[message_id]

    async def send(self, content=None, embed=None):
        await asyncio.sleep(0)  # Yields like the API call it stands in for, so concurrent reactions interleave
        message = FakePostedMessage(len(self.sent) + 1, content=content or "")
        self.sent.append(message)
        return message


class FakeBot:
    def __init__(self, channels):
        self.channels = channels
        self.user = FakeAuthor(author_id=BOT_USER_ID)

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


class FakeReactionEvent:
    def __init__(self):
        self.guild_id = GUILD_ID
        self.channel_id = SOURCE_CHANNEL_ID
        self.message_id = MESSAGE_ID


class FakeMessageRepo:
    """The two reads and one write the gate makes against the message table."""

    def __init__(self, db_message=None, messages_today=0):
        self.db_message = db_message
        self.messages_today = messages_today
        self.updated_fields = []

    def find_hall_of_fame_message(self, _connection, _guild_id, _channel_id, _message_id):
        return self.db_message

    def guild_message_count_today(self, _connection, _guild_id):
        return self.messages_today

    def update_field_for_message(self, _connection, guild_id, channel_id, message_id, field_name, field_value):
        self.updated_fields.append((guild_id, channel_id, message_id, field_name, field_value))


class GateTestCase(unittest.IsolatedAsyncioTestCase):
    """Builds the world the gate runs in, with every action it can take stubbed out."""

    def setUp(self):
        self.post = Recorder()
        self.update_counter = Recorder()
        self.remove = Recorder()
        self.embed = object()
        self.create_embed = Recorder(result=self.embed)
        self.logged = []
        self.log_options = []

        async def record_log(_bot, message, *args, **kwargs):
            self.logged.append(str(message))
            self.log_options.append(kwargs)

        self.reaction_total = 5

        async def count_reactions(_message, _connection, _config=None):
            return self.reaction_total

        for name, replacement in (
            ("post_hall_of_fame_message", self.post),
            ("update_reaction_counter", self.update_counter),
            ("remove_embed", self.remove),
            ("create_embed", self.create_embed),
            ("logging", record_log),
            ("reaction_count", count_reactions),
            ("daily_limit_handled_on", {}),
            ("missing_channels_logged", set()),
        ):
            patcher = mock.patch.object(utils, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build(self, *, age_days=0, author_bot=False, attachments=(), embeds=(),
              read_messages=True, source_channel_missing=False, target_channel_missing=False,
              db_message=None, messages_today=0, posted_messages=None, channel_nsfw=False, board_nsfw=False):
        """Assemble the bot, channels and repository the gate will see."""
        guild = FakeGuild()
        self.source_message = FakeSourceMessage(
            guild, age_days=age_days, author_bot=author_bot, attachments=attachments, embeds=embeds,
            channel_nsfw=channel_nsfw)
        self.source_channel = FakeSourceChannel(guild, self.source_message, read_messages=read_messages)
        self.target_channel = FakeTargetChannel(messages=posted_messages, nsfw=board_nsfw)

        channels = {}
        if not source_channel_missing:
            channels[SOURCE_CHANNEL_ID] = self.source_channel
        if not target_channel_missing:
            channels[TARGET_CHANNEL_ID] = self.target_channel

        self.bot = FakeBot(channels)
        self.repo = FakeMessageRepo(db_message=db_message, messages_today=messages_today)
        patcher = mock.patch.object(utils, "hall_of_fame_message_repo", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def run_gate(self, config=None):
        await utils.validate_message(FakeReactionEvent(), self.bot, connection=object(),
                                     server_config=config if config is not None else server_config())

    def assertDidNothing(self):
        self.assertFalse(self.post.called, "a message was posted")
        self.assertFalse(self.update_counter.called, "an existing post was updated")
        self.assertFalse(self.remove.called, "an existing post was hidden")
        self.assertEqual([], self.target_channel.sent, "something was sent to the Hall of Fame channel")


class ChannelVisibilityTests(GateTestCase):
    async def test_does_nothing_when_the_channel_cannot_be_seen(self):
        self.build(source_channel_missing=True)
        await self.run_gate()
        self.assertDidNothing()

    async def test_does_nothing_without_permission_to_read_the_channel(self):
        self.build(read_messages=False)
        await self.run_gate()
        self.assertDidNothing()

    async def test_reports_the_missing_read_permission(self):
        self.build(read_messages=False)
        await self.run_gate()
        self.assertTrue(any("read message permissions" in entry for entry in self.logged))

    async def test_does_nothing_when_the_hall_of_fame_channel_is_gone(self):
        self.build(target_channel_missing=True)
        await self.run_gate()
        self.assertFalse(self.post.called)

    async def test_reports_the_missing_hall_of_fame_channel(self):
        self.build(target_channel_missing=True)
        await self.run_gate()
        self.assertTrue(any("Could not find the Hall of Fame channel" in entry for entry in self.logged))

    async def test_reports_the_missing_hall_of_fame_channel_once(self):
        """Reactions keep arriving in a server whose board was deleted, which must not repeat the log."""
        self.build(target_channel_missing=True)
        await self.run_gate()
        await self.run_gate()

        self.assertEqual(1, sum("Could not find the Hall of Fame channel" in entry for entry in self.logged))

    async def test_stays_quiet_on_later_days_of_the_same_boot(self):
        self.build(target_channel_missing=True)
        utils.missing_channels_logged.add(GUILD_ID)
        await self.run_gate()

        self.assertFalse(any("Could not find the Hall of Fame channel" in entry for entry in self.logged))


class BoardChannelTests(GateTestCase):
    def in_the_board(self, message_author_id=None):
        class InTheBoard(FakeReactionEvent):
            def __init__(self):
                super().__init__()
                self.channel_id = TARGET_CHANNEL_ID
                self.message_author_id = message_author_id
        return InTheBoard()

    def build_board_message(self, author_id):
        """The message reacted to is in the board, which validate_message fetches through the board channel."""
        self.build()
        self.source_message.author = FakeAuthor(author_id=author_id)
        self.source_message.channel = self.source_channel
        self.bot.channels[TARGET_CHANNEL_ID] = self.source_channel
        self.source_channel.id = TARGET_CHANNEL_ID

    async def test_reactions_on_a_post_never_repost_it(self):
        """Otherwise a well-liked post would be reposted onto the board it is on."""
        self.build()

        await utils.validate_message(self.in_the_board(message_author_id=BOT_USER_ID), self.bot,
                                     connection=object(), server_config=server_config())
        self.assertDidNothing()
        self.assertEqual([], self.target_channel.fetched)

    async def test_a_post_is_not_reposted_when_the_event_does_not_say_who_wrote_it(self):
        """A reaction removal carries no author, so the post is fetched to find out."""
        self.build_board_message(BOT_USER_ID)

        await utils.validate_message(self.in_the_board(), self.bot, connection=object(),
                                     server_config=server_config())
        self.assertFalse(self.post.called)

    async def test_a_members_message_in_the_board_is_still_featured(self):
        """Servers that chat in their board, or use a busy channel as it, keep their messages featured."""
        self.build_board_message(AUTHOR_ID)

        await utils.validate_message(self.in_the_board(message_author_id=AUTHOR_ID), self.bot,
                                     connection=object(), server_config=server_config())
        self.assertTrue(self.post.called)


class PostDueDateTests(GateTestCase):
    async def test_posts_a_message_inside_the_due_date(self):
        self.build(age_days=3)
        await self.run_gate(server_config(post_due_date=7))
        self.assertTrue(self.post.called)

    async def test_ignores_a_message_older_than_the_due_date(self):
        self.build(age_days=8)
        await self.run_gate(server_config(post_due_date=7))
        self.assertDidNothing()

    async def test_keeps_updating_an_old_message_that_is_already_on_the_board(self):
        """The due date decides what may join the board, not what may be kept up to date."""
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[object()])
        self.build(age_days=30, db_message=database_row(),
                   posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        await self.run_gate(server_config(post_due_date=7))
        self.assertTrue(self.update_counter.called)

    async def test_treats_the_due_date_as_a_whole_number_of_days(self):
        self.build(age_days=7)
        await self.run_gate(server_config(post_due_date=7))
        self.assertTrue(self.post.called)


class SystemMessageTests(GateTestCase):
    """A poll closing was featured as an empty reply to the poll. Messages Discord posts itself never are"""

    async def test_a_system_message_is_never_posted(self):
        for message_type in (discord.MessageType.new_member, discord.MessageType.premium_guild_subscription,
                             discord.MessageType.pins_add, discord.MessageType.poll_result):
            with self.subTest(message_type=message_type):
                self.build()
                self.source_message.type = message_type
                await self.run_gate()
                self.assertDidNothing()

    async def test_messages_members_write_are_posted(self):
        for message_type in (discord.MessageType.default, discord.MessageType.reply,
                             discord.MessageType.chat_input_command):
            with self.subTest(message_type=message_type):
                self.post.calls.clear()
                self.build()
                self.source_message.type = message_type
                await self.run_gate()
                self.assertTrue(self.post.called)


class BotAuthorTests(GateTestCase):
    async def test_ignores_a_bot_message_when_configured_to(self):
        self.build(author_bot=True)
        await self.run_gate(server_config(ignore_bot_messages=True))
        self.assertDidNothing()

    async def test_posts_a_bot_message_when_bots_are_allowed(self):
        self.build(author_bot=True)
        await self.run_gate(server_config(ignore_bot_messages=False))
        self.assertTrue(self.post.called)

    async def test_a_human_message_is_never_affected_by_the_setting(self):
        self.build(author_bot=False)
        await self.run_gate(server_config(ignore_bot_messages=True))
        self.assertTrue(self.post.called)


class RequireImageOrVideoTests(GateTestCase):
    async def test_posts_a_text_message_when_media_is_not_required(self):
        self.build()
        await self.run_gate(server_config(require_image_or_video=False))
        self.assertTrue(self.post.called)

    async def test_ignores_a_text_message_when_media_is_required(self):
        self.build()
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertDidNothing()

    async def test_accepts_an_image_attachment(self):
        self.build(attachments=[FakeAttachment(content_type="image/png")])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertTrue(self.post.called)

    async def test_accepts_a_video_attachment(self):
        self.build(attachments=[FakeAttachment(content_type="video/mp4")])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertTrue(self.post.called)

    async def test_rejects_an_attachment_that_is_not_media(self):
        self.build(attachments=[FakeAttachment(content_type="application/pdf")])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertDidNothing()

    async def test_rejects_an_attachment_with_no_content_type(self):
        self.build(attachments=[FakeAttachment(content_type=None)])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertDidNothing()

    async def test_accepts_an_image_embedded_from_a_link(self):
        """A pasted image link arrives as an embed rather than an attachment."""
        self.build(embeds=[FakeEmbed(embed_type="image")])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertTrue(self.post.called)

    async def test_accepts_an_embed_carrying_an_image(self):
        self.build(embeds=[FakeEmbed(embed_type="rich", image=object())])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertTrue(self.post.called)

    async def test_accepts_an_embed_carrying_a_video(self):
        self.build(embeds=[FakeEmbed(embed_type="rich", video=object())])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertTrue(self.post.called)

    async def test_rejects_an_embed_without_media(self):
        self.build(embeds=[FakeEmbed(embed_type="rich")])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertDidNothing()

    async def test_finds_media_in_a_later_attachment(self):
        self.build(attachments=[FakeAttachment(content_type="application/pdf"),
                                FakeAttachment(content_type="image/png")])
        await self.run_gate(server_config(require_image_or_video=True))
        self.assertTrue(self.post.called)


class DailyPostLimitTests(GateTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(utils, "daily_post_limit", 100)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_posts_below_the_limit(self):
        self.build(messages_today=99)
        await self.run_gate()
        self.assertTrue(self.post.called)

    async def test_stops_posting_once_the_limit_is_reached(self):
        """The limit is the number of posts allowed, so the hundredth is the last one."""
        self.build(messages_today=100)
        await self.run_gate()
        self.assertFalse(self.post.called)

    async def test_announces_the_limit_in_the_hall_of_fame_channel(self):
        self.build(messages_today=100)
        await self.run_gate()
        self.assertEqual(1, len(self.target_channel.sent))
        self.assertIn("has hit the daily limit of", self.target_channel.sent[0].content)

    async def test_reports_reaching_the_limit(self):
        self.build(messages_today=100)
        await self.run_gate()
        self.assertTrue(any("exceeded the daily limit" in entry for entry in self.logged))

    async def test_reports_the_limit_as_critical_without_a_ping(self):
        """It recurs for every reaction while the server is at its limit, so it must not ping each time."""
        self.build(messages_today=100)
        await self.run_gate()

        options = next(kwargs for entry, kwargs in zip(self.logged, self.log_options)
                       if "exceeded the daily limit" in entry)
        self.assertEqual(log_type.CRITICAL, options["log_level"])
        self.assertFalse(options["ping_developer"])

    async def test_reports_the_limit_once_a_day(self):
        """Reactions keep arriving all day while the server is at its limit, which must not repeat the log."""
        self.build(messages_today=100)
        await self.run_gate()
        await self.run_gate()

        self.assertEqual(1, sum("exceeded the daily limit" in entry for entry in self.logged))
        self.assertEqual(1, len(self.target_channel.sent))

    async def test_reactions_arriving_together_announce_the_limit_once(self):
        """Reactions are handled concurrently, so they must not all pass the check before the notice is sent."""
        self.build(messages_today=100)
        await asyncio.gather(*(self.run_gate() for _ in range(5)))
        self.assertEqual(1, len(self.target_channel.sent))

    async def test_reports_the_limit_again_the_next_day(self):
        self.build(messages_today=100)
        utils.daily_limit_handled_on[GUILD_ID] = (datetime.datetime.now(timezone.utc).date()
                                                  - datetime.timedelta(days=1))
        await self.run_gate()
        self.assertTrue(any("exceeded the daily limit" in entry for entry in self.logged))

    async def test_remembers_the_notice_by_the_utc_day(self):
        """The limit counts from midnight UTC, so the notice must not go out again at local midnight."""
        self.build(messages_today=100)
        await self.run_gate()

        self.assertEqual(datetime.datetime.now(timezone.utc).date(), utils.daily_limit_handled_on[GUILD_ID])


class BelowThresholdTests(GateTestCase):
    async def test_does_not_post_a_message_under_the_threshold(self):
        self.build()
        self.reaction_total = 2
        await self.run_gate(server_config(reaction_threshold=3))
        self.assertDidNothing()

    async def test_posts_a_message_that_reaches_the_threshold_exactly(self):
        self.build()
        self.reaction_total = 3
        await self.run_gate(server_config(reaction_threshold=3))
        self.assertTrue(self.post.called)

    async def test_hides_a_post_that_falls_back_under_the_threshold(self):
        self.build(db_message=database_row())
        self.reaction_total = 2
        await self.run_gate(server_config(reaction_threshold=3, hide_hof_post_below_threshold=True))
        self.assertTrue(self.remove.called)

    async def test_leaves_the_post_alone_when_hiding_is_turned_off(self):
        self.build(db_message=database_row())
        self.reaction_total = 2
        await self.run_gate(server_config(reaction_threshold=3, hide_hof_post_below_threshold=False))
        self.assertFalse(self.remove.called)

    async def test_blanks_the_video_link_alongside_the_hidden_post(self):
        video_message = FakePostedMessage(VIDEO_LINK_MESSAGE_ID)
        self.build(db_message=database_row(video_link_message_id=VIDEO_LINK_MESSAGE_ID),
                   attachments=[FakeAttachment(content_type="video/mp4")],
                   posted_messages={VIDEO_LINK_MESSAGE_ID: video_message})
        self.reaction_total = 2
        await self.run_gate(server_config(reaction_threshold=3, hide_hof_post_below_threshold=True))
        self.assertEqual([{"content": "** **", "embed": None}], video_message.edits)

    async def test_hides_a_post_that_never_had_a_video_link(self):
        """The column is present and null for every post that is not a video."""
        self.build(db_message=database_row(video_link_message_id=None),
                   attachments=[FakeAttachment(content_type="image/png")])
        self.reaction_total = 2
        await self.run_gate(server_config(reaction_threshold=3, hide_hof_post_below_threshold=True))
        self.assertTrue(self.remove.called)
        self.assertEqual([], self.target_channel.fetched)


class NewPostTests(GateTestCase):
    async def test_posts_a_message_that_is_not_on_the_board(self):
        self.build(db_message=None)
        await self.run_gate()
        self.assertTrue(self.post.called)

    async def test_hands_the_posting_helper_the_message_and_the_channel(self):
        self.build(db_message=None)
        config = server_config(reaction_threshold=4)
        await self.run_gate(config)
        args, _ = self.post.calls[0]
        self.assertIs(self.source_message, args[0])
        self.assertEqual(TARGET_CHANNEL_ID, args[3])
        self.assertEqual(4, args[4])

    async def test_counts_reactions_from_memory_rather_than_the_database(self):
        """The reaction path must not pay for a configuration lookup on every event."""
        self.build(db_message=None)
        config = server_config(reaction_count_calculation_method=calculation_method_type.UNIQUE_USERS)
        await self.run_gate(config)
        _, _ = self.post.calls[0]
        passed_config = self.post.calls[0][0][5]
        self.assertEqual(calculation_method_type.UNIQUE_USERS,
                         passed_config["reaction_count_calculation_method"])


class ExistingPostTests(GateTestCase):
    async def test_updates_the_counter_on_a_post_that_still_has_its_embed(self):
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[object()])
        self.build(db_message=database_row(), posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        await self.run_gate()
        self.assertTrue(self.update_counter.called)
        self.assertFalse(self.post.called)

    async def test_writes_the_new_count_to_the_database(self):
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[object()])
        self.build(db_message=database_row(), posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        self.reaction_total = 12
        await self.run_gate()
        self.assertEqual([(GUILD_ID, SOURCE_CHANNEL_ID, MESSAGE_ID, "reaction_count", 12)],
                         self.repo.updated_fields)

    async def test_restores_the_embed_on_a_post_that_was_hidden(self):
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[])
        self.build(db_message=database_row(), posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        await self.run_gate()
        self.assertEqual([{"embed": self.embed}], posted.edits)

    async def test_a_hidden_post_keeps_its_count_while_edits_to_old_posts_are_paused(self):
        """It stays hidden until a reaction after the pause, so the count it is stored with stays too."""
        now = datetime.datetime.now(datetime.timezone.utc)
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[])
        posted.created_at = now - datetime.timedelta(hours=2)
        self.build(db_message=database_row(), posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        with mock.patch.object(utils, "old_message_edits_paused_until", {GUILD_ID: now + datetime.timedelta(minutes=10)}):
            await self.run_gate()
        self.assertEqual([], posted.edits)
        self.assertEqual([], self.repo.updated_fields)

    async def test_restores_the_video_link_alongside_the_embed(self):
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[])
        video_message = FakePostedMessage(VIDEO_LINK_MESSAGE_ID)
        attachment = FakeAttachment(url="https://cdn.example/clip.mp4", content_type="video/mp4")
        self.build(db_message=database_row(video_link_message_id=VIDEO_LINK_MESSAGE_ID),
                   attachments=[attachment],
                   posted_messages={HALL_OF_FAME_MESSAGE_ID: posted,
                                    VIDEO_LINK_MESSAGE_ID: video_message})
        await self.run_gate()
        self.assertEqual([{"content": attachment.url, "embed": None}], video_message.edits)

    async def test_restores_an_image_post_that_never_had_a_video_link(self):
        """The column is present and null here, which must not be mistaken for a message id."""
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[])
        self.build(db_message=database_row(video_link_message_id=None),
                   attachments=[FakeAttachment(content_type="image/png")],
                   posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        await self.run_gate()
        self.assertEqual([{"embed": self.embed}], posted.edits)
        self.assertEqual([HALL_OF_FAME_MESSAGE_ID], self.target_channel.fetched)

    async def test_does_not_repost_a_message_that_is_already_on_the_board(self):
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[object()])
        self.build(db_message=database_row(), posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        await self.run_gate()
        self.assertFalse(self.post.called)


class AgeRestrictedChannelTests(GateTestCase):
    """Discord keeps age-restricted content in age-restricted channels, and a board is a channel too."""

    async def test_ignores_a_message_from_an_age_restricted_channel(self):
        self.build(channel_nsfw=True)
        await self.run_gate()
        self.assertDidNothing()

    async def test_posts_it_when_the_board_is_age_restricted_too(self):
        self.build(channel_nsfw=True, board_nsfw=True)
        await self.run_gate()
        self.assertTrue(self.post.called)

    async def test_an_age_restricted_board_takes_every_other_channel_as_before(self):
        self.build(board_nsfw=True)
        await self.run_gate()
        self.assertTrue(self.post.called)

    async def test_hides_a_post_made_before_the_rule(self):
        self.build(channel_nsfw=True, db_message=database_row())
        await self.run_gate()
        self.assertTrue(self.remove.called)
        self.assertFalse(self.update_counter.called)

    async def test_hides_it_even_when_hiding_below_the_threshold_is_off(self):
        """That setting is the server's taste. This one is not up to the server."""
        self.build(channel_nsfw=True, db_message=database_row())
        await self.run_gate(server_config(hide_hof_post_below_threshold=False))
        self.assertTrue(self.remove.called)

    async def test_blanks_the_video_link_of_a_hidden_post(self):
        video_message = FakePostedMessage(VIDEO_LINK_MESSAGE_ID)
        self.build(channel_nsfw=True, db_message=database_row(video_link_message_id=VIDEO_LINK_MESSAGE_ID),
                   attachments=[FakeAttachment(content_type="video/mp4")],
                   posted_messages={VIDEO_LINK_MESSAGE_ID: video_message})
        await self.run_gate()
        self.assertEqual([{"content": "** **", "embed": None}], video_message.edits)

    async def test_restores_the_post_once_the_board_is_age_restricted(self):
        posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID, embeds=[])
        self.build(channel_nsfw=True, board_nsfw=True, db_message=database_row(),
                   posted_messages={HALL_OF_FAME_MESSAGE_ID: posted})
        await self.run_gate()
        self.assertEqual([{"embed": self.embed}], posted.edits)

    async def test_with_the_board_gone_there_is_nothing_to_hide(self):
        self.build(channel_nsfw=True, db_message=database_row(), target_channel_missing=True)
        await self.run_gate()
        self.assertFalse(self.remove.called)


class FlaggedMediaTests(GateTestCase):
    """Discord's content scanning flags media, and asks apps that repost media to act on it."""

    async def test_never_posts_gore(self):
        self.build(attachments=[FakeAttachment(flags=utils.GORE_CONTENT)])
        await self.run_gate()
        self.assertDidNothing()

    async def test_never_posts_self_harm_even_to_an_age_restricted_board(self):
        self.build(channel_nsfw=True, board_nsfw=True, attachments=[FakeAttachment(flags=utils.SELF_HARM_CONTENT)])
        await self.run_gate()
        self.assertDidNothing()

    async def test_keeps_explicit_media_off_a_board_that_is_not_age_restricted(self):
        self.build(attachments=[FakeAttachment(flags=utils.EXPLICIT_CONTENT)])
        await self.run_gate()
        self.assertDidNothing()

    async def test_posts_explicit_media_to_an_age_restricted_board(self):
        self.build(channel_nsfw=True, board_nsfw=True, attachments=[FakeAttachment(flags=utils.EXPLICIT_CONTENT)])
        await self.run_gate()
        self.assertTrue(self.post.called)

    async def test_reads_the_flags_of_a_link_preview(self):
        self.build(embeds=[FakeEmbed(embed_type="image", flags=utils.GORE_CONTENT)])
        await self.run_gate()
        self.assertDidNothing()

    async def test_finds_the_flag_on_a_later_attachment(self):
        self.build(attachments=[FakeAttachment(), FakeAttachment(flags=utils.GORE_CONTENT)])
        await self.run_gate()
        self.assertDidNothing()

    async def test_other_attachment_flags_do_not_count(self):
        """Such as a spoiler, which Discord marks with a flag of its own."""
        self.build(attachments=[FakeAttachment(flags=1 << 3)], embeds=[FakeEmbed(flags=1 << 5)])
        await self.run_gate()
        self.assertTrue(self.post.called)

    async def test_hides_a_post_whose_media_was_flagged_since(self):
        self.build(attachments=[FakeAttachment(flags=utils.GORE_CONTENT)], db_message=database_row())
        await self.run_gate()
        self.assertTrue(self.remove.called)
        self.assertFalse(self.update_counter.called)


if __name__ == "__main__":
    unittest.main()
