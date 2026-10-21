from datetime import datetime, timezone
import io
import discord
from discord import app_commands
from discord.ext import commands as discord_commands
from discord.ext import tasks
# First of the bot's own modules, as importing it loads .env, leaving out the production-only values
# in development
import environment
import commands
import concurrency
import events
import message_check
import setup_check
import utils
import validation
from constants import version
from enums import command_refs, log_type, calculation_method_type
from classes.bot_stats import BotStats
from caches import ExpiringSet
from api_services import topgg_api, discordbotlist_api
import os
from translations import messages
import psycopg2
from psycopg2 import pool
from repositories import (
    server_config_repo,
    hall_of_fame_message_repo,
    server_user_repo,
    hof_wrapped_repo,
    hof_wrapped_guild_status_repo,
    guild_lifecycle_event_repo,
    guild_monthly_snapshot_repo,
    global_profile_repo,
    opt_out_repo,
)
import hof_wrapped
from contextlib import asynccontextmanager
from scripts import monthly_guild_snapshot
import asyncio

dev_test = environment.is_development()
TOKEN = os.getenv('DEV_KEY') if dev_test else os.getenv('KEY')
# Only the live bot reports to the listing sites, so the development bot never reads their keys
topgg_api_key = environment.production_secret('TOPGG_API_KEY')

# Opened when the bot starts rather than when this module is imported, so that importing it does
# not reach for a database. Nothing outside the running bot needs a pool, and a module that opens
# one on import cannot be loaded by anything else, tests included
connection_pool = None

database_pool_size = 20

# psycopg2 raises when every connection is checked out rather than waiting for one, and a reaction
# holds its connection for the whole handler, Discord round trips included. Under a burst that
# turned into reactions being dropped, and a dropped reaction is a message that never reaches the
# board at all, since nothing revisits it until somebody reacts again. So the waiting happens here:
# a caller queues for a slot, and the pool is never asked for more connections than it has
connection_slots = asyncio.Semaphore(database_pool_size)

# How long a caller waits for a slot before giving up. Waiting forever would let a burst queue
# without limit; giving up is still visible in the log, where waiting quietly would not be
connection_wait_timeout_seconds = 30


def create_connection_pool():
    """
    Open the pool the bot serves every command and reaction from
    :return: A thread safe connection pool for the configured database
    """
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=database_pool_size,
        **environment.database_settings())

message_locks = concurrency.KeyedLocks()
# Per member, not per server, so a limit follows the member into DMs and every server, user installs
# included. Cleared by the daily task
daily_command_cooldowns = {}
# How many times a member may send /feedback a day. A few, since one bug report often needs a follow-up,
# but capped, since through a user install anyone can open the form from any DM
feedback_daily_limit = 3
# Members who asked Why isn't this on the board? in the last few seconds
why_cooldown_seconds = 10
why_cooldown = ExpiringSet(ttl_seconds=why_cooldown_seconds)

# The longest a single query behind /my_data or /user_profile may run. psycopg2 holds
# the event loop while a query runs, so a slow one would stall the bot in every server; the database
# cancels it instead
data_command_statement_timeout_ms = 10_000

intents = discord.Intents.default()
intents.message_content = True
# Most commands work on a server's configuration or its members, so by default a command is offered only
# in servers that installed the bot. Without the explicit guild install Discord falls back to the install
# types enabled in the Developer Portal, and turning on user installs there would offer every setting in
# DMs, where it could only fail. The commands that make sense anywhere opt in with user_install
bot = discord_commands.Bot(command_prefix="/", intents=intents,
                           allowed_contexts=app_commands.AppCommandContext(guild=True),
                           allowed_installs=app_commands.AppInstallationType(guild=True))
tree = bot.tree
server_classes = {}
bot_stats = BotStats()

month_emoji = "<:month_most_hof_messages:1380272332609683517>" if not dev_test else "<:month_most_hof_messages:1380272983368532160>"
all_time_emoji = "<:all_time_most_hof_messages:1380272422842007622>" if not dev_test else "<:all_time_most_hof_messages:1380272953098244166>"

bot_loaded = False
# Summed over every guild on startup and by the daily task, and adjusted as servers join and leave in
# between, so the presence does not walk every guild on each join
total_member_count = 0

# How long each status stays up before the next one. Discord limits how often a bot may change its
# presence, and ten minutes stays far inside that while still showing every status within the hour
presence_rotation_minutes = 10
# How many statuses the rotation has shown, which decides the next one (see presence_status)
presence_index = 0
# The months the status also points to /hof_wrapped: December and January
wrapped_presence_months = (12, 1)


def user_install(command):
    """
    Offer a command through a user install too: in DMs, group DMs and servers without Hall of Fame, as
    well as in servers that installed the bot. Only for commands that need no server set up, or that
    check set_up_here and answer without one
    """
    command = app_commands.allowed_installs(guilds=True, users=True)(command)
    return app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(command)


def set_up_here(interaction: discord.Interaction) -> bool:
    """
    Whether the command was used in a server with Hall of Fame set up. False in a DM, and in a server
    that only reaches the bot through a member's user install, where there is no config to read
    """
    return interaction.guild_id is not None and server_classes.get(interaction.guild_id) is not None


def where_used(interaction: discord.Interaction) -> str:
    """
    Where a command was used, for the log: whether it was a server with the bot, never which one or who
    used it, since logs are kept. The server ID is added to the log on its own when there is one
    """
    return "a server" if getattr(interaction, "guild", None) is not None else "a DM or a server without the bot"


async def ensure_bot_is_loaded(interaction: discord.Interaction) -> bool:
    """
    Check that the bot has finished loading and let the user know when it has not,
    as staying silent leaves them with a failed interaction
    :param interaction: The interaction to respond to
    :return: True when the bot is ready to handle the command
    """
    if bot_loaded:
        return True
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.BOT_LOADING, ephemeral=True)
    return False


async def send_error(interaction: discord.Interaction, content: str):
    """
    Tell only the member who ran the command that it did not go through. A refusal is of no use to
    the rest of the channel, and answering in public turns a typo into clutter
    :param interaction: The interaction to answer
    :param content: What went wrong and what to do about it
    """
    # noinspection PyUnresolvedReferences
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(content, ephemeral=True)


async def refuse_in_closed_board(interaction: discord.Interaction) -> bool:
    """
    Turn away a command that answers with a public card when it is used in a Hall of Fame channel
    that is closed to chat. The bot deletes members' messages there, and a profile or leaderboard
    card left in the middle of the board would be the same clutter
    :param interaction: The command being answered
    :return: True when the command was turned away
    """
    server_class = server_classes.get(interaction.guild_id)
    if (server_class is None or server_class.allow_messages_in_hof_channel
            or getattr(interaction, "channel_id", None) != server_class.hall_of_fame_channel_id):
        return False
    await send_error(interaction, messages.COMMAND_NOT_IN_CLOSED_BOARD.format(
        channel=f"<#{server_class.hall_of_fame_channel_id}>"))
    return True


def on_off(value: bool) -> str:
    return "On" if value else "Off"


async def update_setting(interaction: discord.Interaction, parameter: str, value, label: str,
                         shown_value: str = None, note: str = "") -> bool:
    """
    Store a server setting and confirm it, or say so when it already had that value instead of
    writing it again
    :param interaction: The command being answered
    :param parameter: The configuration column, also the attribute on the server class
    :param value: The new value
    :param label: What the setting is called in the reply
    :param shown_value: How the value reads in the reply, On or Off when left out
    :param note: A line added to the confirmation, explaining what the change means
    :return: True when the setting changed
    """
    server_class = server_classes.get(interaction.guild_id)
    if server_class is None:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return False

    shown_value = shown_value if shown_value is not None else on_off(value)
    if getattr(server_class, parameter, None) == value:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(
            messages.SETTING_UNCHANGED.format(label=label, value=shown_value), ephemeral=True)
        return False

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, parameter, value, connection)
    setattr(server_class, parameter, value)

    content = messages.SETTING_CHANGED.format(label=label, value=shown_value)
    if note:
        content += f"\n{note}"
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(content)
    return True


def plural(count: int) -> str:
    return "" if count == 1 else "s"

@asynccontextmanager
async def get_db_connection(connection_pool):
    """
    Borrow a connection, waiting for a free one rather than failing when they are all in use
    :param connection_pool: The pool to borrow from
    """
    try:
        await asyncio.wait_for(connection_slots.acquire(), connection_wait_timeout_seconds)
    except asyncio.TimeoutError:
        await utils.logging(bot, f"Waited {connection_wait_timeout_seconds} seconds for a database "
                                 f"connection and gave up, so this event was not handled",
                            log_level=log_type.CRITICAL, validate_for_duplicates=True)
        raise

    try:
        conn = connection_pool.getconn()
    except Exception:
        connection_slots.release()
        raise

    try:
        try:
            yield conn
            conn.commit()
        except Exception as e:
            # Anything raised while the connection is held lands here, most of it Discord errors
            # rather than database ones, so it is an ordinary error and not a page. Only failing to
            # get a connection at all, above, is critical
            await utils.logging(bot, f"Error while holding a database connection: {e}",
                                validate_for_duplicates=True)
            raise
    finally:
        connection_pool.putconn(conn)
        connection_slots.release()

@bot.event
async def on_ready():
    global server_classes
    global bot_loaded

    try:
        version.DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await events.bot_login(bot, tree)
        await utils.logging(bot, f"Logged in as {bot.user}", log_level=log_type.SYSTEM, validate_for_duplicates=False)

        # Answers Troubleshoot on every welcome message ever sent, including those from before this boot.
        # Registering again after a reconnect only replaces the same entry
        commands.setup_check_handler = run_setup_check
        bot.add_view(commands.build_welcome_view())

        if bot_loaded:
            # on_ready fires again when Discord drops the session and the bot logs in anew, which is
            # likeliest during the daily task. The daily task holds a transaction open on server_configs,
            # so setting up the tables again waits on its lock, and psycopg2 holds the event loop while
            # it waits, so the daily task never gets to commit: the bot hangs until it is restarted.
            # Everything below is already running or loaded from the first login
            await utils.logging(bot, "Reconnected to Discord, so the startup setup was skipped",
                                log_level=log_type.SYSTEM)
            return

        try:
            async with get_db_connection(connection_pool) as connection:
                setup_databases(connection)
                server_classes = server_config_repo.get_server_classes(connection)
                new_server_classes_dict = await events.check_for_new_server_classes(bot, connection)
        except Exception as e:
            await utils.logging(bot, f"Error setting up databases or loading server classes: {e}", log_level=log_type.CRITICAL)
            return

        for key, value in new_server_classes_dict.items():
            server_classes[key] = value
        bot_loaded = True

        await utils.logging(bot, f"Loaded a total of {len(server_classes)} servers")
        await refresh_total_member_count()
        # on_ready fires again after a reconnect, when the rotation is already running
        if not rotate_presence.is_running():
            rotate_presence.start()

        await events.post_wrapped()
        daily_task.start()

        # Ensure commands are registered
        await tree.sync()
        await utils.logging(bot, "Command tree synced", log_level=log_type.SYSTEM)
    except Exception as e:
        await utils.logging(bot, f"Error in on_ready: {e}", log_level=log_type.CRITICAL)

@tasks.loop(hours=24)
async def daily_task():
    await utils.logging(bot, "Running daily task")
    try:
        async with get_db_connection(connection_pool) as connection:
            await events.daily_task(bot, connection, server_classes, dev_test,
                                    borrow_connection=lambda: get_db_connection(connection_pool))

            # Run snapshot work in thread executor to avoid blocking the event loop
            await asyncio.to_thread(monthly_guild_snapshot.run_monthly_snapshot, connection, bot.guilds)

        await utils.logging(bot, f"Daily task completed")
    except Exception as e:
        await utils.logging(bot, f"Error in daily_task: {e}")

    daily_command_cooldowns.clear()
    # Recount once a day, since members joining and leaving servers are not tracked in between
    await refresh_total_member_count()
    await post_api_bot_stats()

async def refresh_total_member_count():
    """
    Count the members across every guild from scratch. The presence rotation shows the new total
    the next time the member count comes round
    """
    global total_member_count
    total_member_count = sum(server.member_count or 0 for server in bot.guilds)

async def adjust_total_member_count(change: int):
    """
    Add a joined server's members to the total, or subtract a removed one's, without recounting.
    The presence is left to the rotation, so a burst of joins does not change it on every one
    :param change: The number of members to add, negative to subtract
    """
    global total_member_count
    total_member_count = max(0, total_member_count + change)

def presence_status(turn: int, member_count: int, month: int = None) -> str:
    """
    The status for a turn of the rotation: the member count on every second turn, and the command
    pointers in order on the turns between
    :param turn: How many statuses have been shown before this one
    :param member_count: The members across every server
    :param month: The month it is, the current one when left out
    """
    pointers = list(messages.PRESENCE_STATUSES)
    # Wrapped is only worth pointing at around the turn of the year, when members look back on it
    if (month or datetime.now(timezone.utc).month) in wrapped_presence_months:
        pointers.append(messages.PRESENCE_WRAPPED)
    # A total of 0 only means Discord has not reported member counts yet, so leave the count out
    # rather than advertise 0 users
    if member_count <= 0:
        return pointers[turn % len(pointers)]
    if turn % 2 == 0:
        return messages.PRESENCE_MEMBER_COUNT.format(members=member_count)
    return pointers[(turn // 2) % len(pointers)]

@tasks.loop(minutes=presence_rotation_minutes)
async def rotate_presence():
    """
    Show the next status, so the member count shares the presence with pointers to the commands
    members can try, /invite among them
    """
    global presence_index
    status = presence_status(presence_index, total_member_count)
    presence_index += 1
    try:
        await bot.change_presence(activity=discord.CustomActivity(name=status))
    except Exception as e:
        # A loop stops for good on an error it does not handle, so a failed change only skips a turn
        await utils.logging(bot, f"Error changing the presence: {e}", validate_for_duplicates=True)

def setup_databases(connection):
    print("Setting up databases...")
    print("Creating server config table...")
    server_config_repo.create_server_config_table(connection)
    print("Creating hall of fame message table...")
    hall_of_fame_message_repo.create_hall_of_fame_message_table(connection)
    print("Creating server user table...")
    server_user_repo.create_server_user_table(connection)
    print("Creating hof wrapped table...")
    hof_wrapped_repo.create_hof_wrapped_table(connection)
    print("Creating hof wrapped guild status table...")
    hof_wrapped_guild_status_repo.create_hof_wrapped_progress_table(connection)
    print("Creating guild lifecycle event table...")
    guild_lifecycle_event_repo.create_guild_lifecycle_event_table(connection)
    print("Creating guild monthly snapshot table...")
    guild_monthly_snapshot_repo.create_guild_monthly_snapshot_table(connection)
    print("Creating hidden global profile table...")
    global_profile_repo.create_hidden_global_profile_table(connection)
    print("Creating opted out member table...")
    opt_out_repo.create_opted_out_member_table(connection)

async def handle_raw_reaction(payload: discord.RawReactionActionEvent, event_name: str):
    """
    Shared handler for reactions being added and removed
    :param payload: The reaction event payload
    :param event_name: The name of the event, used for logging
    """
    if payload.guild_id not in server_classes or (payload.member is not None and payload.member.bot):
        return

    # Reactions on the same message queue up instead of being dropped, so the newest count still wins
    async with message_locks.acquire(payload.message_id):
        try:
            server_class = server_classes[payload.guild_id]

            async with get_db_connection(connection_pool) as connection:
                await events.on_raw_reaction(payload, bot, connection, server_class)
        except Exception as e:
            await utils.logging(bot, f"Error in {event_name}: {e}", payload.guild_id, validate_for_duplicates=True)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """
    The last stop for a command that raised. Without an answer here Discord shows the member
    "The application did not respond", which says nothing about what happened or what to do next
    """
    if isinstance(error, app_commands.NoPrivateMessage):
        content = messages.GUILD_ONLY
    elif isinstance(error, app_commands.TransformerError):
        # A value the command picker would not have let through, such as a number out of range
        content = f"`{error.value}` is not a valid value for this option."
    else:
        content = messages.COMMAND_FAILED
        command_name = interaction.command.name if interaction.command is not None else "unknown"
        original = getattr(error, "original", error)
        await utils.logging(bot, f"Error in /{command_name}: {original}", interaction.guild_id,
                            log_level=log_type.ERROR, validate_for_duplicates=True)

    try:
        await send_error(interaction, content)
    except discord.HTTPException:
        # The interaction expired, so there is nobody left to tell
        pass


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_raw_reaction(payload, "on_raw_reaction_add")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_raw_reaction(payload, "on_raw_reaction_remove")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.guild is None:
        return

    # A ping is how somebody asks an unfamiliar bot what it is, which is most often in a server that
    # has not been set up yet, so it is answered before the check for a configured server below
    if commands.is_bot_mention(message, bot.user):
        server_class = server_classes.get(message.guild.id)
        # A ping in a board members may not post in is about to be deleted, and answering it would
        # leave the bot talking to a message that is no longer there. That only holds when the bot
        # can actually delete it: without Manage Messages the ping stays, and staying silent would
        # mean ignoring it entirely
        in_closed_board = (server_class is not None
                           and message.channel.id == server_class.hall_of_fame_channel_id
                           and not server_class.allow_messages_in_hof_channel)
        will_be_deleted = (in_closed_board
                           and message.channel.permissions_for(message.guild.me).manage_messages)
        if not will_be_deleted:
            try:
                await commands.answer_bot_mention(message, bot.user, server_class)
            except Exception as e:
                await utils.logging(bot, f"Error answering a mention: {e}", message.guild.id,
                                    validate_for_duplicates=True)
            return

    if message.guild.id not in server_classes:
        return

    if message.guild.id == 1180006529575960616 and message.type in (discord.MessageType.new_member, 7):
        welcome_message = f"Welcome to the Hall of Fame support server, {message.author.mention}! Please check out the <#1493561648009580585> channel for getting help with commonly asked questions, otherwise you can just ask away in the chat."
        if message.channel.permissions_for(message.guild.me).send_messages:
            await message.channel.send(welcome_message)
        # Assuming the rest of the code doesn't need to process new member messages for this guild
        return

    try:
        await events.on_message(message, bot, server_classes[message.guild.id])
    except Exception as e:
        await utils.logging(bot, f"Error in on_message: {e}", message.guild.id, validate_for_duplicates=True)

@bot.event
async def on_guild_join(server):
    await utils.logging(bot, "Joined a server", server.id, log_level=log_type.SYSTEM)
    await utils.post_server_perms(bot, server)

    try:
        async with get_db_connection(connection_pool) as connection:
            server_config_repo.insert_server_config(connection, server.id)
            new_server_class = await events.guild_join(server, connection, bot)
            guild_lifecycle_event_repo.insert_guild_lifecycle_event(
                connection, server.id, "JOIN", datetime.now(timezone.utc)
            )
    except Exception as e:
        await utils.logging(bot, f"Error in on_guild_join: {e}", server.id, log_level=log_type.ERROR)
        return

    if new_server_class is None:
        return
    server_classes[server.id] = new_server_class
    await adjust_total_member_count(server.member_count or 0)
    await post_api_bot_stats()

@bot.event
async def on_guild_remove(server):
    # Case where discord sends a guild remove event for a server which has already been removed, or one
    # the bot never set up. The leave is still recorded when the last event is a join, and any data left
    # behind is removed by the daily cleanup
    if server_classes is None or server.id not in server_classes:
        try:
            async with get_db_connection(connection_pool) as connection:
                events.record_guild_leave(connection, server.id, datetime.now(timezone.utc))
        except Exception as e:
            await utils.logging(bot, f"Error recording the leave in on_guild_remove: {e}", server.id,
                                log_level=log_type.ERROR)
        return
    await utils.logging(bot, "Left a server", server.id, log_level=log_type.SYSTEM)
    async with get_db_connection(connection_pool) as connection:
        await events.guild_remove(server, connection)
        guild_lifecycle_event_repo.insert_guild_lifecycle_event(
            connection, server.id, "LEAVE", datetime.now(timezone.utc)
        )
    if server.id in server_classes:
        del server_classes[server.id]
    await adjust_total_member_count(-(server.member_count or 0))
    await post_api_bot_stats()

@tree.command(name="help", description="List of commands")
@user_install
async def get_help(interaction: discord.Interaction):
    await commands.get_help(interaction)
    await utils.logging(bot, f"Help command used in {where_used(interaction)}",
                        interaction.guild_id, log_level=log_type.COMMAND)

@tree.command(name="set_reaction_threshold", description="Configure the amount of reactions needed to post a message in the Hall of Fame")
@app_commands.describe(reaction_threshold=f"Reactions a message needs to reach the Hall of Fame "
                                          f"({validation.REACTION_THRESHOLD_MIN}-{validation.REACTION_THRESHOLD_MAX})")
async def configure_bot(interaction: discord.Interaction,
                        reaction_threshold: app_commands.Range[int, validation.REACTION_THRESHOLD_MIN,
                                                               validation.REACTION_THRESHOLD_MAX]):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    # Refused rather than quietly raised to the minimum, so the member knows what was stored
    error = validation.out_of_range_message("The reaction threshold", reaction_threshold,
                                            validation.REACTION_THRESHOLD_MIN, validation.REACTION_THRESHOLD_MAX)
    if error is not None:
        await send_error(interaction, error)
        return

    server_class = server_classes.get(interaction.guild_id)
    if server_class is None:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return
    if server_class.reaction_threshold == reaction_threshold:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.SETTING_UNCHANGED.format(
            label="The reaction threshold", value=reaction_threshold), ephemeral=True)
        return

    method = commands.calculation_method_labels.get(server_class.reaction_count_calculation_method,
                                                    str(server_class.reaction_count_calculation_method))
    async with get_db_connection(connection_pool) as connection:
        await commands.set_reaction_threshold(interaction, reaction_threshold, connection, method.lower(), server_class)
    await utils.logging(bot, f"Reaction threshold configure command used in a server",
                        interaction.guild.id, reaction_threshold, log_level=log_type.COMMAND)

@tree.command(name="feedback", description="Send feedback to the developer")
@user_install
async def send_feedback(interaction: discord.Interaction):
    refused = feedback_refusal(interaction.user.id)
    if refused:
        await send_error(interaction, refused)
        return
    await utils.create_feedback_form(interaction, bot,
                                     on_sent=lambda user_id: start_daily_cooldown(user_id, "feedback"),
                                     refusal=feedback_refusal)

def feedback_refusal(user_id: int):
    """
    Why a member may not send feedback right now, or None when they may. Asked when the form opens and
    again when it is sent, since several forms can be open at once and each was allowed when it opened
    """
    if daily_uses(user_id, "feedback") >= feedback_daily_limit:
        return messages.FEEDBACK_ON_COOLDOWN.format(limit=feedback_daily_limit)
    return None

@tree.command(name="include_authors_reaction", description="Should the author's own reaction be included in the reaction threshold calculation?")
async def include_author_own_reaction_in_threshold(interaction: discord.Interaction, include: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return
    await update_setting(interaction, "include_author_in_reaction_calculation", include,
                         "Author's own reaction counts toward the threshold")
    await utils.logging(bot, f"Include author's own reaction in threshold command used in a server",
                        interaction.guild.id, include, log_level=log_type.COMMAND)

@tree.command(name="allow_messages_in_hof_channel", description="Should people be allowed to send messages in the Hall of Fame channel?")
async def allow_messages_in_hof_channel(interaction: discord.Interaction, allow: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    note = "" if allow else "Messages members post in the Hall of Fame channel will be removed."
    await update_setting(interaction, "allow_messages_in_hof_channel", allow,
                         "Members can chat in the Hall of Fame channel", note=note)
    await utils.logging(bot, f"Allow messages in Hall of Fame channel command used in a server",
                        interaction.guild.id, allow, log_level=log_type.COMMAND)

@tree.command(name="require_image_or_video", description="Should only messages with images or videos be allowed in the Hall of Fame?")
async def require_image_or_video(interaction: discord.Interaction, require: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    await update_setting(interaction, "require_image_or_video", require,
                         "Only posts with an image or video can reach the Hall of Fame")
    await utils.logging(bot, f"Require image or video command used in a server",
                        interaction.guild.id, str(require), log_level=log_type.COMMAND)

@tree.command(name="vote", description="Vote for the bot on top.gg")
@user_install
async def vote(interaction: discord.Interaction):
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.VOTE_MESSAGE, view=commands.build_vote_view())
    await utils.logging(bot, f"Vote command used in {where_used(interaction)}",
                        interaction.guild_id, log_level=log_type.COMMAND)

@tree.command(name="custom_emoji_check_logic",
              description="Here you can decide if it only should be whitelisted emojis or all emojis")
@discord.app_commands.choices(
    config_option=[
        app_commands.Choice(name="All emojis", value="all_emojis"),
        app_commands.Choice(name="Only whitelisted emojis", value="whitelisted_emojis")
    ]
)
async def custom_emoji_check_logic(interaction: discord.Interaction, config_option: app_commands.Choice[str]):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    custom_emoji_check = config_option.value == "whitelisted_emojis"
    note = ""
    if custom_emoji_check:
        note = (f"Manage the list with {command_refs.WHITELIST_EMOJI}, {command_refs.UNWHITELIST_EMOJI} "
                f"and {command_refs.CLEAR_WHITELIST}.")
        server_class = server_classes.get(interaction.guild_id)
        if server_class is not None and not server_class.whitelisted_emojis:
            note += messages.WHITELIST_EMPTY_NOTE.format(command=command_refs.WHITELIST_EMOJI)

    await update_setting(interaction, "custom_emoji_check_logic", custom_emoji_check,
                         "Emojis that count toward the threshold", shown_value=config_option.name, note=note)
    await utils.logging(bot, f"Custom emoji check logic command used in a server",
                        interaction.guild.id, str(config_option.value), log_level=log_type.COMMAND)


async def get_whitelist_server_class(interaction: discord.Interaction):
    """
    The guards the whitelist commands share
    :return: The server's configuration, or None when the command was turned away
    """
    if not await ensure_bot_is_loaded(interaction):
        return None

    if not await check_if_user_has_manage_server_permission(interaction):
        return None

    server_class = server_classes.get(interaction.guild_id)
    if server_class is None:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return None

    if not server_class.custom_emoji_check_logic:
        await send_error(interaction, messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return None
    return server_class


@tree.command(name="whitelist_emoji", description="Whitelist an emoji for the server if custom emoji check logic is enabled")
@app_commands.describe(emoji="A single emoji, either a standard one or a custom emoji from this server")
async def whitelist_emoji(interaction: discord.Interaction, emoji: str):
    server_class = await get_whitelist_server_class(interaction)
    if server_class is None:
        return

    parsed = validation.normalize_emoji(emoji)
    if parsed is None:
        await send_error(interaction, "No emoji was given.")
        await utils.logging(bot, f"Whitelist emoji command used in a server "
                                 f"with no emoji", interaction.guild.id, emoji, log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        whitelist = server_config_repo.get_parameter_value(connection, interaction.guild_id, "whitelisted_emojis") or []

        if parsed in whitelist:
            await send_error(interaction, messages.WHITELIST_ALREADY_EXISTS.format(emoji=parsed))
        elif len(whitelist) >= validation.WHITELIST_MAX_SIZE:
            await send_error(interaction, messages.WHITELIST_FULL.format(
                limit=validation.WHITELIST_MAX_SIZE, command=command_refs.UNWHITELIST_EMOJI))
        else:
            whitelist.append(parsed)
            server_config_repo.update_server_config_param(interaction.guild_id, "whitelisted_emojis", whitelist, connection)
            server_class.whitelisted_emojis = whitelist
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.WHITELIST_ADDED.format(emoji=parsed, count=len(whitelist)))
    await utils.logging(bot, f"Whitelist emoji command used in a server",
                        interaction.guild.id, parsed, log_level=log_type.COMMAND)


@tree.command(
    name="unwhitelist_emoji",
    description="Unwhitelist an emoji for the server if custom emoji check logic is enabled")
@app_commands.describe(emoji="The whitelisted emoji to remove")
async def unwhitelist_emoji(interaction: discord.Interaction, emoji: str):
    server_class = await get_whitelist_server_class(interaction)
    if server_class is None:
        return

    async with get_db_connection(connection_pool) as connection:
        whitelist = server_config_repo.get_parameter_value(connection, interaction.guild_id, "whitelisted_emojis") or []
        entry = validation.find_in_whitelist(whitelist, emoji)

        if entry is not None:
            whitelist.remove(entry)
            server_config_repo.update_server_config_param(interaction.guild_id, "whitelisted_emojis", whitelist, connection)
            server_class.whitelisted_emojis = whitelist
            content = messages.WHITELIST_REMOVED.format(emoji=entry, count=len(whitelist))
            if not whitelist:
                content += messages.WHITELIST_EMPTY_NOTE.format(command=command_refs.WHITELIST_EMOJI)
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(content)
        else:
            await send_error(interaction, messages.WHITELIST_NOT_FOUND.format(
                emoji=emoji.strip(), command=command_refs.GET_SERVER_CONFIG))
    await utils.logging(bot, f"Unwhitelist emoji command used in a server",
                        interaction.guild.id, emoji, log_level=log_type.COMMAND)


@tree.command(name="clear_whitelist", description="Clear the whitelist for the server if custom emoji check logic is enabled")
async def clear_whitelist(interaction: discord.Interaction):
    server_class = await get_whitelist_server_class(interaction)
    if server_class is None:
        return

    if not server_class.whitelisted_emojis:
        await send_error(interaction, messages.WHITELIST_ALREADY_EMPTY)
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "whitelisted_emojis", [], connection)
    server_class.whitelisted_emojis = []
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.WHITELIST_CLEARED.format(command=command_refs.WHITELIST_EMOJI))
    await utils.logging(bot, f"Clear whitelist command used in a server",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="get_server_config", description="Get the server config")
async def get_server_config(interaction: discord.Interaction):
    if not await ensure_bot_is_loaded(interaction):
        return

    if interaction.guild_id not in server_classes:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    embed = commands.build_server_config_embed(interaction.guild, server_classes[interaction.guild_id])
    # The settings are most often looked up because something is not working, so the check is one press away
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed, view=commands.build_check_setup_view())
    await utils.logging(bot, f"Get server config command used in a server",
                        interaction.guild.id, log_level=log_type.COMMAND)

async def run_setup_check(interaction: discord.Interaction):
    """
    Check everything that can stop messages from reaching the board, and tell the admin how to fix it.
    Shared by /troubleshoot and the Troubleshoot button on the welcome message and /get_server_config. Only the admin sees the
    answer, as it names channels members may not be able to see
    :param interaction: The command or button press to answer
    """
    if not await ensure_bot_is_loaded(interaction):
        return
    if not await check_if_user_has_manage_server_permission(interaction, False):
        return

    guild = interaction.guild
    server_class = server_classes.get(interaction.guild_id)
    if server_class is None:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    # The activity query can outlast the three seconds Discord waits for an answer
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(ephemeral=True)
    try:
        async with get_db_connection(connection_pool) as connection:
            # It counts every post in the server, so a huge board is cut off rather than left to stall the bot
            with utils.statement_timeout(connection, data_command_statement_timeout_ms):
                activity = hall_of_fame_message_repo.get_post_activity(connection, interaction.guild_id)
    except Exception as e:
        # The Troubleshoot button has no command error handler behind it, so the admin is answered here
        await send_error(interaction, messages.COMMAND_FAILED)
        await utils.logging(bot, f"Error reading the post activity for the setup check: {e}", interaction.guild_id,
                            log_level=log_type.ERROR)
        return

    board_channel = guild.get_channel(server_class.hall_of_fame_channel_id)
    findings = setup_check.check_server(guild, board_channel, server_class, activity, utils.daily_post_limit)
    await interaction.followup.send(embed=setup_check.build_embed(findings), ephemeral=True)

    found = setup_check.problems(findings)
    await utils.logging(bot, f"Setup check used in a server: "
                             f"{', '.join(finding.title for finding in found) or 'no problems'}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="troubleshoot", description="Health check and debugging: find what stops messages reaching the Hall of Fame, and how to fix it")
async def troubleshoot(interaction: discord.Interaction):
    await run_setup_check(interaction)

@tree.context_menu(name=messages.WHY_MENU_NAME)
async def why_not_on_board(interaction: discord.Interaction, message: discord.Message):
    """
    Tell whoever asked why one message is or is not on the board. Open to every member, since they are the
    ones wondering, and answered privately, since the answer is of no use to the rest of the channel
    """
    if not await ensure_bot_is_loaded(interaction):
        return
    server_class = server_classes.get(interaction.guild_id)
    if server_class is None:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return
    # Counting unique members costs a request per emoji, so one member cannot keep the bot busy with it
    if not why_cooldown.add_if_absent(interaction.user.id):
        await send_error(interaction, messages.WHY_ON_COOLDOWN)
        return

    # noinspection PyUnresolvedReferences
    await interaction.response.defer(ephemeral=True)
    async with get_db_connection(connection_pool) as connection:
        verdict = await message_check.explain(message, interaction.user.id, bot, connection, server_class)
    await interaction.followup.send(verdict.text, ephemeral=True)

    await utils.logging(bot, f"Why isn't this on the board used in a server: {verdict.reason}",
                        interaction.guild_id, log_level=log_type.COMMAND)

@tree.command(
    name="set_post_due_date",
    description="How many days ago should the post be to be considered old and not valid?")
@app_commands.describe(post_due_date=f"How many days old a message can be and still reach the Hall of Fame "
                                     f"({validation.POST_DUE_DATE_MIN}-{validation.POST_DUE_DATE_MAX})")
async def set_post_due_date(interaction: discord.Interaction,
                            post_due_date: app_commands.Range[int, validation.POST_DUE_DATE_MIN,
                                                              validation.POST_DUE_DATE_MAX]):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    error = validation.out_of_range_message("The post due date", post_due_date,
                                            validation.POST_DUE_DATE_MIN, validation.POST_DUE_DATE_MAX)
    if error is not None:
        await send_error(interaction, error)
        return

    await update_setting(interaction, "post_due_date", post_due_date, "Post due date",
                         shown_value=f"{post_due_date} day{plural(post_due_date)}",
                         note=messages.POST_DUE_DATE_NOTE.format(days=post_due_date, plural=plural(post_due_date)))
    await utils.logging(bot, f"Set post due date command used in a server",
                        interaction.guild.id, post_due_date, log_level=log_type.COMMAND)

@tree.command(name="invite", description="Invite the bot to your server")
@user_install
async def invite(interaction: discord.Interaction):
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.INVITE_MESSAGE, view=commands.build_invite_view())
    await utils.logging(bot, f"Invite command used in {where_used(interaction)}",
                        interaction.guild_id, log_level=log_type.COMMAND)

@tree.command(name="ignore_bot_messages", description="Should the bot ignore messages from other bots?")
async def ignore_bot_messages(interaction: discord.Interaction, should_ignore_bot_messages: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    await update_setting(interaction, "ignore_bot_messages", should_ignore_bot_messages,
                         "Ignore messages from bots")
    await utils.logging(bot, f"Ignore bot messages command used in a server",
                        interaction.guild.id, should_ignore_bot_messages, log_level=log_type.COMMAND)

@tree.command(name="calculation_method", description="Set the calculation method for reactions")
@discord.app_commands.choices(
    method=[
        app_commands.Choice(name="reaction_count = Most reactions on an emoji (default, recommended)", value=calculation_method_type.MOST_REACTIONS_ON_EMOJI),
        app_commands.Choice(name="reaction_count = Total reactions", value=calculation_method_type.TOTAL_REACTIONS),
        app_commands.Choice(name="reaction_count = How many users reacted", value=calculation_method_type.UNIQUE_USERS)
    ]
)
async def calculation_method(interaction: discord.Interaction, method: app_commands.Choice[str]):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    label = commands.calculation_method_labels.get(method.value, method.name)
    await update_setting(interaction, "reaction_count_calculation_method", method.value,
                         "Reactions are counted as", shown_value=label)
    await utils.logging(bot, f"Calculation method command used in a server",
                        interaction.guild.id, method.value, log_level=log_type.COMMAND)

@tree.command(name="hide_hof_post_below_threshold", description="Should hall of fame posts be hidden when they go below the reaction threshold?")
async def hide_hall_of_fame_posts_when_they_are_below_threshold(interaction: discord.Interaction, hide: bool):
    """
    Hide hall of fame posts when they are below the threshold
    :param interaction:
    :param hide: True to hide, False to not hide
    :return:
    """
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    note = "They show again once they are back above it." if hide else ""
    await update_setting(interaction, "hide_hof_post_below_threshold", hide,
                         "Hide Hall of Fame posts that drop below the threshold", note=note)
    await utils.logging(bot, f"Hide hall of fame posts command used in a server",
                        interaction.guild.id, str(hide), log_level=log_type.COMMAND)

@tree.command(name="user_profile", description="Get the server profile of a user")
@user_install
@app_commands.describe(specific_user="The member to look up, yourself when left out. Only yourself outside "
                                     "servers with Hall of Fame")
async def user_server_profile(interaction: discord.Interaction, specific_user: discord.User = None):
    """
    Get the server profile of a user, with their totals across every server at the bottom unless
    they hid them
    :param interaction: The interaction object
    :param specific_user: The user to get the profile of, defaults to the interaction user
    :return: The server profile of the user
    """
    if not await ensure_bot_is_loaded(interaction):
        return
    if await refuse_in_closed_board(interaction):
        return

    user = specific_user or interaction.user
    if getattr(user, "bot", False):
        await send_error(interaction, messages.PROFILE_BOT_USER)
        return

    if not set_up_here(interaction):
        await answer_profile_outside_server(interaction, user)
        return

    # Answered first, since the badges and highlights below read every post in the server and can
    # outlast the three seconds Discord waits for an answer
    # noinspection PyUnresolvedReferences
    await interaction.response.defer()
    async with get_db_connection(connection_pool) as connection:
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            user_stats = server_user_repo.get_server_user(connection, user.id, interaction.guild_id)
            # The profile is posted in the channel, so a member who hid their totals has them left out
            # even when they look themselves up
            global_profile = (None if global_profile_repo.is_hidden(connection, user.id)
                              else global_profile_repo.get_global_profile(connection, user.id, interaction.guild_id))

    # A member featured only in other servers still has a card worth showing: zeros for this
    # server, and their totals across servers below
    if user_stats is None and not commands.global_profile_adds_something(global_profile):
        await interaction.followup.send(messages.PROFILE_NO_DATA)
        await utils.logging(bot, f"User server profile command used in a server but no data available for the member looked up",
                            interaction.guild.id, log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        # The badges and highlights read every post in the server, so a big one is cut off rather
        # than left to stall the bot
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            await commands.user_server_profile(interaction, user, user_stats, connection, month_emoji,
                                               all_time_emoji, global_profile)
    await utils.logging(bot, f"Get user server profile command used in a server",
                        interaction.guild.id, log_level=log_type.COMMAND)

async def answer_profile_outside_server(interaction: discord.Interaction, user):
    """
    /user_profile through a user install, in a DM or a server without Hall of Fame. There is no server to
    show standings for, so the card has the member's totals across servers alone, and only when they
    have not hidden them.

    Only the member who asked can be looked up here. Inside a server with the bot, profiles show what
    that server's own board and leaderboard already show. Outside one, a lookup would carry someone's
    totals into a DM or a server that never added the bot, which the member never agreed to
    """
    if user.id != interaction.user.id:
        await send_error(interaction, messages.PROFILE_OTHERS_OUTSIDE_SERVER.format(command=command_refs.USER_PROFILE))
        await utils.logging(bot, f"User profile command used in {where_used(interaction)} for another member, "
                                 f"refused outside a server with the bot", interaction.guild_id,
                            log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            hidden = global_profile_repo.is_hidden(connection, user.id)
            global_profile = None if hidden else global_profile_repo.get_global_profile(connection, user.id)

    if hidden:
        await send_error(interaction, messages.PROFILE_HIDDEN_OUTSIDE_SERVER_SELF.format(
            command=command_refs.MY_DATA))
    elif not global_profile["posts"]:
        await send_error(interaction, messages.PROFILE_NOTHING_OUTSIDE_SERVER)
    else:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(embed=commands.build_global_profile_embed(user, global_profile))
    await utils.logging(bot, f"User profile command used in {where_used(interaction)}, outside a server with the bot",
                        interaction.guild_id, log_level=log_type.COMMAND)


@tree.command(name="count_in_global_profiles", description="Should posts in this server count toward members' totals across servers?")
@app_commands.describe(count="Whether members' totals across servers include their posts from this server")
async def count_in_global_profiles(interaction: discord.Interaction, count: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    note = messages.GLOBAL_PROFILE_COUNTING_ON_NOTE if count else messages.GLOBAL_PROFILE_COUNTING_OFF_NOTE
    await update_setting(interaction, "count_in_global_profiles", count,
                         "Posts here count toward members' totals across servers", note=note)
    await utils.logging(bot, f"Count in global profiles command used in a server",
                        interaction.guild.id, str(count), log_level=log_type.COMMAND)


def on_daily_cooldown(user_id: int, command_name: str) -> bool:
    return command_name in daily_command_cooldowns.get(user_id, [])


def daily_uses(user_id: int, command_name: str) -> int:
    """How many times a member used a command since the daily task last cleared the cooldowns"""
    return daily_command_cooldowns.get(user_id, []).count(command_name)


def start_daily_cooldown(user_id: int, command_name: str):
    daily_command_cooldowns.setdefault(user_id, []).append(command_name)


async def read_my_data_summary(user_id: int) -> dict:
    """
    What /my_data shows before any button is pressed: counts and the member's two choices. Counting is
    cheap, so the command answers at once, and the full rows are only read for the Download button
    """
    async with get_db_connection(connection_pool) as connection:
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            return {
                "posts": hall_of_fame_message_repo.count_messages_by_author(connection, user_id),
                "servers": server_user_repo.count_server_users_for_user(connection, user_id),
                "wrapped": hof_wrapped_repo.count_hof_wrapped_for_user(connection, user_id),
                "hidden_since": global_profile_repo.hidden_since(connection, user_id),
                "opted_out_since": opt_out_repo.opted_out_since(connection, user_id),
            }


async def read_my_data_document(user_id: int) -> dict:
    """Every row stored about a member, for the files the Download button sends"""
    async with get_db_connection(connection_pool) as connection:
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            posts = hall_of_fame_message_repo.get_messages_by_author(connection, user_id)
            standings = server_user_repo.get_server_users_for_user(connection, user_id)
            wrapped = hof_wrapped_repo.get_hof_wrapped_for_user(connection, user_id)
            hidden = global_profile_repo.is_hidden(connection, user_id)
            not_featured = opt_out_repo.is_opted_out(connection, user_id)
    return commands.build_my_data_document(user_id, posts, standings, wrapped, hidden, not_featured)


async def delete_member_data(user_id: int) -> int:
    """
    Remove a member from everything the bot stores: their posts lose their author, and their
    statistics, Wrapped rows, place in other members' Wrapped, hidden-totals choice and choice not to
    be featured are deleted. Without the last, new messages of theirs can be featured again, which the
    confirmation says and the done message offers to stop
    :param user_id: The member's user ID
    :return: How many posts were detached from them
    """
    async with get_db_connection(connection_pool) as connection:
        # One transaction, committed by statement_timeout once every step worked. A step that fails
        # rolls back the rest, so a member is never left with only part of their data deleted
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            # The posts before the statistics: the daily rebuild recreates server_user from them, so
            # deleting the statistics alone would undo itself overnight
            detached = hall_of_fame_message_repo.remove_author(connection, user_id, commit=False)
            server_user_repo.delete_server_users_for_user(connection, user_id, commit=False)
            hof_wrapped_repo.delete_hof_wrapped_for_user(connection, user_id, commit=False)
            global_profile_repo.delete_for_user(connection, user_id, commit=False)
            opt_out_repo.set_opted_out(connection, user_id, False, commit=False)
    return detached


async def stop_featuring_member(user_id: int):
    """
    Record that a member asked not to be featured, and take them out of everybody's stored Wrapped fan
    lists in the same transaction, so other members' Wrapped stop showing them, including Wrapped from
    before they asked. Their own earlier Wrapped stays, like the rest of their earlier data
    :param user_id: The member's user ID
    """
    async with get_db_connection(connection_pool) as connection:
        # The fan lists are searched across the whole table, so the database cuts a slow search off
        with utils.statement_timeout(connection, data_command_statement_timeout_ms):
            opt_out_repo.set_opted_out(connection, user_id, True, commit=False)
            hof_wrapped_repo.remove_from_fan_lists(connection, user_id, commit=False)


@tree.command(name="my_data", description="See, download or delete what Hall of Fame stores about you")
@user_install
async def my_data(interaction: discord.Interaction):
    """
    The one place a member manages their data: a private summary of what is stored, with buttons to
    download it, hide or show their totals across servers, and delete it or be featured again
    """
    if not await ensure_bot_is_loaded(interaction):
        return

    user_id = interaction.user.id
    # noinspection PyUnresolvedReferences
    await interaction.response.defer(ephemeral=True)
    summary = await read_my_data_summary(user_id)

    async def download(button_interaction: discord.Interaction, _view):
        # The export reads every row stored about the member, so it is the part limited to once a day
        if on_daily_cooldown(user_id, "my_data"):
            # noinspection PyUnresolvedReferences
            await button_interaction.response.send_message(messages.MY_DATA_DOWNLOAD_ON_COOLDOWN, ephemeral=True)
            return
        # noinspection PyUnresolvedReferences
        await button_interaction.response.defer(ephemeral=True, thinking=True)
        try:
            document = await read_my_data_document(user_id)
        except Exception as e:
            await button_interaction.followup.send(messages.COMMAND_FAILED, ephemeral=True)
            await utils.logging(bot, f"Error reading a member's data export: {e}", interaction.guild_id,
                                log_level=log_type.ERROR)
            return

        whole = commands.encode_export(document)
        try:
            # One file is always tried first, so Discord's own limit decides whether it fits
            await button_interaction.followup.send(
                messages.MY_DATA_EXPORT, ephemeral=True,
                files=[discord.File(io.BytesIO(whole), filename="hall-of-fame-my-data.json")])
            parts = 1
        except discord.HTTPException as e:
            if not commands.is_file_too_large(e):
                await send_export_failed(button_interaction, f"Discord refused a member's data export: {e}")
                return
            parts = await send_export_in_parts(button_interaction, document, len(whole))
            if parts is None:
                return
        # Only once it worked, so a failed attempt does not lock the member out for the day
        start_daily_cooldown(user_id, "my_data")
        await utils.logging(bot, f"A member downloaded their data in {where_used(interaction)}"
                                 + (f", split into {parts} files after Discord refused one" if parts > 1 else ""),
                            interaction.guild_id, log_level=log_type.COMMAND)

    async def send_export_failed(button_interaction: discord.Interaction, log_message: str):
        # Whatever was sent stays, but the day is not used up, so the member can try again
        await button_interaction.followup.send(messages.MY_DATA_EXPORT_SEND_FAILED, ephemeral=True)
        await utils.logging(bot, log_message, interaction.guild_id, log_level=log_type.ERROR)

    async def send_export_in_parts(button_interaction: discord.Interaction, document: dict, refused_bytes: int):
        """
        Send the export as several complete JSON files after Discord refused it as one. Discord's limit is
        not known, so when it refuses the first message for its size too, the parts are halved again,
        until they fit or a single row or the number of messages makes it impossible
        :return: How many files were sent, or None when it could not be sent, which is answered here
        """
        budget = commands.split_budget(refused_bytes)
        while True:
            try:
                files = commands.split_my_data_export(document, max_bytes=budget)
                batches = commands.batch_export_files(files, max_bytes=budget)
                if len(batches) > commands.export_max_messages(button_interaction):
                    raise commands.ExportTooLarge(f"{len(files)} files in {len(batches)} messages")
            except commands.ExportTooLarge as e:
                await button_interaction.followup.send(messages.MY_DATA_EXPORT_TOO_LARGE, ephemeral=True)
                await utils.logging(bot, f"A member's data export is too large to send through Discord: {e}",
                                    interaction.guild_id, log_level=log_type.ERROR)
                return None

            names = [f"hall-of-fame-my-data-part-{number}-of-{len(files)}.json"
                     for number in range(1, len(files) + 1)]
            sent = 0
            try:
                for batch in batches:
                    await button_interaction.followup.send(
                        messages.MY_DATA_EXPORT_PARTS.format(parts=len(files)) if sent == 0 else None,
                        ephemeral=True,
                        files=[discord.File(io.BytesIO(files[index]), filename=names[index]) for index in batch])
                    sent += 1
            except discord.HTTPException as e:
                # Smaller parts only help before anything went out. Once some parts are sent, sending them
                # all again would leave the member with two sets that do not match
                if commands.is_file_too_large(e) and sent == 0:
                    budget //= 2
                    continue
                await send_export_failed(button_interaction,
                                         f"Discord refused a member's data export split into {len(files)} files: {e}")
                return None
            return len(files)

    async def toggle_totals(button_interaction: discord.Interaction, view):
        hide = view.summary["hidden_since"] is None
        # Answered first, since the summary is read twice around the change, which can outlast the three
        # seconds Discord waits for a button to be answered
        # noinspection PyUnresolvedReferences
        await button_interaction.response.defer()
        try:
            # A /my_data opened earlier can still show this button to a member who since has no totals,
            # and storing the choice then would keep data about them for nothing
            stored = commands.has_totals(await read_my_data_summary(user_id))
            if stored:
                async with get_db_connection(connection_pool) as connection:
                    global_profile_repo.set_hidden(connection, user_id, hide)
            # Read again rather than patched, so a /my_data opened before the member deleted their data or
            # opted out shows what is stored now
            view.summary = await read_my_data_summary(user_id)
        except Exception as e:
            await button_interaction.edit_original_response(content=messages.COMMAND_FAILED, view=None)
            await utils.logging(bot, f"Error changing whether a member's totals are hidden: {e}",
                                interaction.guild_id, log_level=log_type.ERROR)
            return
        view.refresh()
        await button_interaction.edit_original_response(content=commands.my_data_summary(view.summary), view=view)
        if stored:
            await utils.logging(bot, f"A member {'hid' if hide else 'showed'} their totals across servers",
                                interaction.guild_id, log_level=log_type.COMMAND)

    async def delete(button_interaction: discord.Interaction, view):
        # Answered first, since the summary is read again below
        # noinspection PyUnresolvedReferences
        await button_interaction.response.defer()
        try:
            # Read again rather than taken from the panel, which may have been opened before the member
            # opted out from another /my_data, so the confirmation always warns when that choice goes too
            summary = await read_my_data_summary(user_id)
        except Exception as e:
            view.finished = True
            view.stop()
            await button_interaction.edit_original_response(content=messages.COMMAND_FAILED, view=None)
            await utils.logging(bot, f"Error reading a member's data before deleting it: {e}", interaction.guild_id,
                                log_level=log_type.ERROR)
            return
        # Limited because a deletion scans every table for the member. With no rows stored there is
        # nothing to scan, so a member who just deleted can still come back and stop being featured
        if commands.has_stored_rows(summary) and on_daily_cooldown(user_id, "delete_my_data"):
            await button_interaction.followup.send(messages.MY_DATA_DELETE_ON_COOLDOWN, ephemeral=True)
            return
        # The summary gives way to the confirmation, so its own buttons stop here
        view.finished = True
        view.stop()
        confirm_view = commands.ConfirmDeleteView(user_id, confirmed)
        confirm_view.original_interaction = interaction
        content = messages.DELETE_MY_DATA_CONFIRM
        if summary["opted_out_since"]:
            # Deleting everything includes the record that keeps their messages off the boards
            content += " " + messages.DELETE_MY_DATA_CONFIRM_OPT_OUT
        await button_interaction.edit_original_response(content=content, view=confirm_view)

    async def toggle_featuring(button_interaction: discord.Interaction, view):
        stop = view.summary["opted_out_since"] is None
        # Answered first, since stopping searches every stored Wrapped and can outlast the three seconds
        # Discord waits for a button to be answered
        # noinspection PyUnresolvedReferences
        await button_interaction.response.defer()
        try:
            if stop:
                await stop_featuring_member(user_id)
            else:
                async with get_db_connection(connection_pool) as connection:
                    opt_out_repo.set_opted_out(connection, user_id, False)
        except Exception as e:
            await button_interaction.edit_original_response(content=messages.COMMAND_FAILED, view=None)
            await utils.logging(bot, f"Error changing whether a member is featured: {e}", interaction.guild_id,
                                log_level=log_type.ERROR)
            return
        note = messages.STOPPED_FEATURING if stop else messages.COUNTED_AGAIN
        try:
            view.summary = await read_my_data_summary(user_id)
        except Exception as e:
            # The change is stored, so the member hears that it worked, and the panel goes rather than
            # being left showing the old choice
            view.finished = True
            view.stop()
            await button_interaction.edit_original_response(content=note, view=None)
            await utils.logging(bot, f"Error reading a member's data after changing whether they are featured: {e}",
                                interaction.guild_id, log_level=log_type.ERROR)
            return
        view.refresh()
        await button_interaction.edit_original_response(
            content=commands.my_data_summary(view.summary, note=note), view=view)
        await utils.logging(bot, "A member asked not to be featured" if stop else "A member asked to be featured again",
                            interaction.guild_id, log_level=log_type.COMMAND)

    async def confirmed(button_interaction: discord.Interaction):
        # Answered before the deletes run, since they can take longer than the three seconds Discord
        # waits for a button to be answered
        # noinspection PyUnresolvedReferences
        await button_interaction.response.defer()
        try:
            detached = await delete_member_data(user_id)
        except Exception as e:
            # Nothing was deleted, since the deletes run in one transaction, so no cooldown is started
            await button_interaction.edit_original_response(content=messages.COMMAND_FAILED, view=None)
            await utils.logging(bot, f"Error deleting a member's data: {e}", interaction.guild_id,
                                log_level=log_type.ERROR)
            return
        start_daily_cooldown(user_id, "delete_my_data")
        offer = commands.StopFeaturingView(user_id, stop_featuring)
        offer.original_interaction = button_interaction
        await button_interaction.edit_original_response(
            content=messages.DELETE_MY_DATA_DONE.format(command=command_refs.MY_DATA), view=offer)
        # No name in the log: the member has just asked to be forgotten
        await utils.logging(bot, f"A member deleted their data, detaching {detached} post{plural(detached)}",
                            interaction.guild_id, log_level=log_type.COMMAND)

    async def stop_featuring(button_interaction: discord.Interaction):
        # The same setting as the button on /my_data, offered where a member who just deleted their
        # data is likeliest to want it
        # noinspection PyUnresolvedReferences
        await button_interaction.response.defer()
        try:
            await stop_featuring_member(user_id)
        except Exception as e:
            await button_interaction.edit_original_response(content=messages.COMMAND_FAILED, view=None)
            await utils.logging(bot, f"Error changing whether a member is featured: {e}", interaction.guild_id,
                                log_level=log_type.ERROR)
            return
        await button_interaction.edit_original_response(
            content=messages.DELETE_MY_DATA_DONE_STOPPED.format(command=command_refs.MY_DATA), view=None)
        await utils.logging(bot, "A member asked not to be featured", interaction.guild_id,
                            log_level=log_type.COMMAND)

    view = commands.MyDataView(user_id, summary, download, toggle_totals, toggle_featuring, delete)
    view.original_interaction = interaction
    await interaction.followup.send(commands.my_data_summary(summary), view=view, ephemeral=True)
    await utils.logging(bot, f"My data command used in {where_used(interaction)}", interaction.guild_id,
                        log_level=log_type.COMMAND)


@tree.command(name="leaderboard", description="Get the server leaderboard")
async def leaderboard(interaction: discord.Interaction):
    """
    Get the server leaderboard
    :param interaction: The interaction object
    :return: The server stats
    """
    if not await ensure_bot_is_loaded(interaction):
        return
    if await refuse_in_closed_board(interaction):
        return

    if interaction.guild_id not in server_classes:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    if on_daily_cooldown(interaction.user.id, "leaderboard"):
        await send_error(interaction, messages.COMMAND_ON_COOLDOWN)
        await utils.logging(bot, f"Leaderboard command on cooldown in a server",
                            interaction.guild.id, log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        try:
            await commands.server_leaderboard(interaction, connection, month_emoji, all_time_emoji)
        except Exception as e:
            await utils.logging(bot, f"Error in leaderboard command: {e}", interaction.guild_id)
            # The command was deferred, so without this the member is left watching it think forever
            await send_error(interaction, messages.COMMAND_FAILED)
            return

    # Only put the command on cooldown once it actually produced a leaderboard
    start_daily_cooldown(interaction.user.id, "leaderboard")

    await utils.logging(bot, f"Leaderboard command used in a server",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="set_hall_of_fame_channel", description="Manually set the Hall of Fame channel for the server")
@app_commands.describe(channel="The text channel Hall of Fame posts go to")
async def set_hall_of_fame_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """
    Set the Hall of Fame channel for the server
    :param interaction: The interaction object
    :param channel: The channel to set as the Hall of Fame channel
    """
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction, False):
        return

    permissions = channel.permissions_for(interaction.guild.me)
    required_permissions = [
        ("View Channel", permissions.view_channel),
        ("Send Messages", permissions.send_messages),
        ("Read Message History", permissions.read_message_history),
        # Every Hall of Fame post is an embed, and without this Discord drops it without an error
        ("Embed Links", permissions.embed_links),
    ]
    missing_permissions = [name for name, granted in required_permissions if not granted]
    if missing_permissions:
        await send_error(interaction, messages.HOF_CHANNEL_MISSING_PERMISSIONS.format(
            channel=channel.mention, missing_permissions=", ".join(missing_permissions)))
        await utils.logging(bot, f"Failed to set the Hall of Fame channel, "
                                 f"with missing permissions: {', '.join(missing_permissions)}",
                                 interaction.guild.id, str(channel.id), log_level=log_type.COMMAND)
        return

    server_class = server_classes.get(interaction.guild_id)
    if server_class is not None and server_class.hall_of_fame_channel_id == channel.id:
        await send_error(interaction, messages.HOF_CHANNEL_UNCHANGED.format(channel=channel.mention))
        return

    # Setting a server up for the first time posts in the channel, which can outlast the three
    # seconds Discord waits for an answer
    # noinspection PyUnresolvedReferences
    await interaction.response.defer()

    async with get_db_connection(connection_pool) as connection:
        needs_setup = (server_class is None
                       or server_config_repo.check_if_guild_exists(connection, interaction.guild_id) is False)
        if needs_setup:
            new_server_class = await events.guild_join(interaction.guild, connection, bot, channel)
            if new_server_class is None:
                await send_error(interaction, messages.HOF_CHANNEL_SETUP_FAILED.format(channel=channel.mention))
                return
            server_classes[interaction.guild_id] = new_server_class

        server_config_repo.update_server_config_param(interaction.guild_id, "hall_of_fame_channel_id", channel.id, connection)
        if not needs_setup:
            # Only once it is stored, so a failed write does not leave reactions posting to a channel
            # the saved configuration does not know about
            server_class.hall_of_fame_channel_id = channel.id

    if needs_setup:
        # Setting the server up already posted its welcome message in the channel
        await interaction.followup.send(messages.HOF_CHANNEL_SET.format(channel=channel.mention))
        return

    try:
        await channel.send(messages.HOF_CHANNEL_MOVED_ANNOUNCEMENT.format(
            user=interaction.user.mention, threshold=server_class.reaction_threshold,
            threshold_command=command_refs.SET_REACTION_THRESHOLD, config_command=command_refs.GET_SERVER_CONFIG),
            allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        # The board has moved either way, so the member still hears that it worked
        await utils.logging(bot, f"Could not post the Hall of Fame channel announcement: {e}",
                            interaction.guild.id, str(channel.id), log_level=log_type.COMMAND)
        await interaction.followup.send(messages.HOF_CHANNEL_SET_ANNOUNCEMENT_FAILED.format(channel=channel.mention))
        return

    await interaction.followup.send(messages.HOF_CHANNEL_SET.format(channel=channel.mention))
    await utils.logging(bot, f"Set Hall of Fame channel command used in a server",
                        interaction.guild.id, str(channel.id), log_level=log_type.COMMAND)

@tree.command(name="hof_wrapped", description="Get your Hall of Fame Wrapped for the year")
async def hof_wrapped_command(interaction: discord.Interaction):
    if not await ensure_bot_is_loaded(interaction):
        return
    if await refuse_in_closed_board(interaction):
        return

    if not (interaction.guild_id in server_classes and server_classes[interaction.guild_id] is not None):
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    async with get_db_connection(connection_pool) as connection:
        user_wrapped = hof_wrapped_repo.get_hof_wrapped(connection, interaction.guild_id, interaction.user.id, version.WRAPPED_YEAR)
    if user_wrapped is None:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(f"No Hall of Fame Wrapped data available for you in {version.WRAPPED_YEAR}. Participate more in Hall of Fame to get your wrapped next year!")
        await utils.logging(bot, f"HOF Wrapped command used in a server but no data available",
                            interaction.guild.id, log_level=log_type.COMMAND)
        return

    embed = await hof_wrapped.create_embed(interaction.user, user_wrapped, bot)
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed)

    await utils.logging(bot, f"HOF Wrapped command used in a server",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="server_hof_wrapped", description="Get the server's Hall of Fame Wrapped for the year")
async def server_hof_wrapped_command(interaction: discord.Interaction):
    if not await ensure_bot_is_loaded(interaction):
        return
    if await refuse_in_closed_board(interaction):
        return

    if not (interaction.guild_id in server_classes and server_classes[interaction.guild_id] is not None):
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    async with get_db_connection(connection_pool) as connection:
        if not hof_wrapped_repo.check_if_guild_wrapped_data_exists(connection, interaction.guild_id, version.WRAPPED_YEAR):
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(f"No Hall of Fame Wrapped data available for {version.WRAPPED_YEAR}. The bot will start collecting data for next year's wrapped!")
            return
        all_users_wrapped = hof_wrapped_repo.get_all_hof_wrapped_for_guild(connection, interaction.guild_id,  version.WRAPPED_YEAR)
    embed = hof_wrapped.create_server_embed(interaction.guild, all_users_wrapped)
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed, view=commands.build_server_wrapped_view())


async def check_if_user_has_manage_server_permission(interaction: discord.Interaction, check_server_set_up: bool = True):
    """
    Check if the user has manage server permission
    :param interaction:
    :param check_server_set_up: Whether to check if the server is set up
    :return: True if the user has manage server permission
    """
    if not interaction.user.guild_permissions.manage_guild:
        await send_error(interaction, messages.NOT_AUTHORIZED)
        await utils.logging(bot, "A member without the Manage Server permission was refused",
                            interaction.guild_id, log_level=log_type.COMMAND)
        return False
    if check_server_set_up and len(server_classes) > 1 and (interaction.guild_id not in server_classes or server_classes[interaction.guild_id] is None):
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return False
    return True

async def post_api_bot_stats():
    """
    Post the bot stats to the API services
    """
    if dev_test:
        return

    try:
        topgg_response = topgg_api.post_bot_stats(len(bot.guilds), topgg_api_key)
        await utils.logging(bot, f"Posted bot stats to top.gg: {topgg_response[0]} - {topgg_response[1]}")
    except Exception as e:
        await utils.logging(bot, f"Failed to post bot stats to top.gg: {e}")

    try:
        discordbotlist_response = discordbotlist_api.post_bot_stats(len(bot.guilds))
        await utils.logging(bot, f"Posted bot stats to discordbotlist.com: {discordbotlist_response[0]} - {discordbotlist_response[1]}")
    except Exception as e:
        await utils.logging(bot, f"Failed to post bot stats to discordbotlist.com: {e}")

if __name__ == "__main__":
    import time
    if TOKEN is None:
        raise ValueError("TOKEN environment variable is not set in the .env file")
    connection_pool = create_connection_pool()
    while True:
        # Every run gets a new event loop, and a semaphore or lock that has ever had to make a caller
        # wait stays bound to the loop it waited on. Reusing one after a restart would raise instead
        # of wait, so both are made fresh for each run
        connection_slots = asyncio.Semaphore(database_pool_size)
        message_locks = concurrency.KeyedLocks()
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"[ERROR] Bot crashed with exception: {e}. Restarting in 5 seconds...")
            import traceback
            traceback.print_exc()
            time.sleep(5)
        else:
            break
    connection_pool.closeall()
