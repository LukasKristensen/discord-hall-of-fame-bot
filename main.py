import random
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
import message_reactions

load_dotenv()
TOKEN = os.getenv('KEY')

# Connect to MongoDB
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)

# Get the database
db = client['caroon']
collection = db['messages_sent']

all_documents = []
print("Showing all documents in the collection: ")
for document in collection.find():
    print(document)
    all_documents.append(document)

# Check if the TOKEN variable is set
if TOKEN is None:
    raise ValueError("TOKEN environment variable is not set in the .env file")


print("Bot is starting...")
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

YOUR_DEDICATED_CHANNEL_ID = 1176965358796681326
reaction_threshold = 6
target_channel_id = YOUR_DEDICATED_CHANNEL_ID

# File to store sent message IDs
file_path = 'sent_messages.txt'

# Set to store sent message IDs
sent_messages = set()

# Load existing sent message IDs from the file
try:
    with open(file_path, 'r') as file:
        sent_messages = {int(line.strip()) for line in file.readlines()}
except FileNotFoundError:
    pass


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=discord.Streaming(name='infamous messages _', url='https://github.com/LukasKristensen/discord-hall-of-fame-bot'))


@bot.event
async def on_raw_reaction_add(payload):
    channel_id = payload.channel_id
    message_id = payload.message_id
    guild_id = payload.guild_id

    if channel_id == target_channel_id:
        return  # Ignore reactions in the dedicated channel

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)
    if message.author.bot:
        return  # Ignore messages from bots

    # Check if the message has surpassed the reaction threshold
    if any(reaction.count >= reaction_threshold for reaction in message.reactions):
        if collection.find_one({"message_id": message.id}):
            print("Found message in database: ", message.id)
            return
        # Get the dedicated channel
        target_channel = bot.get_channel(target_channel_id)

        # Find the first attachment (assuming it's an image or video)
        attachment_url = message.attachments[0].url if message.attachments else None

        # Check for links in the message content
        link_in_content = None
        for word in message.content.split():
            if word.startswith(('http://', 'https://')):
                link_in_content = word
                break

        # Send a simple message with the media link
        if attachment_url:
            await target_channel.send(f"{attachment_url}")
        elif link_in_content:
            await target_channel.send(f"{link_in_content}")

        embed = send_message(message)
        await target_channel.send(embed=embed)

        # Save to database
        collection.insert_one({"message_id": message.id,
                               "channel_id": str(message.channel.id),
                               "guild_id": str(message.guild.id)})


@bot.command(name='apply_reaction_checker')
async def apply_reaction_checker(ctx):
    print("CTX: ", ctx)
    print("CTX GUILD: ", ctx.guild)
    guild = ctx.guild

    try:
        for channel in guild.channels:
            print("Checking channel: ", channel.name)
            if not isinstance(channel, discord.TextChannel):
                continue
            async for message in channel.history(limit=None):
                if message.author.bot:
                    continue  # Ignore messages from bots

                if any(reaction.count >= reaction_threshold for reaction in message.reactions):
                    # Check if the message_id is in the database
                    if collection.find_one({"message_id": message.id}):
                        print("Found message in database: ", message.id)
                        continue

                    # Get the dedicated channel
                    target_channel = bot.get_channel(target_channel_id)

                    # Find the first attachment (assuming it's an image or video)
                    attachment_url = message.attachments[0].url if message.attachments else None

                    # Check for links in the message content
                    link_in_content = None
                    for word in message.content.split():
                        if word.startswith(('http://', 'https://')):
                            link_in_content = word
                            break

                    # Send a simple message with the media link
                    if attachment_url:
                        await target_channel.send(f"{attachment_url}")
                    elif link_in_content:
                        await target_channel.send(f"{link_in_content}")

                    embed = send_message(message)
                    await target_channel.send(embed=embed)

                    collection.insert_one({"message_id": message.id,
                                           "channel_id": str(message.channel.id),
                                           "guild_id": str(message.guild.id)})

    except Exception as e:
        print(f'An error occurred: {e}')


# TODO: Create a consistent function for posting message
def send_message(message):
    embed = discord.Embed(
        title=f"Message in #{message.channel.name} has surpassed {reaction_threshold} reactions",
        description=message.content,
        color=0x00ff00
    )
    most_reactions = message_reactions.most_reactions(message.reactions)
    print("Most reactions: ", most_reactions)

    embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
    # Field displaying most reacted emoji
    embed.add_field(name=f"{most_reactions[0].count} Reactions ", value=most_reactions[0].emoji, inline=True)
    embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
    return embed


@bot.command(name='get_random_message')
async def get_random_messsage(ctx):
    print("[CMD] get_random_message from:", ctx.author.name)
    sender_channel = ctx.channel.id
    random_msg = get_random_message()

    msg_channel = bot.get_channel(int(random_msg["channel_id"]))
    message = await msg_channel.fetch_message(int(random_msg["message_id"]))
    target_channel = bot.get_channel(sender_channel)

    # Find the first attachment (assuming it's an image or video)
    attachment_url = message.attachments[0].url if message.attachments else None

    # Check for links in the message content
    link_in_content = None
    for word in message.content.split():
        if word.startswith(('http://', 'https://')):
            link_in_content = word
            break

    # Send a simple message with the media link
    if attachment_url:
        await target_channel.send(f"{attachment_url}")
    elif link_in_content:
        await target_channel.send(f"{link_in_content}")

    embed = send_message(message)
    await target_channel.send(embed=embed)


def get_random_message():
    all_messages = []
    for message in collection.find():
        all_messages.append(message)
    random_num = random.randint(0, len(all_messages)-1)
    return all_messages[random_num]

# Run the bot with your token
bot.run(TOKEN)

