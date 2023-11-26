import random
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
import message_reactions

load_dotenv()
TOKEN = os.getenv('KEY')

# Set up the MongoDB client
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['caroon']
collection = db['messages_sent']

iteration = 23
user_gifs = db['user_gifs'+str(iteration)]

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
YOUR_DEDICATED_CHANNEL_ID = 1176965358796681326
reaction_threshold = 6
target_channel_id = YOUR_DEDICATED_CHANNEL_ID

# Set to store sent message IDs
sent_messages = set()


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=discord.Streaming(name='!commands', url='https://github.com/LukasKristensen/discord-hall-of-fame-bot'))


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
        target_channel = bot.get_channel(target_channel_id)

        video_link = check_video_extension(message)
        if video_link:
            await target_channel.send(video_link)

        embed = send_message(message)
        await target_channel.send(embed=embed)

        # Save to database
        collection.insert_one({"message_id": message.id,
                               "channel_id": str(message.channel.id),
                               "guild_id": str(message.guild.id)})


@bot.command(name='apply_reaction_checker')
async def cmd_check_emoji_reaction(ctx):
    guild = ctx.guild

    if not ctx.author.id == 230698327589650432:
        ctx.message.reply("You are not allowed to use this command")
        return

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

                    video_link = check_video_extension(message)
                    if video_link:
                        await target_channel.send(video_link)

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
    if message.attachments:
        embed.set_image(url=message.attachments[0].url)
    embed.add_field(name=f"{most_reactions[0].count} Reactions ", value=most_reactions[0].emoji, inline=True)
    embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
    return embed


@bot.command(name='get_random_message')
async def cmd_random_message(ctx):
    print("[CMD] get_random_message from:", ctx.author.name)
    sender_channel = ctx.channel.id
    random_msg = get_random_message()

    msg_channel = bot.get_channel(int(random_msg["channel_id"]))
    message = await msg_channel.fetch_message(int(random_msg["message_id"]))
    target_channel = bot.get_channel(sender_channel)

    video_link = check_video_extension(message)
    if video_link:
        await target_channel.send(video_link)

    embed = send_message(message)
    await target_channel.send(embed=embed)
    return


@bot.command(name='commands')
async def cmd_help(ctx):
    embed = discord.Embed(
        title="Commands",
        color=0x00ff00
    )
    embed.add_field(name="!commands", value="List of commands", inline=False)
    embed.add_field(name="!apply_reaction_checker", value="Apply reaction checker to all messages in the server", inline=False)
    embed.add_field(name="!get_random_message", value="Get a random message from the database", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    await ctx.send(embed=embed)


video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm']


@bot.command(name='get_history_gifs')
async def cmd_get_history_gifs(ctx):
    print("[CMD] get_history_gifs from:", ctx.author.name)
    await ctx.message.reply("Starting gif search")

    if not ctx.author.id == 230698327589650432:
        ctx.message.reply("You are not allowed to use this command")
        return

    for channel in ctx.guild.channels:
        print("Checking channel: ", channel.name)
        if not isinstance(channel, discord.TextChannel):
            continue
        async for message in channel.history(limit=None):
            if message.author.bot:
                continue
            if message.attachments:
                if '.gif' in message.attachments[0].url.lower():
                    print("Found a attachment:", message.attachments[0].url, "from:", message.author.name, "Message ID:", message.id)
            if '.gif' in message.content.lower() or '-gif' in message.content.lower():
                print("Found a gif:", message.content, "from:", message.author.name, "Message ID:", message.id)
                gif_url = str(message.content)
                user_id = str(message.author.id)

                user_gifs_get = user_gifs.find_one({"user_id": str(user_id)})
                field_name = gif_url.replace(".", "_")

                if user_gifs_get is None:
                    print("User not in database, adding entry")
                    user_gifs.insert_one({"user_id": str(user_id), field_name: {"url": gif_url, "count": 1}})
                else:
                    if field_name not in user_gifs_get:
                        print("Gif not in user database, adding it")
                        user_gifs.update_one({"user_id": str(user_id)},
                                             {"$set": {field_name: {"url": gif_url, "count": 1}}})
                    else:
                        print("Gif in user database, incrementing count")
                        user_gifs.update_one({"user_id": str(user_id)}, {"$inc": {f"{field_name}.count": 1}})

    print("Completed .gif search!")
    await ctx.message.reply("Completed .gif search")


@bot.command(name='favorite_gifs')
async def favorite_gifs(ctx):
    print("[CMD] favorite_gifs from:", ctx.author.name)
    user_id = str(ctx.author.id)  # Convert user_id to string
    user_gifs_get = user_gifs.find_one({"user_id": user_id})
    print("User gifs get:", user_gifs_get)

    # Check if user data is present and contains gif entries
    if user_gifs_get and 'user_id' in user_gifs_get:
        gifs_data = {k: v for k, v in user_gifs_get.items() if k != '_id' and k != 'user_id'}

        # Check if there are any gifs in the user's data
        if gifs_data:
            sorted_gifs = sorted(gifs_data.items(), key=lambda x: x[1].get('count', 0), reverse=True)
            print("Sorted gifs:", sorted_gifs)

            top_gifs = sorted_gifs[:3]
            dict_gifs = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}

            for i in range(len(top_gifs)):
                gif_name, data = top_gifs[i]
                gifs_url = data.get('url', "")
                count = data.get('count', 0)

                # Create an embed for each gif
                embed = discord.Embed(
                    title=f"Your {dict_gifs[i + 1]} favorite gif",
                    description=f"**Count:** {count}",
                    color=0x00ff00
                )
                embed.set_image(url=gifs_url)
                await ctx.send(embed=embed)
        else:
            await ctx.send("No favorite gifs found.")
    else:
        await ctx.send("No user data found.")


def check_video_extension(message):
    if not message.attachments:
        return None
    url = message.attachments[0].url
    for extension in video_extensions:
        if extension in url:
            video_url = url.split(extension)[0] + extension
            return video_url
    return None


def get_random_message():
    all_messages = []
    for message in collection.find():
        all_messages.append(message)
    random_num = random.randint(0, len(all_messages)-1)
    return all_messages[random_num]


# Check if the TOKEN variable is set
if TOKEN is None:
    raise ValueError("TOKEN environment variable is not set in the .env file")
bot.run(TOKEN)

