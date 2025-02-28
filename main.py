import discord
from discord.ext import commands as discord_commands
from discord.app_commands import check
import os
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
import commands
import events
import utils

load_dotenv()
TOKEN = os.getenv('KEY')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)
messages_processing = []

bot = discord_commands.Bot(command_prefix="!", intents=discord.Intents.all())
tree = bot.tree
server_classes = {}
dev_user = 230698327589650432

# todo: Make dynamic for multiple servers
#       [-] If opening up for multiple servers: create security measures to
#           validate that the origin of the message correlates to the server
#       [-] Research topic: How reliable is the `guild_id` attribute of a message? Can it be spoofed?
#               [-] Put as many security measures in place as possible to prevent unauthorized access
#                       [-] Is the requesting user a part of the guild
#               [-] Research how to validate the origin of a message
#       [x] Server join routine:
#               [x] Setup new db document for the server
#               [x] Create a new HOF channel for the server and store the channel_id in the db
#               [x] Create a new leaderboard message for the server and store the message_id in the db
#               [x] Create a new server config document for the server
#               [x] Server setup routine for configuring the bot with threshold and other settings
#       [x] Server leave routine:
#               [x] Delete the db document for the server
#       [x] Refactor the code to be able to handle multiple servers
#       [x] Setup a server on azure to host the bot
#       [-] Research db security measures to prevent unauthorized access
#       [x] Disable getRandomMessage or add a server parameter to the command
#       [-] Optimize the code to handle multiple servers without performance issues on scaling
#       [x] Disable LLM model for now, as it is not optimized for multiple servers
#       [-] Language support MVP:
#               [-] Support Danish and English
#               [-] Add a language parameter to the command in the bot setup routine or as a command
#               [-] Translations document for each language
#               [-] Implement the translations in the bot
#       [x] Refactor the bot for supporting slash commands (Better user experience)
#       [x] Make HOF Wrapped channel dynamic, so that it will create a new thread in the HOF channel for each server
#       [x] Extract all variables to a config file in the db for each server
#       [-] Refactor historical search to be date-sorted, so they are first stored in a list and then sorted by date and then posted


#region Events
@bot.event
async def on_ready():
    global server_classes
    await utils.error_logging(bot, f"Logged in as {bot.user}")
    server_classes = utils.get_server_classes(db_client)
    new_server_classes_dict = await events.on_ready(bot, tree, db_client, server_classes)
    print("New server classes: ", new_server_classes_dict)
    for key, value in new_server_classes_dict.items():
        server_classes[key] = value
    print("Dictionary after on_ready: ", server_classes)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    server_class = server_classes[payload.guild_id]
    collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_class.reaction_threshold
    post_due_date = server_class.post_due_date
    target_channel_id = server_class.hall_of_fame_channel_id

    if not payload.message_id in messages_processing:
        messages_processing.append(payload.message_id)
        await events.on_raw_reaction_add(payload, bot, collection, temp_reaction_threshold, post_due_date, target_channel_id)
        messages_processing.remove(payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    server_class = server_classes[payload.guild_id]
    collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_class.reaction_threshold
    post_due_date = server_class.post_due_date
    target_channel_id = server_class.hall_of_fame_channel_id

    if not payload.message_id in messages_processing:
        messages_processing.append(payload.message_id)
        await events.on_raw_reaction_remove(payload, bot, collection, temp_reaction_threshold, post_due_date, target_channel_id)
        messages_processing.remove(payload.message_id)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    server_class = server_classes[message.guild.id]
    target_channel_id = server_class.hall_of_fame_channel_id
    await events.on_message(message, bot, target_channel_id)

@bot.event
async def on_guild_join(server):
    new_server_class = await events.guild_join(server, db_client)
    server_classes[server.id] = new_server_class
    await utils.error_logging(bot, f"Joined server {server.name}, id: {server.id}")

@bot.event
async def on_guild_remove(server):
    await events.guild_remove(server, db_client)
    server_classes.pop(server.id)
    await utils.error_logging(bot, f"Left server {server.name}, id: {server.id}")

@tree.command(name="restart", description="Restart the bot [Dev Only]")
async def restart(interaction: discord.Interaction):
    if not await check_if_dev_user(interaction): return

    await interaction.response.send_message("Restarting the bot")
    await utils.error_logging(bot, "Restarting the bot")
    await bot.close()

@tree.command(name="setup", description="Setup the bot for the server [Owner Only]")
async def setup(interaction: discord.Interaction, reaction_threshold: int):
    if not await check_if_server_owner(interaction): return

    if not interaction.guild.me.guild_permissions.manage_channels or not interaction.guild.me.guild_permissions.manage_messages:
        await interaction.response.send_message("The bot does not have the required permissions to setup the server")
        return

    if str(interaction.guild_id) in db_client.list_database_names():
        await interaction.response.send_message("The server is already set up")
        return

    try:
        new_server_class = await events.guild_join(interaction.guild, db_client, reaction_threshold)
    except Exception as e:
        await interaction.response.send_message(f"Failed to setup the bot for the server: {e}")

    server_classes[interaction.guild.id] = new_server_class
    await utils.error_logging(bot, f"Setup the bot for the server {interaction.guild.name}, id: {interaction.guild.id}")

@tree.command(name="get_random_message", description="Get a random message from the Hall of Fame database")
async def get_random_message(interaction: discord.Interaction):
    collection = db_client[str(interaction.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_classes[interaction.guild_id].reaction_threshold
    await commands.get_random_message(interaction, collection, bot, temp_reaction_threshold)
    await utils.error_logging(bot, f"Get random message command used by {interaction.user.name} in {interaction.guild.name} ({interaction.guild_id})")

@tree.command(name="help", description="List of commands")
async def get_help(interaction: discord.Interaction):
    await commands.get_help(interaction)
    await utils.error_logging(bot, f"Help command used by {interaction.user.name} in {interaction.guild.name} ({interaction.guild_id})")

@tree.command(name="manual_sweep", description="Check for any historical message that should be in the Hall of Fame [Dev Only]")
async def manual_sweep(interaction: discord.Interaction, guild_id: str):
    if not await check_if_dev_user(interaction): return
    collection = db_client[guild_id]["hall_of_fame_messages"]

    guild_id = int(guild_id)
    temp_reaction_threshold = server_classes[guild_id].reaction_threshold
    post_due_date = server_classes[guild_id].post_due_date
    target_channel_id = server_classes[guild_id].hall_of_fame_channel_id

    await commands.manual_sweep(interaction, int(guild_id), None, False, bot, collection,
                                temp_reaction_threshold, post_due_date, target_channel_id, dev_user)
    await utils.error_logging(bot, f"Manual sweep command used by {interaction.user.name} in {interaction.guild.name} ({interaction.guild_id})")

@tree.command(name="reaction_threshold_configure", description="Configure the amount of reactions needed to post a message in the Hall of Fame [Owner Only]")
async def configure_bot(interaction: discord.Interaction, reaction_threshold: int):
    if not await check_if_server_owner(interaction): return

    completion = await commands.set_reaction_threshold(interaction, reaction_threshold, db_client)
    if completion:
        server_classes[interaction.guild_id].reaction_threshold = reaction_threshold
    await utils.error_logging(bot, f"Reaction threshold configure command used by {interaction.user.name} in {interaction.guild.name} ({interaction.guild_id})")

async def check_if_server_owner(interaction: discord.Interaction):
    """
    Check if the user is the server owner
    :param interaction:
    :return: True if the user is the server owner
    """
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("You are not authorized to use this command, only for server owner")
        return False
    return True

async def check_if_dev_user(interaction: discord.Interaction):
    """
    Check if the user is a developer
    :param interaction:
    :return: True if the user is a developer
    """
    if interaction.user.id != dev_user:
        await interaction.response.send_message("You are not authorized to use this command, only for developers")
        return False
    return True

# Check if the TOKEN variable is set
if TOKEN is None or mongo_uri is None:
    raise ValueError("TOKEN environment variable is not set in the .env file")
bot.run(TOKEN)
