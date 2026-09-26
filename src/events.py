import discord
import asyncio
import datetime
from contextlib import contextmanager
import concurrency
import utils
from translations import messages
from enums import command_refs
from repositories import server_config_repo, hall_of_fame_message_repo

# The daily sweep runs once per server the bot is in, so it is paced rather than run all at once:
# a bounded number of servers are handled together, and any single one that hangs is abandoned so
# that it cannot cost the remaining servers their update
daily_task_concurrency = 5
daily_task_guild_timeout_seconds = 120

# psycopg2 blocks the event loop while a query runs, so the per-server timeout above cannot fire during
# a stalled query. The database is told to cancel any single statement that runs longer than this
# instead, which bounds how long one server can hold up the loop
daily_task_statement_timeout_ms = 20_000


async def post_wrapped():
    """
    Compute and post the hall of fame wrapped for individual servers
    :return:
    """
    if datetime.datetime.now().month == 12 and datetime.datetime.now().day == 28:
        return
        # Todo: Evaluate and improve performance in a local environments before deploying to production
        # disabled until tested for dynamic usage across multiple servers and refactored
        # await hof_wrapped.main(bot.get_guild(guild_id), collection, reaction_threshold, target_channel_id)

async def check_for_new_server_classes(bot, connection):
    new_server_classes = {}
    for guild in bot.guilds:
        if not server_config_repo.check_if_guild_exists(connection, guild.id) and guild.me.guild_permissions.manage_channels:
            await utils.logging(bot, f"Guild {guild.name} not found in database, creating...", guild.id)
            try:
                new_server_class = await utils.create_database_context(bot, guild, connection)
                new_server_classes[guild.id] = new_server_class
            except Exception as e:
                await utils.logging(bot, f"Failed to create database context for server {guild.name}: {e}", guild.id)
    return new_server_classes


async def bot_login(bot: discord.Client, tree):
    """
    Event handler for when the bot is ready
    :param bot:
    :param tree:
    :return:
    """
    try:
        await tree.sync()
        await utils.logging(bot, f"Logged in as {bot.user}")
    except discord.HTTPException as e:
        await utils.logging(bot, f"Failed to sync commands: {e}")
    await bot.change_presence(activity=discord.CustomActivity(name="🔥 Sweeping for legendary moments!", type=5))
    await utils.logging(bot, f"Total servers: {len(bot.guilds)}")


async def on_raw_reaction(message: discord.RawReactionActionEvent, bot: discord.Client, connection, server_config):
    """
    Event handler for when a reaction is added to a message
    :param message: The message that the reaction was removed from
    :param bot: The bot client
    :param connection:
    :param server_config: The in memory configuration of the server the reaction happened in
    :return: None
    """

    try:
        await utils.validate_message(message, bot, connection, server_config)
    except Exception as e:
        # A message that has been deleted since it was reacted to is ordinary, and reporting it
        # would bury everything else
        if "Unknown Message" in str(e):
            return
        # Everything else is reported. This used to stay quiet unless the message was already on the
        # board, and to discard every error reading "object has no attribute" outright, which is
        # every AttributeError there is: a bug in the posting path left no trace at all. Repeats are
        # collapsed per server, so one message failing over and over cannot flood the log
        await utils.logging(bot, f"Error in reaction event: {e}", message.guild_id,
                            validate_for_duplicates=True)


async def on_message(message: discord.Message, bot: discord.Client, server_config):
    """
    Event handler for when a message is sent in a channel
    :param message: The message that was sent
    :param bot: The bot client
    :param server_config: The in memory configuration of the server the message was sent in
    :return: None
    """
    if (message.channel.id != server_config.hall_of_fame_channel_id
            or message.author.bot
            or server_config.allow_messages_in_hof_channel):
        return

    permissions = message.channel.permissions_for(message.guild.me)
    if not permissions.manage_messages:
        # Nothing can be removed without this. Left silent on purpose: warning from here would fire
        # once per message posted, which is exactly the situation the permission is missing in
        return

    await message.delete()

    # Without this the reminder itself fails, and the member is left with a deletion and no reason
    if not permissions.send_messages:
        return

    msg = await message.channel.send(f"Only Hall of Fame messages are allowed in this channel, {message.author.mention}. "
                                     f"Can be disabled by {command_refs.ALLOW_MESSAGES_IN_HOF_CHANNEL}")
    await asyncio.sleep(5)
    await msg.delete()


async def guild_join(server, connection, bot, custom_channel: discord.TextChannel = None):
    """
    Event handler for when the bot is added to a server
    :param server:
    :param connection:
    :param bot:
    :param custom_channel: Optional custom channel ID for the Hall of Fame channel
    :return:
    """
    try:
        return await utils.create_database_context(bot, server, connection, custom_channel)
    except Exception as e:
        await utils.logging(bot, f"Failed to create database context for server {server.name}: {e}", server.id)
        await utils.send_message_to_highest_prio_channel(bot, server,
                                                         messages.FAILED_SETUP_HOF.format(serverName=server.name), 0)


async def guild_remove(server, connection):
    """
    Event handler for when the bot is removed from a server
    :param server:
    :param connection:
    :return:
    """
    utils.delete_database_context(server.id, connection)


@contextmanager
def statement_timeout(connection, milliseconds: int):
    """
    Have the database cancel any statement on this connection that runs longer than the limit.

    The limit is set for the session rather than with SET LOCAL, because the repositories commit as
    they go and SET LOCAL would be dropped at the first commit. Pooled connections are reused, so it
    is always reset afterwards, after rolling back a transaction the failure may have left aborted.
    :param connection: A connection borrowed for this block alone
    :param milliseconds: The longest a single statement may run
    """
    _execute_and_commit(connection, "SET statement_timeout = %s", (milliseconds,))
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        _execute_and_commit(connection, "RESET statement_timeout")


def _execute_and_commit(connection, sql, params=None):
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
    finally:
        cursor.close()
    connection.commit()


async def daily_task(bot, connection, server_classes, dev_testing, borrow_connection):
    """
    Daily task to check for updating the leaderboard
    :param bot:
    :param connection:
    :param server_classes:
    :param dev_testing:
    :param borrow_connection: Returns an async context manager lending a connection of its own to one
        leaderboard update. Guilds are updated concurrently, and on one shared connection a database
        error in one guild aborts the transaction every other in-flight guild is writing to
    :return:
    """
    await utils.logging(bot, f"Starting daily task for {len(server_classes)} servers")

    bot_guild_ids = {guild.id for guild in bot.guilds}
    due_for_leaderboard = [
        server_class for server_class in list(server_classes.values())
        if server_class.guild_id in bot_guild_ids
        and server_config_repo.get_parameter_value(connection, server_class.guild_id, "leaderboard_setup")
    ]

    async def update_one_leaderboard(server_class):
        async with borrow_connection() as guild_connection:
            with statement_timeout(guild_connection, daily_task_statement_timeout_ms):
                await utils.update_leaderboard(guild_connection, bot, server_class)

    async def report_leaderboard_failure(server_class, error):
        if isinstance(error, asyncio.TimeoutError):
            await utils.logging(bot, f"Timed out updating leaderboard for server {server_class.guild_id} "
                                     f"after {daily_task_guild_timeout_seconds} seconds", server_class.guild_id)
            return
        await utils.logging(bot, f"Error updating leaderboard for server {server_class.guild_id}: {error}")

    leaderboards = await concurrency.run_in_batches(
        due_for_leaderboard,
        update_one_leaderboard,
        limit=daily_task_concurrency,
        timeout=daily_task_guild_timeout_seconds,
        on_error=report_leaderboard_failure)
    await utils.logging(bot, f"Updated {len(leaderboards.completed)} leaderboards, "
                             f"{len(leaderboards.failed)} failed")

    await utils.logging(bot, f"Checking for db entries that are not in the guilds")
    for server in server_classes.values():
        if dev_testing:
            continue
        if int(server.guild_id) not in [guild.id for guild in bot.guilds]:
            await utils.logging(bot, f"Could not find server {server.guild_id} in bot guilds")
    await utils.logging(bot, f"Checked {len(server_classes)} servers for daily task")
    await update_user_database(bot, connection)
    await check_write_permissions_to_hall_of_fame_channel(bot, server_classes)


async def check_write_permissions_to_hall_of_fame_channel(bot: discord.Client, server_classes):
    """
    Check if the bot has write permissions to the Hall of Fame channel for each server
    :param bot: The bot client
    :param server_classes: The server classes
    :return: None
    """
    async def check_one_server(server_class):
        guild = bot.get_guild(server_class.guild_id)
        if not guild:
            return
        channel = guild.get_channel(server_class.hall_of_fame_channel_id)
        if not channel:
            await utils.logging(bot, f"Could not find Hall of Fame channel for server {guild.name}", guild.id)
            # await utils.send_message_to_highest_prio_channel(bot, guild, messages.FAILED_TO_FIND_HOF_CHANNEL)
            return
        permissions = channel.permissions_for(guild.me)
        missing_permissions = []
        if not permissions.view_channel:
            missing_permissions.append("View Channel")
        if not permissions.send_messages:
            missing_permissions.append("Send Messages")
        if not permissions.read_message_history:
            missing_permissions.append("Read Message History")

        if not missing_permissions:
            return
        channel_ref = f"<#{channel.id}>"
        await utils.send_message_to_highest_prio_channel(bot, guild, messages.MISSING_HOF_CHANNEL_PERMISSIONS.format(
                        missing_permissions=", ".join(missing_permissions), channel=channel_ref))

    async def report_permission_failure(server_class, error):
        await utils.logging(bot, f"Error checking Hall of Fame channel permissions for server "
                                 f"{server_class.guild_id}: {error}", server_class.guild_id)

    await concurrency.run_in_batches(
        list(server_classes.values()),
        check_one_server,
        limit=daily_task_concurrency,
        timeout=daily_task_guild_timeout_seconds,
        on_error=report_permission_failure)


async def update_user_database(bot: discord.Client, connection):
    """
    Update the user database with the latest information
    :param bot: The bot client
    :param connection: The database connection
    :return: None
    """
    try:
        await utils.update_user_database(bot, connection)
        await utils.logging(bot, "User database updated successfully")
    except Exception as e:
        await utils.logging(bot, f"Failed to update user database: {e}")
