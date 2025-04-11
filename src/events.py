import discord
import asyncio
import datetime
import utils
import main

async def historical_sweep(bot: discord.Client, db_client, server_classes):
    """
    Event handler for when the bot is ready
    :param bot:
    :param db_client:
    :param server_classes:
    :return:
    """
    hof_total_messages = 0

    for server_class in server_classes.values():
        try:
            print(f"Checking server {server_class.guild_id}")
            server_collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]
            server_config = db_client[str(server_class.guild_id)]["server_config"]
            hof_total_messages += server_collection.count_documents({})
            await utils.check_all_server_messages(
                server_class.guild_id,
                server_class.sweep_limit,
                server_class.sweep_limited,
                bot,
                server_collection,
                server_class.reaction_threshold,
                server_class.post_due_date,
                server_class.hall_of_fame_channel_id,
                server_class.allow_messages_in_hof_channel)
            await utils.update_leaderboard(
                server_collection,
                bot,
                server_config,
                server_class.hall_of_fame_channel_id,
                server_class.reaction_threshold)
        except Exception as e:
            print(f"Failed to check server {server_class.guild_id}: {e}")
            # TODO: Log error here to a discord channel for debugging - Include server id and error message
    main.total_message_count = hof_total_messages
    await bot.change_presence(activity=discord.CustomActivity(name=f'{hof_total_messages} Hall of Fame messages', type=5))
    print("total_message_count: ", hof_total_messages)


async def post_wrapped():
    """
    Compute and post the hall of fame wrapped for individual servers
    :return:
    """
    if datetime.datetime.now().month == 12 and datetime.datetime.now().day == 28:
        pass
        # disabled until tested for dynamic usage across multiple servers and refactored
        # await hof_wrapped.main(bot.get_guild(guild_id), collection, reaction_threshold, target_channel_id)


async def check_for_new_server_classes(bot, db_client):
    """
    Check if any of the joined guilds are not in the database
    :param bot:
    :param db_client:
    :return:
    """
    new_server_classes = {}
    for guild in bot.guilds:
        try:
            print(f"Checking guild {guild.name}")
            if not str(guild.id) in db_client.list_database_names():
                print(f"Guild {guild.name} not found in database, creating...")
                new_server_class = await utils.create_database_context(guild, db_client)
                new_server_classes[guild.id] = new_server_class
        except Exception as e:
            print(f"Failed to create database context for guild {guild.name}: {e}")
            await utils.send_server_owner_error_message(guild.owner, e)
    return new_server_classes


async def bot_login(bot, tree):
    try:
        await tree.sync()
        print(f"Logged in as {bot.user}")
    except discord.HTTPException as e:
        print(f"Failed to sync commands: {e}")
    await bot.change_presence(activity=discord.CustomActivity(name="New /slash commands integrated", type=5))


async def on_raw_reaction_add(message: discord.RawReactionActionEvent, bot: discord.Client, collection,
                              reaction_threshold: int, post_due_date: int, target_channel_id: int, allow_messages_in_hof_channel: bool):
    """
    Event handler for when a reaction is added to a message
    :param message:
    :param bot:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :param allow_messages_in_hof_channel:
    :return:
    """
    await utils.validate_message(message, bot, collection, reaction_threshold, post_due_date, target_channel_id, allow_messages_in_hof_channel)

async def on_raw_reaction_remove(message: discord.RawReactionActionEvent, bot: discord.Client, collection,
                              reaction_threshold: int, post_due_date: int, target_channel_id: int, allow_messages_in_hof_channel: bool):
    """
    Event handler for when a reaction is added to a message
    :param message: The message that the reaction was removed from
    :param bot: The bot client
    :param collection: The collection of messages
    :param reaction_threshold: The threshold for reactions
    :param post_due_date: The due date for posting
    :param target_channel_id: The target channel id
    :param allow_messages_in_hof_channel: Whether messages are allowed in the hall of fame channel
    :return: None
    """
    await utils.validate_message(message, bot, collection, reaction_threshold, post_due_date, target_channel_id, allow_messages_in_hof_channel)

async def on_message(message, bot, target_channel_id, allow_messages_in_hof_channel):
    """
    Event handler for when a message is sent in a channel
    :param message:
    :param bot:
    :param target_channel_id:
    :param allow_messages_in_hof_channel:
    :return:
    """
    if message.author.bot or allow_messages_in_hof_channel:
        return

    if message.channel.id == target_channel_id and not message.author.bot:
        await message.delete()
        msg = await message.channel.send(f"Only Hall of Fame messages are allowed in this channel, {message.author.mention}")
        await asyncio.sleep(5)
        await msg.delete()
    await bot.process_commands(message)

async def guild_join(server, db_client, reaction_threshold: int = 7):
    print(f"Joined server {server.name}")
    try:
        return await utils.create_database_context(server, db_client, reaction_threshold_default=reaction_threshold)
    except Exception as e:
        print(f"Failed to create database context for server {server.name}: {e}")

async def guild_remove(server, db_client):
    print(f"Left server {server.name}")
    utils.delete_database_context(server.id, db_client)