import discord
import asyncio
import datetime
import utils

async def on_ready(bot: discord.Client, tree, guild_id: int, sweep_limit: int, sweep_limited: bool,
                   collection, reaction_threshold: int, post_due_date: int, target_channel_id: int, server_config):
    """
    Event handler for when the bot is ready
    :param bot:
    :param tree:
    :param guild_id:
    :param sweep_limit:
    :param sweep_limited:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :param server_config:
    :return:
    """
    try:
        await tree.sync()
        print(f"Logged in as {bot.user}")
    except discord.HTTPException as e:
        print(f"Failed to sync commands: {e}")
    await bot.change_presence(
        activity=discord.CustomActivity(name=f'{len([x for x in collection.find()])} Hall of Fame messages', type=5))
    await utils.check_all_server_messages(guild_id, sweep_limit, sweep_limited,  bot, collection, reaction_threshold,
                                          post_due_date, target_channel_id)
    await utils.update_leaderboard(collection, bot, server_config, target_channel_id, reaction_threshold)

    if datetime.datetime.now().month == 12 and datetime.datetime.now().day == 28:
        pass
        # disabled until tested for dynamic usage across multiple servers and refactored
        # await hof_wrapped.main(bot.get_guild(guild_id), collection, reaction_threshold, target_channel_id)

async def on_raw_reaction_add(message: discord.RawReactionActionEvent, bot: discord.Client, collection,
                              reaction_threshold: int, post_due_date: int, target_channel_id: int):
    """
    Event handler for when a reaction is added to a message
    :param message:
    :param bot:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :return:
    """
    await utils.validate_message(message, bot, collection, reaction_threshold, post_due_date, target_channel_id)

async def on_raw_reaction_remove(message: discord.RawReactionActionEvent, bot: discord.Client, collection,
                              reaction_threshold: int, post_due_date: int, target_channel_id: int):
    """
    Event handler for when a reaction is added to a message
    :param message: The message that the reaction was removed from
    :param bot: The bot client
    :param collection: The collection of messages
    :param reaction_threshold: The threshold for reactions
    :param post_due_date: The due date for posting
    :param target_channel_id: The target channel id
    :return: None
    """
    await utils.validate_message(message, bot, collection, reaction_threshold, post_due_date, target_channel_id)

async def on_message(message, bot, target_channel_id):
    """
    Event handler for when a message is sent in a channel
    :param message:
    :param bot:
    :param target_channel_id:
    :return:
    """
    if message.author.bot:
        return
    if message.channel.id == target_channel_id and not message.author.bot:
        await message.delete()
        msg = await message.channel.send(f"Kun bot posts herinde {message.author.mention}")
        await asyncio.sleep(5)
        await msg.delete()
    await bot.process_commands(message)

async def guild_join(server, db_client):
    print(f"Joined server {server.name}")
    await utils.create_database_context(server, db_client)

async def guild_remove(server, db_client):
    print(f"Left server {server.name}")
    utils.delete_database_context(server.id, db_client)