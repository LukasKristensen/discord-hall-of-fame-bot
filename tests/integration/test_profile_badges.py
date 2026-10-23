"""The badges on /user_profile, against a real PostgreSQL database.

Badges are worked out from the posts every time, with nothing stored, so these tests check the SQL
behind them on real rows: calendar-month champions with ties and removed authors, month streaks, and
that a member who hid their totals across servers gets no badge from another server.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime
import types

import commands
from repositories import global_profile_repo, hall_of_fame_message_repo, server_config_repo
from translations import messages

from tests.integration.database import DatabaseTestCase, skip_without_database

HOME, AWAY, FAR_AWAY, FOURTH, FIFTH = 9101, 9102, 9103, 9104, 9105
MAYA, SAM, NOBODY = 201, 202, 203
REMOVED = hall_of_fame_message_repo.NO_AUTHOR_ID

NOW = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=datetime.timezone.utc)


def at(year, month, day=10):
    return datetime.datetime(year, month, day, 12, 0)


# (guild, author, reactions, created_at)
POSTS = (
    # Maya at home: once in June 2025, then January to March 2026 in a row
    [(HOME, MAYA, 5, at(2025, 6))]
    + [(HOME, MAYA, 30, at(2026, 1)), (HOME, MAYA, 4, at(2026, 1, 20))]
    + [(HOME, MAYA, 6, at(2026, 2))]
    + [(HOME, MAYA, 7, at(2026, 3))]
    # Sam ties Maya in January, where the lower user ID wins, and beats her in February
    + [(HOME, SAM, 3, at(2026, 1)), (HOME, SAM, 3, at(2026, 1, 21))]
    + [(HOME, SAM, 3, at(2026, 2, day)) for day in (1, 2, 3)]
    # Posts whose author was removed would win March, but have nobody to crown
    + [(HOME, REMOVED, 9, at(2026, 3, day)) for day in range(1, 6)]
    # Maya elsewhere: a 120-reaction post, and 10 posts in one month
    + [(AWAY, MAYA, 120, at(2026, 4))]
    + [(FAR_AWAY, MAYA, 2, at(2026, 5, day)) for day in range(1, 11)]
    # One post each in two more servers, so Maya is featured in five
    + [(FOURTH, MAYA, 1, at(2026, 6)), (FIFTH, MAYA, 1, at(2026, 7))]
)


@skip_without_database
class ProfileBadgesTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        for guild in (HOME, AWAY, FAR_AWAY, FOURTH, FIFTH):
            server_config_repo.insert_server_config(self.connection, guild)
        for message_id, (guild, author, reactions, created_at) in enumerate(POSTS, start=1):
            hall_of_fame_message_repo.insert_hall_of_fame_message(
                self.connection, message_id, 500 + guild, guild, message_id + 5000, reactions, author, created_at)

    def facts(self, user_id, guild=HOME):
        return hall_of_fame_message_repo.get_member_badge_facts(self.connection, guild, user_id)


class BadgeFactsTests(ProfileBadgesTestCase):
    def test_counts_posts_by_calendar_month(self):
        self.assertEqual([(at(2025, 6, 1).replace(hour=0), 1), (at(2026, 1, 1).replace(hour=0), 2),
                          (at(2026, 2, 1).replace(hour=0), 1), (at(2026, 3, 1).replace(hour=0), 1)],
                         self.facts(MAYA)["posts_by_month"])

    def test_first_featured_and_biggest_post_are_from_this_server_only(self):
        facts = self.facts(MAYA)

        self.assertEqual(at(2025, 6), facts["first_featured"])
        self.assertEqual(30, facts["biggest_post"])

    def test_champion_months_break_ties_by_user_id_and_skip_removed_authors(self):
        """June 2025, January on the tie and March over the removed author's posts go to Maya."""
        self.assertEqual(3, self.facts(MAYA)["champion_months"])
        self.assertEqual(1, self.facts(SAM)["champion_months"])

    def test_a_member_with_nothing_here(self):
        self.assertEqual({"posts_by_month": [], "first_featured": None, "biggest_post": 0, "champion_months": 0},
                         self.facts(NOBODY))

    def test_only_reads_the_server_asked_about(self):
        facts = self.facts(MAYA, guild=AWAY)

        self.assertEqual(1, len(facts["posts_by_month"]))
        self.assertEqual(120, facts["biggest_post"])
        self.assertEqual(1, facts["champion_months"])


class BadgesOnTheProfileTests(ProfileBadgesTestCase):
    async def badges_field(self, hidden: bool):
        sent = []

        async def send(embed=None, **_kwargs):
            sent.append(embed)

        # The command defers first, so the card goes out as its followup
        interaction = types.SimpleNamespace(
            guild=types.SimpleNamespace(id=HOME, name="Home"),
            followup=types.SimpleNamespace(send=send))
        user = types.SimpleNamespace(id=MAYA, name="maya",
                                     display_avatar=types.SimpleNamespace(url="https://example.com/a.png"))
        if hidden:
            global_profile_repo.set_hidden(self.connection, MAYA, True)
        # The command reads the hidden flag the same way before building the card
        global_profile = (None if global_profile_repo.is_hidden(self.connection, MAYA)
                          else global_profile_repo.get_global_profile(self.connection, MAYA))
        await commands.user_server_profile(interaction, user, {"total_hall_of_fame_messages": 5},
                                           self.connection, ":m:", ":a:", global_profile)
        fields = {field.name: field.value for field in sent[0].fields}
        return fields.get(messages.BADGES_HEADING, "")

    async def test_shows_badges_from_every_server(self):
        badges = await self.badges_field(hidden=False)

        for badge in (messages.BADGE_MONTHLY_CHAMPION, messages.BADGE_STREAK.format(months=3),
                      messages.BADGE_VETERAN, messages.BADGE_BIG_POST, messages.BADGE_BIG_MONTH,
                      messages.BADGE_SERVERS.format(servers=5)):
            self.assertIn(badge, badges)

    async def test_hidden_totals_leave_out_badges_from_other_servers(self):
        badges = await self.badges_field(hidden=True)

        self.assertIn(messages.BADGE_MONTHLY_CHAMPION, badges)
        self.assertIn(messages.BADGE_VETERAN, badges)
        for badge in (messages.BADGE_BIG_POST, messages.BADGE_BIG_MONTH, "servers"):
            self.assertNotIn(badge, badges)

    async def test_a_server_that_opted_out_earns_no_badge_elsewhere(self):
        """The 120-reaction post is from AWAY, so once AWAY stops counting the badge goes with it."""
        server_config_repo.update_server_config_param(AWAY, "count_in_global_profiles", False, self.connection)
        badges = await self.badges_field(hidden=False)

        self.assertNotIn(messages.BADGE_BIG_POST, badges)
        self.assertNotIn("servers", badges)
