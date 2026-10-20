"""Posts whose author was removed, against a real PostgreSQL database.

Deleting a member's data on /my_data leaves their posts on their servers' boards but stores them
with author 0, which is nobody. Every query that reads posts has to agree on what that means: the
server still has the post, so its own counts and top posts keep it, but no member is credited with it,
so nothing that is about a member may find it. These tests detach a member's posts with the same
statement the deletion runs and then check each read on the rows that are left.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import datetime

from repositories import global_profile_repo, hall_of_fame_message_repo, server_config_repo, server_user_repo

from tests.integration.database import DatabaseTestCase, skip_without_database

HOME, AWAY = 9201, 9202
REMOVED_MEMBER, MEMBER = 301, 302
NO_AUTHOR = hall_of_fame_message_repo.NO_AUTHOR_ID
CHANNEL = 500
WINDOW_START = datetime.datetime(2026, 9, 1)


def at(month, day=10):
    return datetime.datetime(2026, month, day, 12, 0)


# (message id, guild, author, reactions, created_at). The member who is removed had the biggest post and
# the most posts in September, so every read that wrongly kept them would show it
POSTS = (
    (1, HOME, REMOVED_MEMBER, 50, at(9, 1)),
    (2, HOME, REMOVED_MEMBER, 40, at(9, 2)),
    (3, HOME, REMOVED_MEMBER, 30, at(9, 3)),
    (4, HOME, MEMBER, 20, at(9, 4)),
    (5, HOME, MEMBER, 10, at(8, 4)),
    (6, AWAY, REMOVED_MEMBER, 60, at(9, 5)),
)


@skip_without_database
class RemovedAuthorTestCase(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        for guild in (HOME, AWAY):
            server_config_repo.insert_server_config(self.connection, guild)
        for message_id, guild, author, reactions, created_at in POSTS:
            self.store(message_id, guild, author, reactions, created_at)
        self.detached = hall_of_fame_message_repo.remove_author(self.connection, REMOVED_MEMBER)

    def store(self, message_id, guild, author, reactions, created_at):
        hall_of_fame_message_repo.insert_hall_of_fame_message(
            self.connection, message_id, CHANNEL, guild, message_id + 5000, reactions, author, created_at)

    def authors(self):
        return dict(self.rows("SELECT message_id, author_id FROM hall_of_fame_message"))


class DetachingTests(RemovedAuthorTestCase):
    def test_detaches_the_members_posts_in_every_server(self):
        self.assertEqual(4, self.detached)
        self.assertEqual({1: NO_AUTHOR, 2: NO_AUTHOR, 3: NO_AUTHOR, 4: MEMBER, 5: MEMBER, 6: NO_AUTHOR},
                         self.authors())

    def test_detaching_again_finds_nothing(self):
        self.assertEqual(0, hall_of_fame_message_repo.remove_author(self.connection, REMOVED_MEMBER))

    def test_storing_a_detached_post_again_keeps_it_detached(self):
        """Its reaction count still updates, but the member who deleted their data is not credited again."""
        self.store(1, HOME, REMOVED_MEMBER, 55, at(9, 1))

        self.assertEqual(NO_AUTHOR, self.authors()[1])
        self.assertEqual([(55,)], self.rows("SELECT reaction_count FROM hall_of_fame_message WHERE message_id = 1"))

    def test_storing_a_post_again_still_updates_a_known_author(self):
        self.store(4, HOME, REMOVED_MEMBER, 20, at(9, 4))

        self.assertEqual(REMOVED_MEMBER, self.authors()[4])

    def test_new_posts_by_the_member_are_credited_to_them(self):
        """A plain deletion counts what is featured later, so only the posts from before stay detached."""
        self.store(7, HOME, REMOVED_MEMBER, 5, at(9, 20))

        self.assertEqual([7], [post["message_id"] for post in
                               hall_of_fame_message_repo.get_messages_by_author(self.connection, REMOVED_MEMBER)])


class ServerReadsTests(RemovedAuthorTestCase):
    """The posts still belong to the server, so the server's own numbers keep them."""

    def test_the_server_still_counts_every_post(self):
        self.assertEqual(5, hall_of_fame_message_repo.count_messages_for_guild(self.connection, HOME))

    def test_detached_posts_still_count_toward_the_daily_limit(self):
        today = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        self.store(8, HOME, MEMBER, 5, today)
        self.store(9, HOME, REMOVED_MEMBER, 5, today)
        hall_of_fame_message_repo.remove_author(self.connection, REMOVED_MEMBER)

        self.assertEqual(2, hall_of_fame_message_repo.guild_message_count_today(self.connection, HOME))

    def test_post_activity_for_the_setup_check_keeps_them(self):
        self.assertEqual(5, hall_of_fame_message_repo.get_post_activity(self.connection, HOME)["total"])

    def test_monthly_statistics_keep_them(self):
        counts = hall_of_fame_message_repo.get_monthly_message_counts_by_guild(self.connection, at(9, 1), at(10, 1))

        self.assertEqual({HOME: 4, AWAY: 1}, {row["guild_id"]: row["message_count"] for row in counts})

    def test_the_top_posts_keep_them(self):
        """They are the server's posts. The member's name on them comes from Discord, not from this row."""
        top = hall_of_fame_message_repo.find_top_messages_by_reaction_count(self.connection, HOME, limit=2)

        self.assertEqual([(1, NO_AUTHOR), (2, NO_AUTHOR)], [(post["message_id"], post["author_id"]) for post in top])

    def test_wrapped_reads_them_with_no_author(self):
        """Wrapped skips them by the stored author, so it must be the stored one that comes back."""
        posts = hall_of_fame_message_repo.get_all_hall_of_fame_messages_for_guild(self.connection, HOME)

        self.assertEqual({1: NO_AUTHOR, 2: NO_AUTHOR, 3: NO_AUTHOR, 4: MEMBER, 5: MEMBER},
                         {post["message_id"]: post["author_id"] for post in posts})


class MemberReadsTests(RemovedAuthorTestCase):
    """Nothing about a member may find a detached post, and nobody is made out of author 0."""

    def test_the_server_has_no_member_for_the_detached_posts(self):
        self.assertEqual([MEMBER], hall_of_fame_message_repo.find_members_for_guild(self.connection, HOME))

    def test_a_server_with_only_detached_posts_has_no_members(self):
        self.assertEqual([], hall_of_fame_message_repo.find_members_for_guild(self.connection, AWAY))

    def test_the_removed_member_has_no_posts(self):
        self.assertEqual([], hall_of_fame_message_repo.get_messages_by_author(self.connection, REMOVED_MEMBER))

    def test_the_other_member_keeps_only_their_own_posts(self):
        posts = hall_of_fame_message_repo.get_messages_by_author(self.connection, MEMBER)

        self.assertEqual([4, 5], sorted(post["message_id"] for post in posts))

    def test_the_removed_member_has_no_highlights(self):
        self.assertEqual({"best_post": None, "last_featured": None},
                         hall_of_fame_message_repo.get_member_highlights(self.connection, HOME, REMOVED_MEMBER))

    def test_the_best_post_is_the_members_own_and_not_a_bigger_detached_one(self):
        highlights = hall_of_fame_message_repo.get_member_highlights(self.connection, HOME, MEMBER)

        self.assertEqual(4, highlights["best_post"]["message_id"])
        self.assertEqual(20, highlights["best_post"]["reaction_count"])

    def test_the_removed_member_has_no_badge_facts(self):
        self.assertEqual({"posts_by_month": [], "first_featured": None, "biggest_post": 0, "champion_months": 0},
                         hall_of_fame_message_repo.get_member_badge_facts(self.connection, HOME, REMOVED_MEMBER))

    def test_the_month_the_removed_member_led_goes_to_the_next_member(self):
        """Three detached posts beat one in September, but nobody is crowned for them."""
        facts = hall_of_fame_message_repo.get_member_badge_facts(self.connection, HOME, MEMBER)

        self.assertEqual(2, facts["champion_months"])
        self.assertEqual(20, facts["biggest_post"])

    def test_the_removed_member_has_no_totals_across_servers(self):
        self.assertEqual({field: 0 for field in global_profile_repo.PROFILE_FIELDS},
                         global_profile_repo.get_global_profile(self.connection, REMOVED_MEMBER))

    def test_the_other_members_totals_across_servers_leave_the_detached_posts_out(self):
        profile = global_profile_repo.get_global_profile(self.connection, MEMBER)

        self.assertEqual(2, profile["posts"])
        self.assertEqual(30, profile["reactions"])
        self.assertEqual(1, profile["servers"])


class StatisticsTests(RemovedAuthorTestCase):
    def setUp(self):
        super().setUp()
        server_user_repo.rebuild_user_stats_for_guild(self.connection, HOME, WINDOW_START)

    def test_the_rebuild_writes_no_row_for_author_0(self):
        self.assertEqual([(MEMBER,)], self.rows("SELECT user_id FROM server_user WHERE guild_id = %s", (HOME,)))

    def test_the_other_member_is_first_on_every_leaderboard(self):
        self.assertEqual([(1, 1, 1, 1)], self.rows(
            "SELECT total_message_rank, monthly_message_rank, total_reaction_rank, monthly_reaction_rank "
            "FROM server_user WHERE user_id = %s AND guild_id = %s", (MEMBER, HOME)))

    def test_the_other_member_is_champion(self):
        self.assertTrue(server_user_repo.check_if_user_is_top_of_stat(
            self.connection, MEMBER, HOME, "total_hall_of_fame_messages"))
