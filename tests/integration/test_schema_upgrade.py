"""Upgrading a database that already holds data, against a real PostgreSQL database.

Every change to a table reaches the production database the first time the new version starts, on
600+ servers' worth of rows. These tests build the tables the way production has them (the schema on
main before this branch, plus an older variant), fill them, and run the bot's own start-up setup over
them twice, as two restarts would. Nothing may be lost, every new column must get the right value on
old rows, and the result must match a database created from scratch.

They need HOF_TEST_DATABASE_URL, see tests/integration/database.py, and are skipped without it.
"""

import contextlib
import datetime
import io
import unittest
import uuid

import main
from repositories import server_config_repo

from tests.integration.database import DatabaseTestCase, skip_without_database

# The tables as main created them before this branch: no count_in_global_profiles or missing_since,
# no author or Wrapped member index, and none of the new tables
PRODUCTION_TABLES = [
    """
    CREATE TABLE server_configs (
        guild_id BIGINT PRIMARY KEY,
        hall_of_fame_channel_id BIGINT,
        reaction_threshold INT DEFAULT 5,
        post_due_date INT DEFAULT 30,
        leaderboard_message_ids TEXT[],
        sweep_limit INT DEFAULT 100,
        sweep_limited BOOLEAN DEFAULT TRUE,
        include_author_in_reaction_calculation BOOLEAN DEFAULT TRUE,
        allow_messages_in_hof_channel BOOLEAN DEFAULT TRUE,
        custom_emoji_check_logic BOOLEAN DEFAULT FALSE,
        whitelisted_emojis TEXT[],
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        leaderboard_setup BOOLEAN DEFAULT FALSE,
        ignore_bot_messages BOOLEAN DEFAULT FALSE,
        server_member_count INT DEFAULT 0,
        reaction_count_calculation_method VARCHAR(50) DEFAULT 'most_reactions_on_emoji',
        hide_hof_post_below_threshold BOOLEAN DEFAULT TRUE,
        require_image_or_video BOOLEAN DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE hall_of_fame_message (
        message_id BIGINT PRIMARY KEY,
        channel_id BIGINT NOT NULL,
        guild_id BIGINT NOT NULL,
        hall_of_fame_message_id BIGINT,
        reaction_count INTEGER NOT NULL,
        author_id BIGINT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        video_link_message_id BIGINT
    )
    """,
    "CREATE INDEX hall_of_fame_message_guild_created_idx ON hall_of_fame_message (guild_id, created_at)",
    """
    CREATE TABLE server_user (
        user_id BIGINT NOT NULL,
        guild_id BIGINT NOT NULL,
        monthly_reaction_rank INTEGER,
        total_message_rank INTEGER,
        total_reaction_rank INTEGER,
        this_month_hall_of_fame_messages INTEGER,
        total_hall_of_fame_messages INTEGER,
        monthly_message_rank INTEGER,
        this_month_hall_of_fame_message_reactions INTEGER,
        total_hall_of_fame_message_reactions INTEGER,
        PRIMARY KEY (user_id, guild_id)
    )
    """,
    """
    CREATE TABLE hof_wrapped (
        id SERIAL PRIMARY KEY,
        guild_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        year INTEGER NOT NULL,
        reaction_count INTEGER,
        hof_message_posts INTEGER,
        most_used_channels TEXT,
        most_used_emojis TEXT,
        most_reacted_post_message_id BIGINT,
        most_reacted_post_channel_id BIGINT,
        most_reacted_post_reaction_count INTEGER,
        fan_of_users TEXT,
        users_fans TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(guild_id, user_id, year),
        user_ranks TEXT
    )
    """,
]

GUILD = 9001
OLD_GUILD = 9002
MEMBER = 111111111111111111


@skip_without_database
class SchemaUpgradeTestCase(DatabaseTestCase):
    create_tables = False

    def build(self, statements):
        for statement in statements:
            self.execute(statement)

    def seed_production_rows(self):
        self.execute("INSERT INTO server_configs (guild_id, hall_of_fame_channel_id, reaction_threshold, "
                     "allow_messages_in_hof_channel, whitelisted_emojis, require_image_or_video) "
                     "VALUES (%s, 100, 7, FALSE, ARRAY['🔥'], TRUE)", (GUILD,))
        self.execute("INSERT INTO server_configs (guild_id, hall_of_fame_channel_id) VALUES (%s, 200)", (OLD_GUILD,))
        self.execute("INSERT INTO hall_of_fame_message VALUES (1, 100, %s, 5001, 9, %s, '2026-09-01 12:00', NULL)",
                     (GUILD, MEMBER))
        self.execute("INSERT INTO server_user (user_id, guild_id, total_hall_of_fame_messages, total_message_rank) "
                     "VALUES (%s, %s, 1, 1)", (MEMBER, GUILD))
        self.execute("INSERT INTO hof_wrapped (guild_id, user_id, year, fan_of_users) VALUES (%s, %s, 2025, '{}')",
                     (GUILD, MEMBER))

    def data(self):
        """The rows that existed before the upgrade, in the columns they had then"""
        return {
            "server_configs": self.rows("SELECT guild_id, hall_of_fame_channel_id, reaction_threshold, "
                                        "allow_messages_in_hof_channel, whitelisted_emojis, require_image_or_video "
                                        "FROM server_configs ORDER BY guild_id"),
            "hall_of_fame_message": self.rows("SELECT * FROM hall_of_fame_message ORDER BY message_id"),
            "server_user": self.rows("SELECT * FROM server_user ORDER BY user_id, guild_id"),
            "hof_wrapped": self.rows("SELECT guild_id, user_id, year, fan_of_users FROM hof_wrapped ORDER BY id"),
        }

    def fresh_schema_shape(self):
        """Every table and its columns in a database created from scratch, for comparison"""
        schema = f"hof_fresh_{uuid.uuid4().hex[:12]}"
        self.execute(f"CREATE SCHEMA {schema}")
        try:
            self.execute(f"SET search_path TO {schema}")
            with contextlib.redirect_stdout(io.StringIO()):
                main.setup_databases(self.connection)
            return self.shape(schema)
        finally:
            self.execute(f"SET search_path TO {self.schema}")
            self.execute(f"DROP SCHEMA {schema} CASCADE")

    def shape(self, schema):
        return {(table, column, data_type) for table, column, data_type in self.rows(
            "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %s",
            (schema,))}


class ProductionUpgradeTests(SchemaUpgradeTestCase):
    def setUp(self):
        super().setUp()
        self.build(PRODUCTION_TABLES)
        self.seed_production_rows()
        self.before = self.data()
        self.setup_databases()

    def test_keeps_every_existing_row(self):
        self.assertEqual(self.before, self.data())

    def test_a_second_start_changes_nothing(self):
        once = self.data()
        shape = self.shape(self.schema)
        self.setup_databases()

        self.assertEqual(once, self.data())
        self.assertEqual(shape, self.shape(self.schema))

    def test_ends_with_the_same_tables_and_columns_as_a_new_database(self):
        self.assertEqual(self.fresh_schema_shape(), self.shape(self.schema))

    def test_existing_servers_count_toward_totals_across_servers(self):
        """The new setting defaults to on, for servers that existed before it as much as for new ones."""
        self.assertEqual([(GUILD, True), (OLD_GUILD, True)], self.rows(
            "SELECT guild_id, count_in_global_profiles FROM server_configs ORDER BY guild_id"))

    def test_existing_servers_are_not_marked_missing(self):
        self.assertEqual([(None,), (None,)], self.rows("SELECT missing_since FROM server_configs"))

    def test_adds_the_new_tables(self):
        for table in ("hidden_global_profile", "opted_out_member", "hof_wrapped_progress", "guild_lifecycle_event",
                      "guild_monthly_snapshot", "permission_warning"):
            with self.subTest(table=table):
                self.assertIn(table, self.tables())

    def test_adds_the_member_indexes(self):
        self.assertIn("hall_of_fame_message_author_idx", self.indexes("hall_of_fame_message"))
        self.assertIn("hall_of_fame_message_guild_created_idx", self.indexes("hall_of_fame_message"))
        self.assertIn("hof_wrapped_user_idx", self.indexes("hof_wrapped"))

    def test_the_bot_reads_the_upgraded_servers(self):
        servers = server_config_repo.get_server_classes(self.connection)

        self.assertEqual(7, servers[GUILD].reaction_threshold)
        self.assertEqual(["🔥"], servers[GUILD].whitelisted_emojis)
        self.assertTrue(servers[GUILD].require_image_or_video)
        self.assertFalse(servers[GUILD].allow_messages_in_hof_channel)
        self.assertTrue(servers[GUILD].count_in_global_profiles)
        self.assertTrue(servers[OLD_GUILD].count_in_global_profiles)

    def test_a_member_can_have_standing_in_several_servers(self):
        """The server_user key is the member and the server, so a second server is a second row."""
        self.execute("INSERT INTO server_user (user_id, guild_id, total_hall_of_fame_messages) VALUES (%s, %s, 3)",
                     (MEMBER, OLD_GUILD))

        self.assertEqual([(2,)], self.rows("SELECT COUNT(*) FROM server_user WHERE user_id = %s", (MEMBER,)))


class OlderSchemaUpgradeTests(SchemaUpgradeTestCase):
    """Servers set up before require_image_or_video, and server_user from before its composite key."""

    def setUp(self):
        super().setUp()
        statements = [statement.replace(",\n        require_image_or_video BOOLEAN DEFAULT FALSE", "")
                      .replace("PRIMARY KEY (user_id, guild_id)", "PRIMARY KEY (user_id)")
                      for statement in PRODUCTION_TABLES]
        self.build(statements)
        self.execute("INSERT INTO server_configs (guild_id, hall_of_fame_channel_id) VALUES (%s, 100)", (GUILD,))
        self.execute("INSERT INTO server_user (user_id, guild_id, total_hall_of_fame_messages) VALUES (%s, %s, 4)",
                     (MEMBER, GUILD))
        self.setup_databases()

    def test_old_servers_do_not_require_images(self):
        self.assertEqual([(False,)], self.rows("SELECT require_image_or_video FROM server_configs"))

    def test_switches_server_user_to_the_member_and_server_key(self):
        key = self.rows("""
            SELECT array_agg(attribute.attname::text ORDER BY attribute.attname)
            FROM pg_index index
            JOIN pg_class class ON class.oid = index.indrelid
            JOIN pg_namespace namespace ON namespace.oid = class.relnamespace
            JOIN pg_attribute attribute ON attribute.attrelid = class.oid AND attribute.attnum = ANY(index.indkey)
            WHERE namespace.nspname = %s AND class.relname = 'server_user' AND index.indisprimary
        """, (self.schema,))[0][0]

        self.assertEqual(["guild_id", "user_id"], key)

    def test_keeps_the_existing_standing(self):
        self.assertEqual([(MEMBER, GUILD, 4)], self.rows(
            "SELECT user_id, guild_id, total_hall_of_fame_messages FROM server_user"))

    def test_ends_with_the_same_tables_and_columns_as_a_new_database(self):
        self.assertEqual(self.fresh_schema_shape(), self.shape(self.schema))


if __name__ == "__main__":
    unittest.main()
