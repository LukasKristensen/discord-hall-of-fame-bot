"""Tests for the helpers that put a message on the board and keep it up to date.

``validate_message`` decides what should happen; these are the three things it can decide on. They
are where the bot writes to Discord and to the database in the same breath, so the cases that matter
are the ones where the two can disagree: a database write that fails after the message is already
posted, a post whose embed was removed while it was hidden, and a video that has to survive as a
separate message.
"""

import datetime
import types
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


def http_error(error_type, status, code, text):
    return error_type(types.SimpleNamespace(status=status, reason=text), {"code": code, "message": text})


def unknown_message():
    return http_error(discord.NotFound, 404, 10008, "Unknown Message")


def missing_access():
    return http_error(discord.Forbidden, 403, 50001, "Missing Access")


def old_message_edit_limit():
    return http_error(discord.HTTPException, 429, utils.OLD_MESSAGE_EDIT_LIMIT_CODE,
                      "Maximum number of edits to messages older than 1 hour reached.")


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
        self.mention = f"<#{channel_id}>"


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
    def __init__(self, message_id, embeds=(), content="", view=None, allowed_mentions=None):
        self.id = message_id
        self.embeds = list(embeds)
        self.content = content
        self.view = view
        self.allowed_mentions = allowed_mentions
        # A message sent with a Components V2 view carries the flag, and its components
        self.flags = types.SimpleNamespace(components_v2=view is not None)
        self.components = list(getattr(view, "children", []))
        self.edits = []
        self.deleted = False
        # Old enough by default for its edits to count toward Discord's limit on edits to old messages
        self.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        # Raised by the next edit instead of making it, as Discord refusing it
        self.edit_error = None

    async def edit(self, **kwargs):
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append(kwargs)

    async def delete(self):
        self.deleted = True


class FakeTargetChannel:
    def __init__(self, messages=None, next_id=7000):
        self.id = TARGET_CHANNEL_ID
        self.messages = messages if messages is not None else {}
        self.sent = []
        self.next_id = next_id

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        message = FakePostedMessage(self.next_id, embeds=[embed] if embed else [], content=content or "", view=view,
                                    allowed_mentions=allowed_mentions)
        self.next_id += 1
        self.sent.append(message)
        return message

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise AssertionError(f"fetched an unexpected message id: {message_id!r}")
        # An error in place of a message is what Discord answers for it, such as a deleted message
        if isinstance(self.messages[message_id], Exception):
            raise self.messages[message_id]
        return self.messages[message_id]


class FakeBot:
    def __init__(self, channels):
        self.channels = channels

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


def post_view(text, reactions_line=None):
    """A Components V2 post as create_post_view lays it out: a container, with the reactions line by its ID"""
    container = discord.ui.Container(discord.ui.TextDisplay(text))
    if reactions_line is not None:
        container.add_item(discord.ui.TextDisplay(reactions_line, id=utils.POST_REACTIONS_ID))
    view = discord.ui.LayoutView()
    view.add_item(container)
    return view


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

        self.view = post_view("a post")

        async def build_view(*_args, **_kwargs):
            return self.view

        self.patch(utils, "logging", record_log)
        self.patch(utils, "reaction_count", count_reactions)
        self.patch(utils, "create_embed", build_embed)
        self.patch(utils, "create_post_view", build_view)
        self.patch(utils, "missing_channels_logged", set())
        self.patch(utils, "old_message_edits_paused_until", {})

        self.original_cache = utils.recently_logged_messages
        utils.recently_logged_messages = ExpiringSet(ttl_seconds=600)
        self.addCleanup(self.restore_cache)

    def restore_cache(self):
        utils.recently_logged_messages = self.original_cache

    def patch(self, target, name, replacement):
        patcher = mock.patch.object(target, name, replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def patch_repo(self, insert=None, credited_posts=0):
        self.inserted = []

        def record_insert(*args, author_post_limit=None):
            """Stores like the real INSERT: nobody credited once the author is at the limit"""
            if insert:
                insert()
            author = args[6]
            if author_post_limit is not None and credited_posts >= author_post_limit:
                author = 0
            self.inserted.append(args[:6] + (author,) + args[7:])
            return author

        repo = mock.Mock()
        repo.insert_hall_of_fame_message = record_insert
        repo.NO_AUTHOR_ID = 0
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

    async def test_posts_one_components_v2_message_to_the_hall_of_fame_channel(self):
        self.patch_repo()
        await self.post()

        self.assertEqual(1, len(self.target_channel.sent))
        self.assertIs(self.view, self.target_channel.sent[0].view)
        self.assertEqual([], self.target_channel.sent[0].embeds)

    async def test_posts_without_pinging_anyone_the_message_mentions(self):
        """Unlike an embed, text in components pings, so the message's mentions would go off again."""
        self.patch_repo()
        await self.post()

        mentions = self.target_channel.sent[0].allowed_mentions
        self.assertFalse(mentions.everyone or mentions.users or mentions.roles or mentions.replied_user)

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

    async def test_a_video_plays_inside_the_post_with_no_message_of_its_own(self):
        self.patch_repo()
        await self.post(FakeSourceMessage(attachments=[FakeAttachment("https://cdn.example/clip.mp4")]))

        self.assertEqual(1, len(self.target_channel.sent))
        self.assertIsNone(self.inserted[0][8])

    async def test_checks_the_sent_post_for_flagged_media(self):
        """Such as the image of the message it replies to, which the message itself does not carry."""
        self.patch_repo()
        checked = []

        async def take_down(post, *_args, **_kwargs):
            checked.append(post)
            return False

        self.patch(utils, "take_down_flagged_post", take_down)
        await self.post()

        self.assertEqual(self.target_channel.sent, checked)
        self.assertEqual(1, len(self.inserted), "a post taken down is still recorded, so it can be restored")

    async def test_reads_the_scan_results_a_new_post_carries_in_its_raw_components(self):
        """discord.py does not keep them, and a replied-to image may already be flagged when the post is sent."""
        self.patch_repo()
        requested = []

        async def get_message(channel_id, message_id):
            requested.append((channel_id, message_id))
            return {"components": [{"type": 17, "components": [{"type": 12, "items": [
                {"media": {"url": "https://cdn.example/a.png", "content_scan_metadata": {"flags": 1 << 1}}}]}]}]}

        self.bot.http = types.SimpleNamespace(get_message=get_message)
        await self.post()

        posted = self.target_channel.sent[0]
        self.assertEqual([(TARGET_CHANNEL_ID, posted.id)], requested)
        self.assertEqual(1, len(posted.edits), "the flagged post is blanked")
        self.assertNotIn("embed", posted.edits[0])

    async def test_a_post_whose_raw_components_cannot_be_read_stays_up(self):
        self.patch_repo()

        async def get_message(_channel_id, _message_id):
            raise http_error(discord.HTTPException, 500, 0, "Server Error")

        self.bot.http = types.SimpleNamespace(get_message=get_message)
        await self.post()

        self.assertEqual([], self.target_channel.sent[0].edits)

    async def test_leaves_a_post_without_flags_alone(self):
        self.patch_repo()
        await self.post()

        self.assertEqual([], self.target_channel.sent[0].edits)

    async def test_takes_the_post_back_down_when_it_cannot_be_recorded(self):
        """A post the database does not know about can never be updated or hidden again."""
        self.patch_repo(insert=lambda: (_ for _ in ()).throw(RuntimeError("write failed")))
        await self.post()

        self.assertTrue(self.target_channel.sent[0].deleted)

    async def test_a_member_at_the_post_limit_still_gets_on_the_board_but_is_not_credited(self):
        self.patch(utils, "members_at_post_limit_logged", set())
        self.patch_repo(credited_posts=utils.member_post_limit)
        await self.post()

        self.assertEqual(1, len(self.target_channel.sent))
        self.assertEqual(0, self.inserted[0][6])

    async def test_a_member_just_under_the_post_limit_is_credited(self):
        self.patch_repo(credited_posts=utils.member_post_limit - 1)
        await self.post()

        self.assertEqual(AUTHOR_ID, self.inserted[0][6])

    async def test_reaching_the_post_limit_is_logged_once(self):
        self.patch(utils, "members_at_post_limit_logged", set())
        self.patch_repo(credited_posts=utils.member_post_limit)
        await self.post()
        await self.post()

        alerts = [entry for entry in self.logged if "the most allowed" in entry]
        self.assertEqual(1, len(alerts))
        self.assertIn(str(AUTHOR_ID), alerts[0])

    async def test_a_member_who_opts_out_while_the_repost_is_sent_gets_it_taken_down(self):
        """They asked not to be reposted, so the repost sent a moment before goes and nothing is stored."""
        self.patch_repo()
        answers = iter([False, True])
        self.patch(utils.opt_out_repo, "is_opted_out", lambda *_args: next(answers))
        await self.post(FakeSourceMessage(attachments=[FakeAttachment("https://cdn.example/clip.mp4")]))

        self.assertTrue(all(message.deleted for message in self.target_channel.sent))
        self.assertEqual([], self.inserted)

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


class YoungMessageTests(PostingTestCase):
    """A message posted moments after it was sent had a file fail to load on the board for good, since Discord
    fetched it before it was ready and kept the failure. Such a message is held until it is old enough"""

    def setUp(self):
        super().setUp()
        self.target_channel = FakeTargetChannel()
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.target_channel})
        self.slept = []

        async def record_sleep(seconds):
            self.slept.append(seconds)

        self.patch(utils.asyncio, "sleep", record_sleep)
        self.built_from = []

        async def build_view(message, *_args, **_kwargs):
            self.built_from.append(message)
            return self.view

        self.patch(utils, "create_post_view", build_view)
        self.patch_repo()

    def message(self, age_seconds, attachments=(FakeAttachment(),), fetched=None):
        message = FakeSourceMessage(attachments=attachments)
        message.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age_seconds)
        message.embeds, message.stickers = [], []
        message.content = "no link here"
        message.channel = FakeTargetChannel(messages={MESSAGE_ID: fetched if fetched is not None else message})
        return message

    async def post(self, message):
        await utils.post_hall_of_fame_message(message, self.bot, FakeConnection(), TARGET_CHANNEL_ID, 5)

    async def test_a_message_with_files_sent_moments_ago_waits_until_it_is_old_enough(self):
        await self.post(self.message(age_seconds=2))

        self.assertEqual(1, len(self.slept))
        self.assertAlmostEqual(utils.post_minimum_message_age_seconds - 2, self.slept[0], delta=1)
        self.assertEqual(1, len(self.target_channel.sent))

    async def test_the_post_is_built_from_the_message_as_it_is_after_the_wait(self):
        """Fetched again, so link previews that arrived while waiting are shown"""
        fetched = FakeSourceMessage(attachments=[FakeAttachment()])
        await self.post(self.message(age_seconds=1, fetched=fetched))

        self.assertIs(fetched, self.built_from[0])

    async def test_a_message_old_enough_posts_at_once(self):
        await self.post(self.message(age_seconds=utils.post_minimum_message_age_seconds + 5))

        self.assertEqual([], self.slept)
        self.assertEqual(1, len(self.target_channel.sent))

    async def test_a_young_message_with_only_text_posts_at_once(self):
        await self.post(self.message(age_seconds=1, attachments=()))

        self.assertEqual([], self.slept)
        self.assertEqual(1, len(self.target_channel.sent))

    async def test_a_young_message_with_a_link_waits_for_its_preview(self):
        message = self.message(age_seconds=1, attachments=())
        message.content = "look https://example.com/clip.gif"
        await self.post(message)

        self.assertEqual(1, len(self.slept))

    async def test_a_message_deleted_while_waiting_is_not_posted(self):
        await self.post(self.message(age_seconds=1, fetched=unknown_message()))

        self.assertEqual([], self.target_channel.sent)
        self.assertEqual([], self.inserted)


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

    async def test_leaves_a_post_whose_count_has_not_changed(self):
        """Discord limits edits to old messages, and busy boards spent it on edits that changed nothing."""
        self.posted.embeds = [self.embed_with_reactions(utils.format_reactions_field_value(20, None))]
        await self.update(corrected_reactions=20)

        self.assertEqual([], self.posted.edits)

    async def test_rewrites_an_old_field_name_even_when_the_count_is_the_same(self):
        value = utils.format_reactions_field_value(20, None)
        self.posted.embeds = [self.embed_with_reactions(value, name="🔥 Reactions")]
        await self.update(corrected_reactions=20)

        self.assertEqual(1, len(self.posted.edits))

    async def test_the_old_message_edit_limit_is_not_raised(self):
        """Each refusal was logged as an error in the reaction event."""
        self.posted.edit_error = old_message_edit_limit()

        await self.update()

    async def test_pauses_edits_in_the_server_after_reaching_the_old_message_edit_limit(self):
        self.posted.edit_error = old_message_edit_limit()
        await self.update(corrected_reactions=20)
        self.posted.edit_error = None
        await self.update(corrected_reactions=21)

        self.assertEqual([], self.posted.edits)

    async def test_keeps_editing_new_posts_during_the_pause(self):
        """The limit only counts edits to messages older than an hour, so a fresh post keeps climbing."""
        utils.old_message_edits_paused_until[GUILD_ID] = (datetime.datetime.now(datetime.timezone.utc)
                                                          + datetime.timedelta(minutes=10))
        self.posted.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)
        await self.update(corrected_reactions=20)

        self.assertEqual(1, len(self.posted.edits))

    async def test_edits_again_once_the_pause_is_over(self):
        utils.old_message_edits_paused_until[GUILD_ID] = (datetime.datetime.now(datetime.timezone.utc)
                                                          - datetime.timedelta(seconds=1))
        await self.update(corrected_reactions=20)

        self.assertEqual(1, len(self.posted.edits))

    async def test_other_edit_failures_are_still_raised(self):
        self.posted.edit_error = missing_access()

        with self.assertRaises(discord.Forbidden):
            await self.update()
        self.assertEqual({}, utils.old_message_edits_paused_until)


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

    def pause_old_message_edits(self):
        utils.old_message_edits_paused_until[GUILD_ID] = (datetime.datetime.now(datetime.timezone.utc)
                                                          + datetime.timedelta(minutes=10))

    async def test_waits_out_the_pause_on_edits_to_old_posts(self):
        """The edit would be refused too, and logged as an error."""
        self.pause_old_message_edits()
        await utils.remove_embed({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID},
                                 self.bot, TARGET_CHANNEL_ID, guild_id=GUILD_ID)

        self.assertEqual([], self.posted.edits)

    async def test_a_post_hidden_for_safety_is_tried_during_the_pause(self):
        self.pause_old_message_edits()
        await utils.remove_embed({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID},
                                 self.bot, TARGET_CHANNEL_ID, guild_id=GUILD_ID, always=True)

        self.assertEqual(1, len(self.posted.edits))

    async def test_reaching_the_limit_while_hiding_is_not_raised_and_pauses(self):
        self.posted.edit_error = old_message_edit_limit()
        await utils.remove_embed({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID},
                                 self.bot, TARGET_CHANNEL_ID, guild_id=GUILD_ID)

        self.assertIn(GUILD_ID, utils.old_message_edits_paused_until)


REACTION_CONFIG = {"custom_emoji_check_logic": False, "whitelisted_emojis": []}


class ComponentsV2PostTests(PostingTestCase):
    """Posts sent as Components V2 messages: updated, hidden and restored with views, never embeds."""

    def setUp(self):
        super().setUp()
        self.source = FakeSourceMessage()
        self.posted = FakePostedMessage(HALL_OF_FAME_MESSAGE_ID,
                                        view=post_view("a post", utils.reactions_line(self.source, REACTION_CONFIG, 5)))
        self.target_channel = FakeTargetChannel(messages={HALL_OF_FAME_MESSAGE_ID: self.posted})
        self.bot = FakeBot({TARGET_CHANNEL_ID: self.target_channel})

    async def update(self, counted):
        await utils.update_reaction_counter({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID}, self.bot,
                                            TARGET_CHANNEL_ID, 5, FakeConnection(), self.source, counted,
                                            REACTION_CONFIG)

    async def test_a_reaction_that_changes_nothing_costs_no_edit(self):
        """Nor a fetch of the message replied to, which rebuilding the post would take."""
        built = []

        async def build_view(*_args, **_kwargs):
            built.append(True)
            return self.view

        self.patch(utils, "create_post_view", build_view)
        await self.update(5)

        self.assertEqual([], self.posted.edits)
        self.assertEqual([], built)

    async def test_a_new_count_rebuilds_the_post_without_mentions(self):
        await self.update(20)

        [edit] = self.posted.edits
        self.assertIs(self.view, edit["view"])
        self.assertNotIn("embed", edit)
        self.assertFalse(edit["allowed_mentions"].everyone or edit["allowed_mentions"].users)

    async def test_hiding_keeps_the_message_and_shows_nothing(self):
        await utils.remove_embed({"hall_of_fame_message_id": HALL_OF_FAME_MESSAGE_ID}, self.bot, TARGET_CHANNEL_ID)

        [edit] = self.posted.edits
        self.assertNotIn("embed", edit)
        self.assertFalse(utils.post_shows(types.SimpleNamespace(embeds=[], components=edit["view"].children)))

    async def test_a_hidden_post_is_restored_as_a_view(self):
        self.posted.components = utils.hidden_post_view().children
        await self.update(20)

        self.assertIs(self.view, self.posted.edits[-1]["view"])

    async def test_a_restored_post_whose_reply_media_is_flagged_goes_back_down(self):
        """Media only the post carries, such as a replied-to image, is flagged on the post, not the source."""
        self.posted.components = utils.hidden_post_view().children

        async def get_message(_channel_id, _message_id):
            return {"components": [{"type": 17, "components": [{"type": 12, "items": [
                {"media": {"url": "https://cdn.example/a.png", "content_scan_metadata": {"flags": 1 << 1}}}]}]}]}

        self.bot.http = types.SimpleNamespace(get_message=get_message)
        await self.update(20)

        self.assertIs(self.view, self.posted.edits[0]["view"])
        self.assertFalse(utils.post_shows(types.SimpleNamespace(embeds=[], components=self.posted.edits[-1]["view"].children)))

    async def test_a_restored_post_without_flags_stays_up(self):
        self.posted.components = utils.hidden_post_view().children

        async def get_message(_channel_id, _message_id):
            return {"components": []}

        self.bot.http = types.SimpleNamespace(get_message=get_message)
        await self.update(20)

        self.assertEqual(1, len(self.posted.edits))

    async def test_an_old_post_that_discord_refuses_to_edit_pauses_the_server(self):
        self.posted.edit_error = old_message_edit_limit()
        await self.update(20)

        self.assertIn(GUILD_ID, utils.old_message_edits_paused_until)

    async def test_media_discord_flags_after_sending_takes_the_post_down(self):
        """A Components V2 post carries the scanning results only in its raw components."""
        raw = [{"type": 17, "components": [{"type": 12, "items": [
            {"media": {"url": "https://cdn.example/a.png", "content_scan_metadata": {"flags": 1 << 1}}}]}]}]
        taken_down = await utils.take_down_flagged_post(self.posted, self.target_channel, self.bot, GUILD_ID, raw)

        self.assertTrue(taken_down)
        self.assertNotIn("embed", self.posted.edits[-1])


class ComponentScanFlagTests(unittest.TestCase):
    def media(self, flags):
        return [{"type": 9, "accessory": {"type": 11, "media": {"url": "u", "content_scan_metadata": {"flags": flags}}}}]

    def test_turns_the_component_bits_into_the_attachment_ones(self):
        self.assertEqual(utils.EXPLICIT_CONTENT, utils.component_scan_flags(self.media(1 << 0)))
        self.assertEqual(utils.GORE_CONTENT, utils.component_scan_flags(self.media(1 << 1)))
        self.assertEqual(utils.SELF_HARM_CONTENT, utils.component_scan_flags(self.media(1 << 2)))

    def test_media_without_results_has_none(self):
        self.assertEqual(0, utils.component_scan_flags([{"type": 12, "items": [{"media": {"url": "u"}}]}]))
        self.assertEqual(0, utils.component_scan_flags(None))


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

    async def test_one_deleted_message_does_not_cost_the_rest_of_the_leaderboard(self):
        """One deleted featured message stopped the whole update, so the same servers failed every day."""
        self.patch_leaderboard_repo()
        self.source_messages[MESSAGE_ID] = unknown_message()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([], self.leaderboard_messages[8001].edits)
        self.assertIn("HallOfFame#2", self.leaderboard_messages[8002].edits[0]["content"])

    async def test_a_message_in_a_channel_the_bot_cannot_read_is_skipped(self):
        self.patch_leaderboard_repo()
        self.source_messages[MESSAGE_ID] = missing_access()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertIn("HallOfFame#2", self.leaderboard_messages[8002].edits[0]["content"])

    async def test_a_deleted_place_does_not_cost_the_other_places(self):
        self.patch_leaderboard_repo()
        self.leaderboard_messages[8001] = unknown_message()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertIn("HallOfFame#2", self.leaderboard_messages[8002].edits[0]["content"])

    async def test_stops_quietly_when_the_bot_cannot_read_its_board(self):
        """The daily permission check already tells the server, so failing every place adds nothing."""
        self.patch_leaderboard_repo()
        self.leaderboard_messages[8001] = missing_access()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([], self.leaderboard_messages[8002].edits)

    async def test_stops_quietly_at_the_old_message_edit_limit(self):
        self.patch_leaderboard_repo()
        self.leaderboard_messages[8001].edit_error = old_message_edit_limit()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([], self.leaderboard_messages[8002].edits)

    async def test_the_old_message_edit_limit_pauses_the_boards_other_edits_too(self):
        """Reactions after the leaderboard reached the limit would otherwise keep spending it."""
        self.patch_leaderboard_repo()
        self.leaderboard_messages[8001].edit_error = old_message_edit_limit()
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertIn(GUILD_ID, utils.old_message_edits_paused_until)

    async def test_other_edit_failures_are_still_raised(self):
        self.patch_leaderboard_repo()
        self.leaderboard_messages[8001].edit_error = http_error(discord.HTTPException, 503, 0, "Service Unavailable")

        with self.assertRaises(discord.HTTPException):
            await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

    async def test_only_asks_for_as_many_messages_as_there_are_places(self):
        self.patch_leaderboard_repo()
        limits = []

        def find_top_messages(*_args, limit):
            limits.append(limit)
            return self.top_messages

        utils.hall_of_fame_message_repo.find_top_messages_by_reaction_count = find_top_messages
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([len(self.leaderboard_ids)], limits)

    async def test_counts_each_shown_message_once(self):
        """Counting can cost a request per member who reacted, and counting twice timed large servers out."""
        self.patch_leaderboard_repo()
        counted = []
        embed_counts = []

        async def count_reactions(message, *_args, **_kwargs):
            counted.append(message.id)
            return 44

        async def build_embed(*args):
            embed_counts.append(args[4])
            return self.embed

        self.patch(utils, "reaction_count", count_reactions)
        self.patch(utils, "create_embed", build_embed)
        await utils.update_leaderboard(FakeConnection(), self.bot, self.config())

        self.assertEqual([MESSAGE_ID, MESSAGE_ID + 1], counted)
        self.assertEqual([44, 44], embed_counts)


if __name__ == "__main__":
    unittest.main()
