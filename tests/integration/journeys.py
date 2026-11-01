"""The base for the journey tests: the running bot's own handlers, a faked Discord and a real database.

A journey is what one person does with the bot from start to end: an admin adding it and setting it up, a
member's message climbing onto the board and dropping off again, a member asking for their data. The
tests drive main's event handlers and slash commands, the same entry points Discord calls, against the
fakes in discord_world and a real PostgreSQL schema, and check what each person sees along the way.

The journeys are listed in tests/JOURNEYS.md. They need HOF_TEST_DATABASE_URL, see
tests/integration/database.py, and are skipped without it.
"""

from unittest import mock

import commands
import events
import main
import utils
from caches import ExpiringSet
from repositories import hall_of_fame_message_repo

from tests.integration.database import DatabaseTestCase, SingleConnectionPool
from tests.integration.discord_world import Author, Bot, Guild, Interaction, SourceChannel, reaction_payload

GUILD = 9301
GENERAL = 501
ADMIN = Author(1001, manage_guild=True)
AUTHOR = Author(2001)
FANS = [Author(user_id) for user_id in range(3001, 3011)]
# A server of 50 members starts with a threshold of 7, so most journeys lower it first, as admins do
STARTING_THRESHOLD = 7


class JourneyTestCase(DatabaseTestCase):
    """One server with a general channel, a bot that has not joined it yet, and main wired to both"""

    def setUp(self):
        super().setUp()
        self.guild = Guild(GUILD, member_count=50)
        self.general = SourceChannel(GENERAL, self.guild)
        self.bot = Bot(self.guild)
        self.logged = []

        async def record_log(_bot, message, *_args, **_kwargs):
            self.logged.append(str(message))

        async def no_stats():
            pass

        utils.daily_limit_handled_on.clear()
        utils.members_at_post_limit_logged.clear()
        for target, name, value in (
                (utils, "logging", record_log),
                (main, "connection_pool", SingleConnectionPool(self.connection)),
                (main, "bot", self.bot),
                (main, "bot_loaded", True),
                (main, "server_classes", {}),
                (main, "daily_command_cooldowns", {}),
                (main, "why_cooldown", ExpiringSet(ttl_seconds=main.why_cooldown_seconds)),
                (main, "post_api_bot_stats", no_stats),
                (events, "recent_setup_failure_notices", ExpiringSet(ttl_seconds=3600)),
                # What on_ready registers, so the persistent buttons on the welcome message answer
                (commands, "setup_check_handler", main.run_setup_check),
                (commands, "settings_form_handler", main.open_settings_form)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    # The server

    async def install(self, guild=None):
        """Discord tells the bot it was added to the server. Returns the board it made"""
        guild = guild or self.guild
        await main.on_guild_join(guild)
        config = main.server_classes.get(guild.id)
        return guild.get_channel(config.hall_of_fame_channel_id) if config is not None else None

    async def set_up(self, threshold=3):
        """Install the bot and lower the threshold, the first thing most admins do"""
        self.board = await self.install()
        if threshold != STARTING_THRESHOLD:
            await main.configure_bot.callback(self.command(ADMIN), threshold)
        return self.board

    @property
    def config(self):
        return main.server_classes.get(self.guild.id)

    # People

    def command(self, user, guild=..., channel_id=GENERAL, app_permissions=None):
        """A slash command or button press by a member, in the server unless a guild of None (a DM) is given"""
        return Interaction(user, self.guild if guild is ... else guild, channel_id, app_permissions)

    async def react(self, message, *users, emoji="🔥"):
        """Each member adds the emoji, and Discord tells the bot once per reaction"""
        for user in users:
            message.react(emoji, user.id)
            await main.on_raw_reaction_add(reaction_payload(message, user))

    async def unreact(self, message, *users, emoji="🔥"):
        for user in users:
            message.unreact(emoji, user.id)
            # Discord leaves the member out of a removed reaction
            payload = reaction_payload(message, user)
            payload.member = None
            await main.on_raw_reaction_remove(payload)

    @staticmethod
    async def press(view, button, user, guild=..., journey=None):
        """A member presses a button. Discord asks the view's interaction_check first, as it does for real"""
        interaction = journey.command(user, guild) if journey is not None else Interaction(user)
        check = getattr(view, "interaction_check", None)
        if check is None or await check(interaction):
            await button.callback(interaction)
        return interaction

    async def press_button(self, view, button, user, guild=...):
        return await self.press(view, button, user, guild, journey=self)

    @staticmethod
    def button(view, custom_id=None, label=None):
        for item in view.children:
            if (custom_id is not None and getattr(item, "custom_id", None) == custom_id) or \
                    (label is not None and getattr(item, "label", None) == label):
                return item
        raise AssertionError(f"No button {custom_id or label} on the view")

    # What the bot did

    def stored(self, message):
        return hall_of_fame_message_repo.find_hall_of_fame_message(self.connection, message.guild.id,
                                                                   message.channel.id, message.id)

    def post_of(self, message):
        stored = self.stored(message)
        return self.board.posts[stored["hall_of_fame_message_id"]] if stored else None

    def reposts(self):
        """The posts on the board that feature a message, leaving out the bot's notices"""
        return [post for post in self.board.sent if post.flags.components_v2]

    def errors_logged(self):
        return [entry for entry in self.logged if entry.startswith("Error") or "Traceback" in entry]

    def assert_no_errors_logged(self):
        self.assertEqual([], self.errors_logged())
