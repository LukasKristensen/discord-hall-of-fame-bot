import discord
from discord.ext import commands as discord_commands
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
#       [-] Server join routine:
#               [-] Setup new db document for the server
#               [-] Create a new HOF channel for the server and store the channel_id in the db
#               [-] Create a new leaderboard message for the server and store the message_id in the db
#               [-] Create a new server config document for the server
#               [-] Server setup routine for configuring the bot with threshold and other settings
#       [-] Server leave routine:
#               [-] Delete the db document for the server
#       [-] Refactor the code to be able to handle multiple servers
#       [-] Setup a server on azure to host the bot
#       [-] Research db security measures to prevent unauthorized access
#       [-] Disable getRandomMessage or add a server parameter to the command
#       [-] Optimize the code to handle multiple servers without performance issues on scaling
#       [x] Disable LLM model for now, as it is not optimized for multiple servers
#       [-] Language support MVP:
#               [-] Support Danish and English
#               [-] Add a language parameter to the command in the bot setup routine or as a command
#               [-] Translations document for each language
#               [-] Implement the translations in the bot
#       [x] Refactor the bot for supporting slash commands (Better user experience)
#       [-] Make HOF Wrapped channel dynamic, so that it will create a new thread in the HOF channel for each server
#       [-] Extract all variables to a config file in the db for each server
#       [-] Refactor historical search to be date-sorted, so they are first stored in a list and then sorted by date and then posted


#region Events
@bot.event
async def on_ready():
    global server_classes
    server_classes = utils.get_server_classes(db_client)
    await events.on_ready(bot, tree, db_client, server_classes)

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

@bot.event
async def on_guild_remove(server):
    await events.guild_remove(server, db_client)
    server_classes.pop(server.id)

@tree.command(name="get_random_message", description="Get a random message from the Hall of Fame database")
async def get_random_message(interaction: discord.Interaction):
    collection = db_client[str(interaction.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_classes[interaction.guild_id].reaction_threshold
    await commands.get_random_message(interaction, collection, bot, temp_reaction_threshold)

@tree.command(name="commands", description="List of commands")
async def get_commands(interaction: discord.Interaction):
    await commands.get_commands(interaction)

@tree.command(name="manual_sweep", description="Manually sweep all messages in a server [DEV ONLY]")
async def manual_sweep(interaction: discord.Interaction, sweep_limit: int, guild_id: int, sweep_limited: bool):
    collection = db_client[str(guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_classes[guild_id].reaction_threshold
    post_due_date = server_classes[guild_id].post_due_date
    target_channel_id = server_classes[guild_id].hall_of_fame_channel_id

    await commands.manual_sweep(interaction, guild_id, sweep_limit, sweep_limited, bot, collection,
                                temp_reaction_threshold, post_due_date, target_channel_id, dev_user)

@tree.command(name="reaction_threshold_configure", description="Configure the amount of reactions needed to post a message in the Hall of Fame")
async def configure_bot(interaction: discord.Interaction, reaction_threshold: int):
    completion = await commands.set_reaction_threshold(interaction, reaction_threshold, db_client)
    if completion:
        server_classes[interaction.guild_id].reaction_threshold = reaction_threshold

# Check if the TOKEN variable is set
if TOKEN is None or mongo_uri is None:
    raise ValueError("TOKEN environment variable is not set in the .env file")
bot.run(TOKEN)
