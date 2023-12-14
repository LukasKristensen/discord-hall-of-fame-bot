import random
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
import message_reactions
import asyncio

load_dotenv()
TOKEN = os.getenv('KEY')

# Set up the MongoDB client
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['caroon']
collection = db['messages_sent']

iteration = 27
user_gifs = db['user_gifs'+str(iteration)]
server_gifs = db['server_gifs'+str(iteration)]

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
target_channel_id = 1176965358796681326
reaction_threshold = 8


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=discord.Streaming(name='!commands', url='https://github.com/LukasKristensen/discord-hall-of-fame-bot'))


@bot.event
async def on_raw_reaction_add(payload):
    channel_id = payload.channel_id
    message_id = payload.message_id

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
    print("[apply_reaction_checker]:", ctx.author.name)
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
    print("[get_random_message]:", ctx.author.name)
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
    print("[commands]:", ctx.author.name)
    embed = discord.Embed(
        title="Commands",
        color=0x00ff00
    )
    embed.add_field(name="!commands", value="List of commands", inline=False)
    embed.add_field(name="!favorite_gifs <user_id> <msg_limit:10>", value="Get the most popular gifs from a user", inline=False)
    embed.add_field(name="!server_gifs <msg_limit:10>", value="Get the most popular gifs in the server", inline=False)
    # embed.add_field(name="!apply_reaction_checker", value="Apply reaction checker to all messages in the server", inline=False)
    embed.add_field(name="!get_random_message", value="Get a random message from the database", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    await ctx.send(embed=embed)


video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm']


@bot.command(name='get_history_gifs')
async def cmd_get_history_gifs(ctx):
    print("[!get_history_gifs]:", ctx.author.name)
    msg = await ctx.message.reply("Starting gif search")
    gif_counter = 0

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
                    message.content = message.attachments[0].url
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
                if server_gifs.find_one({"url": gif_url}) is None:
                    server_gifs.insert_one({"url": gif_url, "count": 1})
                else:
                    server_gifs.update_one({"url": gif_url}, {"$inc": {"count": 1}})

                # Update amount of gifs found
                gif_counter += 1
                if gif_counter % 20 == 0:
                    await msg.edit(content=f"Starting gif search\nFound {gif_counter} gifs. Currently checking channel: {channel.name}")

    print("Completed .gif search!")
    await ctx.message.reply("Completed .gif search")


# Check if the user has posted a gif
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.attachments:
        if '.gif' in message.attachments[0].url.lower():
            message.content = message.attachments[0].url
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
        if server_gifs.find_one({"url": gif_url}) is None:
            server_gifs.insert_one({"url": gif_url, "count": 1})
        else:
            server_gifs.update_one({"url": gif_url}, {"$inc": {"count": 1}})
    # check if the message is sent in target_channel and the author is not a bot, if it is delete it
    if message.channel.id == target_channel_id and not message.author.bot:
        await message.delete()
        msg = await message.channel.send(f"Kun bot posts herinde {message.author.mention}") # mention user
        await asyncio.sleep(5)
        await msg.delete()
    await bot.process_commands(message)


@bot.command(name='favorite_gifs')
async def favorite_gifs(ctx):
    print("[!favorite_gifs]:", ctx.author.name)
    # Take in parameters for the user
    user_parameters = ctx.message.content.split(" ")

    if len(user_parameters) > 1 and len(user_parameters[1]) == 18 and user_parameters[1].isdigit():
        user_id = str(user_parameters[1])
    else:
        user_id = str(ctx.author.id)
    if len(user_parameters) > 2 and user_parameters[2].isdigit():
        msg_limit = int(user_parameters[2])
        msg_limit = 10 if msg_limit > 10 else msg_limit
    else:
        msg_limit = 5

    user_gifs_get = user_gifs.find_one({"user_id": user_id})

    # Check if user data is present and contains gif entries
    if user_gifs_get and 'user_id' in user_gifs_get:
        gifs_data = {k: v for k, v in user_gifs_get.items() if k != '_id' and k != 'user_id'}

        # Check if there are any gifs in the user's data
        if gifs_data:
            sorted_gifs = sorted(gifs_data.items(), key=lambda x: x[1].get('count', 0), reverse=True)
            top_gifs = sorted_gifs[:msg_limit]
            num_convert = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}

            for i in range(len(top_gifs)):
                gif_name, data = top_gifs[i]
                gifs_url = data.get('url', "")
                count = data.get('count', 0)

                embed = discord.Embed(
                    title=f"Your {num_convert[i + 1]} favorite gif",
                    description=f"**Count:** {count}",
                    color=0x00ff00
                )

                await ctx.send(embed=embed)
                await ctx.send(gifs_url)
        else:
            await ctx.send("No favorite gifs found.")
    else:
        await ctx.send("No user data found.")


@bot.command(name='server_gifs')
async def most_used_messages(ctx):
    print("[!server_gifs]:", ctx.author.name)
    user_parameters = ctx.message.content.split(" ")
    if len(user_parameters) > 1 and user_parameters[1].isdigit():
        msg_limit = int(user_parameters[1])
        msg_limit = 5 if msg_limit > 10 else msg_limit
    else:
        msg_limit = 5

    # Get the server's most used messages as sorted
    most_used_messages = server_gifs.find().sort("count", -1).limit(msg_limit)
    print("Most used messages:", most_used_messages)

    if most_used_messages:
        for i, message_data in enumerate(most_used_messages):
            print("Message data:", message_data)
            url = message_data.get('url', "")
            count = message_data.get('count', 0)

            num_convert = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}

            # Create an embed for each message
            embed = discord.Embed(
                title=f"{ctx.guild.name}'s {num_convert[i + 1]} most used gif",
                description=f"**Count:** {count}",
                color=0x00ff00
            )

            print("Sending url:", url)

            await ctx.send(embed=embed)
            await ctx.send(url)
    else:
        await ctx.send("No most used messages found.")


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

