import discord
import asyncio
import datetime
import utils
from translations import messages


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


async def check_for_new_server_classes(bot: discord.Client, db_client):
    """
    Check if any of the joined guilds are not in the database
    :param bot:
    :param db_client:
    :return:
    """
    server_classes_collection = db_client["server_configs"]
    new_server_classes = {}
    for guild in bot.guilds:
        try:
            if server_classes_collection.count_documents({"guild_id": int(guild.id)}) == 0:
                await utils.logging(bot, f"Guild {guild.name} not found in database, creating...", guild.id)
                new_server_class = await utils.create_database_context(bot, guild, db_client)
                new_server_classes[guild.id] = new_server_class
        except Exception as e:
            await utils.send_server_owner_error_message(guild.owner, messages.FAILED_SETUP_HOF.format(serverName=guild.name), bot)
            await utils.logging(bot, f"Sending error message to server owner: {e}", guild.id)
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


async def on_raw_reaction(message: discord.RawReactionActionEvent, bot: discord.Client, message_collection,
                          reaction_threshold: int, post_due_date: int, target_channel_id: int,
                          ignore_bot_messages: bool, hide_hof_post_below_threshold: bool):
    """
    Event handler for when a reaction is added to a message
    :param message: The message that the reaction was removed from
    :param bot: The bot client
    :param message_collection: The collection of messages
    :param reaction_threshold: The threshold for reactions
    :param post_due_date: The due date for posting
    :param target_channel_id: The target channel id
    :param ignore_bot_messages: Whether to ignore bot messages
    :param hide_hof_post_below_threshold: Whether to hide hall of fame posts below the threshold
    :return: None
    """
    try:
        await utils.validate_message(message, bot, message_collection, reaction_threshold, post_due_date,
                                     target_channel_id, ignore_bot_messages, hide_hof_post_below_threshold)
    except Exception as e:
        if "Unknown Message" in str(e) or "object has no attribute" in str(e):
            return
        if message_collection.find_one({"guild_id": int(message.guild_id)}):
            await utils.logging(bot, f"Error in reaction event: {e}", message.guild_id)


async def on_message(message, bot: discord.Client, target_channel_id, allow_messages_in_hof_channel):
    """
    Event handler for when a message is sent in a channel
    :param message:
    :param bot:
    :param target_channel_id:
    :param allow_messages_in_hof_channel:
    :return:
    """
    if message.channel.id != target_channel_id or message.author.bot or allow_messages_in_hof_channel:
        return

    await message.delete()
    msg = await message.channel.send(
        f"Only Hall of Fame messages are allowed in this channel, {message.author.mention}. Can be disabled by </allow_messages_in_hof_channel:1348428694007316571>")
    await asyncio.sleep(5)
    await msg.delete()


async def guild_join(server, db_client, bot, custom_channel: discord.TextChannel = None):
    """
    Event handler for when the bot is added to a server
    :param server:
    :param db_client:
    :param bot:
    :param custom_channel: Optional custom channel ID for the Hall of Fame channel
    :return:
    """
    try:
        return await utils.create_database_context(bot, server, db_client, custom_channel)
    except Exception as e:
        await utils.logging(bot, f"Failed to create database context for server {server.name}: {e}", server.id)
        await utils.send_message_to_highest_prio_channel(bot, server,
                                                         messages.FAILED_SETUP_HOF.format(serverName=server.name), 0)


async def guild_remove(server, db_client):
    """
    Event handler for when the bot is removed from a server
    :param server:
    :param db_client:
    :return:
    """
    utils.delete_database_context(server.id, db_client)


async def daily_task(bot: discord.Client, db_client, server_classes, dev_testing):
    """
    Daily task to check for updating the leaderboard
    :param bot:
    :param db_client:
    :param server_classes:
    :param dev_testing:
    :return:
    """
    await utils.logging(bot, f"Starting daily task for {len(server_classes)} servers")

    bot_guild_ids = [guild.id for guild in bot.guilds]
    for server_class in list(server_classes.values()):
        if not server_class.leaderboard_setup or server_class.guild_id not in bot_guild_ids:
            continue
        try:
            # get all entities where guild_id is the same as the server_class.guild_id
            message_collection = db_client["hall_of_fame_messages"]
            server_config = db_client["server_configs"].find_one({"guild_id": int(server_class.guild_id)})
            await utils.update_leaderboard(
                message_collection,
                bot,
                server_config,
                server_class.hall_of_fame_channel_id,
                server_class.reaction_threshold)
        except Exception as e:
            await utils.logging(bot, f"Error updating leaderboard for server {server_class.guild_id}: {e}")

    await utils.logging(bot, f"Checking for db entries that are not in the guilds")
    for server in db_client["server_configs"].find():
        if server and not dev_testing and int(server["guild_id"]) not in [guild.id for guild in bot.guilds]:
            guild_id = int(server["guild_id"])
            await utils.logging(bot, f"Could not find server {guild_id} in bot guilds")
    await utils.logging(bot, f"Checked {len(server_classes)} servers for daily task")
    await update_user_database(bot, db_client)
    await check_write_permissions_to_hall_of_fame_channel(bot, server_classes)


async def check_write_permissions_to_hall_of_fame_channel(bot: discord.Client, server_classes):
    """
    Check if the bot has write permissions to the Hall of Fame channel for each server
    :param bot: The bot client
    :param server_classes: The server classes
    :return: None
    """
    for server_class in list(server_classes.values()):
        guild = bot.get_guild(server_class.guild_id)
        if not guild:
            continue
        channel = guild.get_channel(server_class.hall_of_fame_channel_id)
        if not channel:
            await utils.logging(bot, f"Could not find Hall of Fame channel for server {guild.name}", guild.id)
            await utils.send_message_to_highest_prio_channel(bot, guild, messages.FAILED_SETUP_HOF.format(serverName=guild.name))
            continue
        missing_permissions = []
        if not channel.permissions_for(guild.me).view_channel:
            missing_permissions.append("View Channel")
        if not channel.permissions_for(guild.me).send_messages:
            missing_permissions.append("Send Messages")
        if not missing_permissions:
            continue
        await utils.send_message_to_highest_prio_channel(bot, guild, messages.MISSING_HOF_CHANNEL_PERMISSIONS.format(
                        missing_permissions=", ".join(missing_permissions)))


async def update_user_database(bot: discord.Client, db_client):
    """
    Update the user database with the latest information
    :param bot: The bot client
    :param db_client: The database client
    :return: None
    """
    try:
        await utils.update_user_database(bot, db_client)
        await utils.logging(bot, "User database updated successfully")
    except Exception as e:
        await utils.logging(bot, f"Failed to update user database: {e}")
