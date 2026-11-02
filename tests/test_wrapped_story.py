"""Tests for the Wrapped story, the plaque it shares, and the two cards the plaque opens.

The story is private and the plaque is public, so the tests care about what each one shows, that the
member alone decides when the plaque goes up, and that the cards on a plaque stay true to the stored
data: a member who stopped being featured since is not shown, and nothing is fetched or read for them.
"""

import datetime
import json
import types
import unittest
from unittest import mock

import discord

import hof_wrapped
import wrapped_story
from translations import messages

GUILD_ID = 200
USER_ID = 77
FAN_ID = 88
YEAR = 2026


def wrapped_row(**overrides):
    row = {
        "guild_id": GUILD_ID, "user_id": USER_ID, "year": YEAR, "reaction_count": 12, "hof_message_posts": 6,
        "most_used_channels": json.dumps({"100": 4, "101": 2}), "most_used_emojis": json.dumps({"💀": 9, "🔥": 3}),
        "most_reacted_post_message_id": 4242, "most_reacted_post_channel_id": 100,
        "most_reacted_post_reaction_count": 41, "fan_of_users": json.dumps({"90": 5}),
        "users_fans": json.dumps({str(FAN_ID): 20, "91": 10}),
        "user_ranks": json.dumps({"hallOfFameMessagePosts": 2}), "messages_sent": 1200,
    }
    row.update(overrides)
    return row


TOTALS = {"members": 9, "messages_sent": 30000, "posts": 25}


def summary(**overrides):
    return wrapped_story.build_summary(wrapped_row(**overrides), TOTALS)


def texts(view) -> str:
    """Everything a view shows as text"""
    return "\n".join(item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay))


def buttons(view) -> dict:
    found = {}
    for item in view.walk_children():
        button = getattr(item, "item", item)
        if isinstance(button, discord.ui.Button):
            found[button.label] = item
    return found


def written_on(day: datetime.datetime, sequence: int = 0) -> int:
    """A message ID for a message written at that moment"""
    return discord.utils.time_snowflake(day) + sequence


class FakeInteraction:
    def __init__(self, user_id=USER_ID):
        self.user = types.SimpleNamespace(id=user_id, name="mia", display_name="Mia",
                                          display_avatar=types.SimpleNamespace(url="https://cdn.example/a.png"))
        self.edits = []
        self.sent = []
        self.followups = []
        interaction = self

        class Response:
            async def edit_message(self, **kwargs):
                interaction.edits.append(kwargs)

            async def send_message(self, content=None, **kwargs):
                interaction.sent.append((content, kwargs))

            async def defer(self, **kwargs):
                interaction.deferred = kwargs

        class Followup:
            async def send(self, content=None, **kwargs):
                interaction.followups.append((content, kwargs))

        self.response = Response()
        self.followup = Followup()


class SummaryTests(unittest.TestCase):
    def test_reads_the_stored_wrapped(self):
        member = summary()

        self.assertEqual(6, member.posts)
        self.assertEqual(30, member.reactions_received)
        self.assertEqual((FAN_ID, 20), member.top_fan)
        self.assertEqual(("💀", 9), member.top_emoji)
        self.assertEqual((100, 4), member.top_channel)
        self.assertEqual(2, member.rank)
        self.assertEqual(9, member.members)

    def test_fame_rate_is_messages_per_post(self):
        self.assertEqual(200, wrapped_story.member_fame_rate(summary()))
        self.assertEqual(1200, wrapped_story.server_fame_rate(summary()))

    def test_no_fame_rate_without_a_count(self):
        """A Wrapped made before messages were counted, or a search that gave no answer."""
        self.assertIsNone(wrapped_story.member_fame_rate(summary(messages_sent=None)))
        self.assertIsNone(wrapped_story.fame_rate(0, 500))

    def test_the_rate_is_never_below_one_in_one(self):
        self.assertEqual(1, wrapped_story.fame_rate(10, 3))


class TitleTests(unittest.TestCase):
    def title(self, **overrides):
        return wrapped_story.title_for(summary(**overrides))[0]

    def test_the_most_featured_member_headlines(self):
        self.assertEqual("The Headliner", self.title(user_ranks=json.dumps({"hallOfFameMessagePosts": 1})))

    def test_a_high_fame_rate_is_a_sharpshooter(self):
        self.assertEqual("The Sharpshooter", self.title(messages_sent=600))

    def test_many_posts_is_a_regular(self):
        self.assertEqual("The Regular", self.title(hof_message_posts=30, messages_sent=None))

    def test_giving_more_than_getting_is_the_hype_crew(self):
        self.assertEqual("The Hype Crew", self.title(messages_sent=None, reaction_count=100))

    def test_many_channels_is_an_explorer(self):
        channels = json.dumps({str(channel): 1 for channel in range(5)})
        self.assertEqual("The Explorer", self.title(messages_sent=None, most_used_channels=channels))

    def test_everyone_else_is_a_rising_star(self):
        self.assertEqual("The Rising Star", self.title(messages_sent=None))


class StoryPageTests(unittest.TestCase):
    def kickers(self, member):
        return [page.kicker for page in wrapped_story.story_pages(member, "Mia", None)]

    def test_counted_messages_get_a_fame_rate_page_with_the_server_average(self):
        pages = wrapped_story.story_pages(summary(), "Mia", None)
        fame = next(page for page in pages if page.kicker == messages.WRAPPED_FAME_KICKER)

        self.assertEqual("1 in 200", fame.big)
        self.assertIn("1 in 1,200", fame.text)

    def test_without_a_count_the_fame_rate_page_is_left_out(self):
        self.assertNotIn(messages.WRAPPED_FAME_KICKER, self.kickers(summary(messages_sent=None)))

    def test_the_best_moment_links_to_the_post(self):
        pages = wrapped_story.story_pages(summary(), "Mia", None)
        best = next(page for page in pages if page.kicker == messages.WRAPPED_BEST_KICKER)

        self.assertEqual(f"https://discord.com/channels/{GUILD_ID}/100/4242", best.link)

    def test_ends_on_the_title(self):
        self.assertEqual(messages.WRAPPED_TITLE_KICKER, self.kickers(summary())[-1])


class StoryViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.row = wrapped_row()
        self.opted_out = False

        class Lend:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_args):
                return False

        for target, name, value in (
                (wrapped_story, "connect", lambda: Lend()),
                (wrapped_story.hof_wrapped_repo, "get_hof_wrapped", lambda *_args: self.row),
                (wrapped_story.opt_out_repo, "is_opted_out", lambda *_args: self.opted_out)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def share_after(self, change):
        view = self.story()
        await buttons(view)[messages.WRAPPED_SKIP].callback(FakeInteraction())
        change()
        interaction = FakeInteraction()
        await buttons(view)[messages.WRAPPED_SHARE].callback(interaction)
        return interaction

    async def test_a_member_who_opted_out_since_opening_cannot_show_it(self):
        interaction = await self.share_after(lambda: setattr(self, "opted_out", True))

        [(content, sent)] = interaction.followups
        self.assertEqual(messages.WRAPPED_CARD_GONE, content)
        self.assertTrue(sent.get("ephemeral"))

    async def test_a_member_who_deleted_their_data_since_opening_cannot_show_it(self):
        interaction = await self.share_after(lambda: setattr(self, "row", None))

        [(content, _sent)] = interaction.followups
        self.assertEqual(messages.WRAPPED_CARD_GONE, content)

    def story(self, **overrides):
        return wrapped_story.StoryView(summary(**overrides), "Mia", "https://cdn.example/a.png", None)

    async def test_opens_on_the_first_page_with_back_disabled(self):
        view = self.story()

        self.assertIn("# Mia", texts(view))
        self.assertTrue(buttons(view)[messages.WRAPPED_BACK].disabled)

    async def test_next_turns_the_page_in_place(self):
        view = self.story()
        interaction = FakeInteraction()
        await buttons(view)[messages.WRAPPED_NEXT].callback(interaction)

        self.assertEqual(1, view.index)
        self.assertEqual([{"view": view}], interaction.edits)
        self.assertIn("# 6", texts(view))

    async def test_two_presses_together_post_one_plaque(self):
        """Both can arrive before the first one disables the button."""
        view = self.story()
        await buttons(view)[messages.WRAPPED_SKIP].callback(FakeInteraction())
        share = buttons(view)[messages.WRAPPED_SHARE]
        first, second = FakeInteraction(), FakeInteraction()
        await share.callback(first)
        await share.callback(second)

        self.assertEqual(1, len(first.followups))
        self.assertEqual([], second.followups)

    async def test_skip_goes_to_the_summary_which_offers_to_show_it(self):
        view = self.story()
        await buttons(view)[messages.WRAPPED_SKIP].callback(FakeInteraction())

        self.assertTrue(view.on_summary)
        self.assertIn(messages.WRAPPED_SHARE, buttons(view))
        self.assertNotIn(messages.WRAPPED_MINE_BUTTON, buttons(view), "the member's own copy needs no invite")

    async def test_showing_posts_the_plaque_once_without_pinging(self):
        view = self.story()
        await buttons(view)[messages.WRAPPED_SKIP].callback(FakeInteraction())
        interaction = FakeInteraction()
        await buttons(view)[messages.WRAPPED_SHARE].callback(interaction)

        [(_content, sent)] = interaction.followups
        self.assertNotIn("ephemeral", sent, "the plaque is for the whole channel")
        self.assertEqual(discord.AllowedMentions.none().to_dict(), sent["allowed_mentions"].to_dict())
        self.assertIn(messages.WRAPPED_SHARED_BY.format(member=f"<@{USER_ID}>"), texts(sent["view"]))
        self.assertTrue(buttons(view)[messages.WRAPPED_SHARED].disabled)

    async def test_the_shared_plaque_has_the_cards_and_an_invite(self):
        plaque = wrapped_story.plaque_view(summary(), "Mia", None, None)
        labels = buttons(plaque)

        for label in (messages.WRAPPED_SQUARES_BUTTON, messages.WRAPPED_TOP_BUTTON, messages.WRAPPED_MINE_BUTTON,
                      messages.WRAPPED_JUMP):
            self.assertIn(label, labels)
        self.assertIn("1 in 200", texts(plaque))
        self.assertIn(f"<@{FAN_ID}>", texts(plaque))

    async def test_a_plaque_without_a_count_leaves_the_rate_out(self):
        plaque = wrapped_story.plaque_view(summary(messages_sent=None), "Mia", None, None)
        self.assertNotIn("1 in", texts(plaque))


class BestPostMediaTests(unittest.TestCase):
    def message(self, flags=0, nsfw=False, attachments=None):
        attachment = types.SimpleNamespace(url="https://cdn.example/cat.png", content_type="image/png",
                                           is_spoiler=lambda: False, flags=discord.AttachmentFlags._from_value(flags))
        channel = types.SimpleNamespace(is_nsfw=lambda: nsfw)
        return types.SimpleNamespace(attachments=[attachment] if attachments is None else attachments, embeds=[],
                                     channel=channel)

    def test_shows_the_first_picture(self):
        self.assertEqual("https://cdn.example/cat.png", wrapped_story.best_post_media(self.message()).media.url)

    def test_leaves_out_media_discord_flagged(self):
        self.assertIsNone(wrapped_story.best_post_media(self.message(flags=1 << 6)))

    def test_leaves_out_media_from_an_age_restricted_channel(self):
        """The plaque can be shown in any channel."""
        self.assertIsNone(wrapped_story.best_post_media(self.message(nsfw=True)))

    def test_nothing_without_a_post_or_a_picture(self):
        self.assertIsNone(wrapped_story.best_post_media(None))
        self.assertIsNone(wrapped_story.best_post_media(self.message(attachments=[])))


class CardTests(unittest.TestCase):
    def post(self, day, reactions=5, channel_id=100, sequence=0):
        return {"message_id": written_on(day, sequence), "channel_id": channel_id, "reaction_count": reactions}

    def test_only_posts_written_that_year_count(self):
        posts = [self.post(datetime.datetime(YEAR, 3, 1, tzinfo=datetime.timezone.utc)),
                 self.post(datetime.datetime(YEAR - 1, 12, 31, 23, tzinfo=datetime.timezone.utc))]
        self.assertEqual(1, len(wrapped_story.posts_in_year(posts, YEAR)))

    def test_squares_have_a_row_per_month_and_a_square_per_day(self):
        day = datetime.datetime(YEAR, 2, 3, 22, tzinfo=datetime.timezone.utc)
        posts = wrapped_story.posts_in_year([self.post(day, sequence=n) for n in range(3)], YEAR)
        card = wrapped_story.squares_card("<@77>", YEAR, posts)
        rows = card.split("```")[1].strip().splitlines()

        self.assertEqual(12, len(rows))
        self.assertEqual("FEB ··█" + "·" * 25, rows[1])
        self.assertIn(messages.WRAPPED_SQUARES_HOUR.format(hour=22), card)

    def test_the_longest_run_counts_days_in_a_row(self):
        days = [datetime.date(YEAR, 1, 1), datetime.date(YEAR, 1, 2), datetime.date(YEAR, 1, 3),
                datetime.date(YEAR, 1, 9)]
        self.assertEqual(3, wrapped_story.longest_daily_run(days))

    def test_the_top_list_ranks_by_reactions_and_stops_at_ten(self):
        start = datetime.datetime(YEAR, 5, 1, tzinfo=datetime.timezone.utc)
        posts = wrapped_story.posts_in_year(
            [self.post(start + datetime.timedelta(days=n), reactions=n) for n in range(12)], YEAR)
        card = wrapped_story.top_card("<@77>", YEAR, GUILD_ID, posts)
        lines = card.splitlines()

        self.assertEqual(11, len(lines))
        self.assertTrue(lines[1].startswith("**1.** 11 reactions"))
        self.assertIn(f"https://discord.com/channels/{GUILD_ID}/100/", lines[1])


class ShowCardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.row = wrapped_row()
        self.opted_out = False
        self.posts = [{"message_id": written_on(datetime.datetime(YEAR, 4, 1, tzinfo=datetime.timezone.utc)),
                       "channel_id": 100, "reaction_count": 7}]

        class Lend:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_args):
                return False

        for target, name, value in (
                (wrapped_story, "connect", lambda: Lend()),
                (wrapped_story.hof_wrapped_repo, "get_hof_wrapped", lambda *_args: self.row),
                (wrapped_story.opt_out_repo, "is_opted_out", lambda *_args: self.opted_out),
                (wrapped_story.hall_of_fame_message_repo, "get_member_posts", lambda *_args: self.posts)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def press(self, kind="top"):
        interaction = FakeInteraction(user_id=FAN_ID)
        await wrapped_story.show_card(interaction, GUILD_ID, USER_ID, YEAR, kind)
        [(content, sent)] = interaction.sent
        return content, sent

    async def test_answers_only_whoever_pressed(self):
        _content, sent = await self.press()

        self.assertTrue(sent["ephemeral"])
        self.assertIn("**1.** 7 reactions", texts(sent["view"]))

    async def test_squares(self):
        _content, sent = await self.press("squares")
        self.assertIn("APR ▒", texts(sent["view"]))

    async def test_a_member_who_stopped_being_featured_is_not_shown(self):
        self.opted_out = True
        content, _sent = await self.press()
        self.assertEqual(messages.WRAPPED_CARD_GONE, content)

    async def test_a_deleted_wrapped_is_not_shown(self):
        self.row = None
        content, _sent = await self.press()
        self.assertEqual(messages.WRAPPED_CARD_GONE, content)

    async def test_no_posts_that_year(self):
        self.posts = []
        content, _sent = await self.press()
        self.assertEqual(messages.WRAPPED_CARD_EMPTY.format(year=YEAR), content)


class PlaqueButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_card_buttons_are_rebuilt_from_their_custom_id(self):
        """So a plaque posted before a restart still answers."""
        for cls, args in ((wrapped_story.SquaresButton, (GUILD_ID, USER_ID, YEAR)),
                          (wrapped_story.TopButton, (GUILD_ID, USER_ID, YEAR)),
                          (wrapped_story.MineButton, (GUILD_ID,))):
            original = cls(*args)
            match = cls.__discord_ui_compiled_template__.fullmatch(original.item.custom_id)
            rebuilt = await cls.from_custom_id(None, original.item, match)
            self.assertEqual(original.item.custom_id, rebuilt.item.custom_id)

    async def test_get_my_wrapped_opens_the_pressers_own(self):
        opened = []

        async def open_wrapped(interaction):
            opened.append(interaction)

        interaction = FakeInteraction(user_id=FAN_ID)
        with mock.patch.object(wrapped_story, "open_wrapped_handler", open_wrapped):
            await wrapped_story.MineButton(GUILD_ID).callback(interaction)
        self.assertEqual([interaction], opened)


class CountMessagesSentTests(unittest.IsolatedAsyncioTestCase):
    def bot(self, *answers):
        asked = []

        async def request(route, params=None, **_kwargs):
            asked.append((route, params))
            answer = answers[len(asked) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.asked = asked
        return types.SimpleNamespace(http=types.SimpleNamespace(request=request))

    def setUp(self):
        patcher = mock.patch.object(hof_wrapped.asyncio, "sleep", mock.AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_asks_for_the_count_of_the_members_year_alone(self):
        count = await hof_wrapped.count_messages_sent(self.bot({"total_results": 812}), GUILD_ID, USER_ID, YEAR)

        self.assertEqual(812, count)
        route, params = self.asked[0]
        self.assertEqual(hof_wrapped.SEARCH_ROUTE, route.path)
        self.assertEqual(USER_ID, params["author_id"])
        self.assertEqual(1, params["limit"])
        self.assertEqual(YEAR, discord.utils.snowflake_time(params["min_id"]).year)
        self.assertEqual(YEAR + 1, discord.utils.snowflake_time(params["max_id"]).year)

    async def test_asks_again_while_the_server_is_being_indexed(self):
        indexing = {"message": "Index not yet available. Try again later", "code": 110000, "retry_after": 2}
        count = await hof_wrapped.count_messages_sent(self.bot(indexing, {"total_results": 5}), GUILD_ID, USER_ID,
                                                      YEAR)
        self.assertEqual(5, count)

    async def test_gives_up_after_a_few_tries(self):
        indexing = {"code": 110000, "retry_after": 0}
        bot = self.bot(*[indexing] * hof_wrapped.search_attempts)
        self.assertIsNone(await hof_wrapped.count_messages_sent(bot, GUILD_ID, USER_ID, YEAR))

    async def test_a_refused_search_leaves_the_rate_out(self):
        refused = discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
        self.assertIsNone(await hof_wrapped.count_messages_sent(self.bot(refused), GUILD_ID, USER_ID, YEAR))


if __name__ == "__main__":
    unittest.main()


class GuildsToProcessTests(unittest.TestCase):
    """The Wrapped script can be limited to a few servers, such as test servers on the development bot."""

    def setUp(self):
        import types
        self.guilds = [types.SimpleNamespace(id=1), types.SimpleNamespace(id=2), types.SimpleNamespace(id=3)]

    def test_every_server_without_arguments(self):
        import hof_wrapped
        self.assertEqual([1, 2, 3], [guild.id for guild in hof_wrapped.guilds_to_process(self.guilds, [])])

    def test_only_the_servers_named(self):
        import hof_wrapped
        self.assertEqual([1, 3], [guild.id for guild in hof_wrapped.guilds_to_process(self.guilds, ["3", "1", "99"])])


class CountedTests(unittest.TestCase):
    """Wrapped wrote "1 posts" and "1 times"."""

    def test_one_is_singular_and_more_are_plural(self):
        import hof_wrapped
        self.assertEqual("1 post", hof_wrapped.counted(1, "post"))
        self.assertEqual("3 posts", hof_wrapped.counted(3, "post"))
        self.assertEqual("1 time", hof_wrapped.counted(1, "time"))
        self.assertEqual("0 reactions", hof_wrapped.counted(0, "reaction"))
