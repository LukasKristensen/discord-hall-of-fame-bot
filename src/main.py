from datetime import datetime, timezone
import discord
from discord import app_commands
from discord.ext import commands as discord_commands
from discord.ext import tasks
from dotenv import load_dotenv
import commands
import concurrency
import environment
import events
import utils
import validation
from constants import version
from enums import command_refs, log_type, calculation_method_type
from classes.bot_stats import BotStats
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
)
import hof_wrapped
from contextlib import asynccontextmanager
from scripts import monthly_guild_snapshot
import asyncio

load_dotenv()
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
    prefix = "_LOCAL" if dev_test else ""
    return psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=database_pool_size,
        host=os.getenv(f'POSTGRES_HOST{prefix}'),
        database=os.getenv(f'POSTGRES_DB{prefix}'),
        user=os.getenv(f'POSTGRES_USER{prefix}'),
        password=os.getenv(f'POSTGRES_PASSWORD{prefix}'))

message_locks = concurrency.KeyedLocks()
daily_command_cooldowns = {}

intents = discord.Intents.default()
intents.message_content = True
# Every command works on a server's configuration or its members, so none of them is offered in DMs,
# where they could only fail
bot = discord_commands.Bot(command_prefix="/", intents=intents,
                           allowed_contexts=app_commands.AppCommandContext(guild=True))
tree = bot.tree
server_classes = {}
bot_stats = BotStats()

month_emoji = "<:month_most_hof_messages:1380272332609683517>" if not dev_test else "<:month_most_hof_messages:1380272983368532160>"
all_time_emoji = "<:all_time_most_hof_messages:1380272422842007622>" if not dev_test else "<:all_time_most_hof_messages:1380272953098244166>"

bot_loaded = False


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
            await utils.logging(bot, f"Database error: {e}", log_level=log_type.CRITICAL)
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
        await bot.change_presence(activity=discord.CustomActivity(name=f'🏆 Hall of Fame - {sum(server.member_count for server in bot.guilds)} users', type=5))

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
    total_server_members = sum(server.member_count for server in bot.guilds)
    await bot.change_presence(activity=discord.CustomActivity(name=f'🏆 Hall of Fame - {total_server_members} users', type=5))
    await post_api_bot_stats()

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
    await utils.logging(bot, f"Joined server {server.name}", server.id, log_level=log_type.SYSTEM)
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
    await post_api_bot_stats()

@bot.event
async def on_guild_remove(server):
    # Case where discord sends a guild remove event for a server which has already been removed
    if server_classes is None or server.id not in server_classes:
        return
    await utils.logging(bot, f"Left server {server.name}", server.id, log_level=log_type.SYSTEM)
    async with get_db_connection(connection_pool) as connection:
        await events.guild_remove(server, connection)
        guild_lifecycle_event_repo.insert_guild_lifecycle_event(
            connection, server.id, "LEAVE", datetime.now(timezone.utc)
        )
    if server.id in server_classes:
        del server_classes[server.id]
    await post_api_bot_stats()

@tree.command(name="help", description="List of commands")
async def get_help(interaction: discord.Interaction):
    await commands.get_help(interaction)
    await utils.logging(bot, f"Help command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

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
    await utils.logging(bot, f"Reaction threshold configure command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, reaction_threshold, log_level=log_type.COMMAND)

@tree.command(name="feedback", description="Send feedback to the developer")
async def send_feedback(interaction: discord.Interaction):
    await utils.create_feedback_form(interaction, bot)

@tree.command(name="include_authors_reaction", description="Should the author's own reaction be included in the reaction threshold calculation?")
async def include_author_own_reaction_in_threshold(interaction: discord.Interaction, include: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return
    await update_setting(interaction, "include_author_in_reaction_calculation", include,
                         "Author's own reaction counts toward the threshold")
    await utils.logging(bot, f"Include author's own reaction in threshold command used by {interaction.user.name} in {interaction.guild.name}",
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
    await utils.logging(bot, f"Allow messages in Hall of Fame channel command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, allow, log_level=log_type.COMMAND)

@tree.command(name="require_image_or_video", description="Should only messages with images or videos be allowed in the Hall of Fame?")
async def require_image_or_video(interaction: discord.Interaction, require: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    await update_setting(interaction, "require_image_or_video", require,
                         "Only posts with an image or video can reach the Hall of Fame")
    await utils.logging(bot, f"Require image or video command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(require), log_level=log_type.COMMAND)

@tree.command(name="vote", description="Vote for the bot on top.gg")
async def vote(interaction: discord.Interaction):
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.VOTE_MESSAGE)
    await utils.logging(bot, f"Vote command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

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
    await utils.logging(bot, f"Custom emoji check logic command used by {interaction.user.name} in {interaction.guild.name}",
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
        await utils.logging(bot, f"Whitelist emoji command used by {interaction.user.name} in {interaction.guild.name} "
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
    await utils.logging(bot, f"Whitelist emoji command used by {interaction.user.name} in {interaction.guild.name}",
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
    await utils.logging(bot, f"Unwhitelist emoji command used by {interaction.user.name} in {interaction.guild.name}",
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
    await utils.logging(bot, f"Clear whitelist command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="get_server_config", description="Get the server config")
async def get_server_config(interaction: discord.Interaction):
    if not await ensure_bot_is_loaded(interaction):
        return

    if interaction.guild_id not in server_classes:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    embed = commands.build_server_config_embed(interaction.guild, server_classes[interaction.guild_id])
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed)
    await utils.logging(bot, f"Get server config command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

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
    await utils.logging(bot, f"Set post due date command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, post_due_date, log_level=log_type.COMMAND)

@tree.command(name="invite", description="Invite the bot to your server")
async def invite(interaction: discord.Interaction):
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.INVITE_MESSAGE)
    await utils.logging(bot, f"Invite command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="ignore_bot_messages", description="Should the bot ignore messages from other bots?")
async def ignore_bot_messages(interaction: discord.Interaction, should_ignore_bot_messages: bool):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    await update_setting(interaction, "ignore_bot_messages", should_ignore_bot_messages,
                         "Ignore messages from bots")
    await utils.logging(bot, f"Ignore bot messages command used by {interaction.user.name} in {interaction.guild.name}",
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
    await utils.logging(bot, f"Calculation method command used by {interaction.user.name} in {interaction.guild.name}",
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
    await utils.logging(bot, f"Hide hall of fame posts command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(hide), log_level=log_type.COMMAND)

@tree.command(name="user_profile", description="Get the server profile of a user")
@app_commands.describe(specific_user="The member to look up, yourself when left out")
async def user_server_profile(interaction: discord.Interaction, specific_user: discord.User = None):
    """
    Get the server profile of a user
    :param interaction: The interaction object
    :param specific_user: The user to get the profile of, defaults to the interaction user
    :return: The server profile of the user
    """
    if not await ensure_bot_is_loaded(interaction):
        return

    user = specific_user or interaction.user
    if getattr(user, "bot", False):
        await send_error(interaction, messages.PROFILE_BOT_USER)
        return

    async with get_db_connection(connection_pool) as connection:
        user_stats = server_user_repo.get_server_user(connection, user.id, interaction.guild_id)

    if user_stats is None:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.PROFILE_NO_DATA)
        await utils.logging(bot, f"User server profile command used by {interaction.user.name} in {interaction.guild.name} but no data available for user {user.name}",
                            interaction.guild.id, str(user.id), log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        await commands.user_server_profile(interaction, user, user_stats, connection, month_emoji, all_time_emoji)
    await utils.logging(bot, f"Get user server profile command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(user.id), log_level=log_type.COMMAND)

@tree.command(name="leaderboard", description="Get the server leaderboard")
async def leaderboard(interaction: discord.Interaction):
    """
    Get the server leaderboard
    :param interaction: The interaction object
    :return: The server stats
    """
    if not await ensure_bot_is_loaded(interaction):
        return

    if interaction.guild_id not in server_classes:
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    if "leaderboard" in daily_command_cooldowns.get(interaction.user.id, []):
        await send_error(interaction, messages.COMMAND_ON_COOLDOWN)
        await utils.logging(bot, f"Leaderboard command on cooldown for {interaction.user.name} in {interaction.guild.name}",
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
    daily_command_cooldowns.setdefault(interaction.user.id, []).append("leaderboard")

    await utils.logging(bot, f"Leaderboard command used by {interaction.user.name} in {interaction.guild.name}",
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
        await utils.logging(bot, f"Failed to set Hall of Fame channel due to missing permissions by {interaction.user.name} in "
                                 f"{interaction.guild.name} with missing permissions: {', '.join(missing_permissions)}",
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
        if server_class is None or server_config_repo.check_if_guild_exists(connection, interaction.guild_id) is False:
            new_server_class = await events.guild_join(interaction.guild, connection, bot, channel)
            if new_server_class is None:
                await send_error(interaction, messages.HOF_CHANNEL_SETUP_FAILED.format(channel=channel.mention))
                return
            server_classes[interaction.guild_id] = new_server_class
        else:
            server_class.hall_of_fame_channel_id = channel.id

        server_config_repo.update_server_config_param(interaction.guild_id, "hall_of_fame_channel_id", channel.id, connection)

    await interaction.followup.send(messages.HOF_CHANNEL_SET.format(channel=channel.mention))
    await utils.logging(bot, f"Set Hall of Fame channel command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(channel.id), log_level=log_type.COMMAND)

@tree.command(name="hof_wrapped", description="Get your Hall of Fame Wrapped for the year")
async def hof_wrapped_command(interaction: discord.Interaction):
    if not await ensure_bot_is_loaded(interaction):
        return

    if not (interaction.guild_id in server_classes and server_classes[interaction.guild_id] is not None):
        await send_error(interaction, messages.ERROR_SERVER_NOT_SETUP)
        return

    async with get_db_connection(connection_pool) as connection:
        user_wrapped = hof_wrapped_repo.get_hof_wrapped(connection, interaction.guild_id, interaction.user.id, version.WRAPPED_YEAR)
    if user_wrapped is None:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(f"No Hall of Fame Wrapped data available for you in {version.WRAPPED_YEAR}. Participate more in Hall of Fame to get your wrapped next year!")
        await utils.logging(bot, f"HOF Wrapped command used by {interaction.user.name} in {interaction.guild.name} but no data available",
                            interaction.guild.id, str(interaction.user.id), log_level=log_type.COMMAND)
        return

    embed = await hof_wrapped.create_embed(interaction.user, user_wrapped, bot)
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed)

    await utils.logging(bot, f"HOF Wrapped command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(interaction.user.id), log_level=log_type.COMMAND)

@tree.command(name="server_hof_wrapped", description="Get the server's Hall of Fame Wrapped for the year")
async def server_hof_wrapped_command(interaction: discord.Interaction):
    if not await ensure_bot_is_loaded(interaction):
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
    await interaction.response.send_message(embed=embed)


async def check_if_user_has_manage_server_permission(interaction: discord.Interaction, check_server_set_up: bool = True):
    """
    Check if the user has manage server permission
    :param interaction:
    :param check_server_set_up: Whether to check if the server is set up
    :return: True if the user has manage server permission
    """
    if not interaction.user.guild_permissions.manage_guild:
        await send_error(interaction, messages.NOT_AUTHORIZED)
        await utils.logging(bot, f"User {interaction.user.name} does not have manage server permission",
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
        # Every run gets a new event loop, and a semaphore that has ever had to make a caller wait
        # stays bound to the loop it waited on. Reusing it after a restart would raise instead of wait
        connection_slots = asyncio.Semaphore(database_pool_size)
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
