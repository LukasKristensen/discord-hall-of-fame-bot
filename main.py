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
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

# Make dynamic for multiple servers
db = client['caroon']
collection = db['hall_of_fame_messages']
server_config = db['server_config']
target_channel_id = 1176965358796681326
reaction_threshold = 6


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.CustomActivity(name=f'{len([x for x in collection.find()])} Hall of Fame messages', type=5))
    await check_all_server_messages(None)


@bot.event
async def on_raw_reaction_remove(payload):
    if collection.find_one({"message_id": int(payload.message_id)}):
        message = await bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        collection.update_one({"message_id": int(message.id)}, {"$set": {"reaction_count": int(max(reaction.count for reaction in message.reactions))}})
        await update_reaction_counter(payload.message_id, payload.channel_id)


@bot.event
async def on_raw_reaction_add(payload):
    channel_id = payload.channel_id
    message_id = payload.message_id

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)

    if message.author.bot or channel_id == target_channel_id:
        return

    # Check if the message has surpassed the reaction threshold
    if any(reaction.count >= reaction_threshold for reaction in message.reactions):
        if collection.find_one({"message_id": int(message.id)}):
            collection.update_one({"message_id": int(message.id)}, {"$set": {"reaction_count": int(max(reaction.count for reaction in message.reactions))}})
            await update_reaction_counter(message_id, payload.channel_id)
            return
        await post_hall_of_fame_message(message)


async def update_reaction_counter(message_id, channel_id):
    message_sent = collection.find_one({"message_id": int(message_id)})
    if "hall_of_fame_message_id" not in message_sent:
        return
    hall_of_fame_message_id = message_sent["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)
    original_message = await bot.get_channel(channel_id).fetch_message(message_id)

    await hall_of_fame_message.edit(embed=create_embed(original_message))


async def update_leaderboard():
    most_reacted_messages = list(collection.find().sort("reaction_count", -1).limit(10))
    msg_id_array = server_config.find_one({"leaderboard_message_ids": {"$exists": True}})

    if msg_id_array:
        for i in range(10):
            hall_of_fame_channel = bot.get_channel(target_channel_id)
            hall_of_fame_message = await hall_of_fame_channel.fetch_message(msg_id_array["leaderboard_message_ids"][i])
            original_channel = bot.get_channel(most_reacted_messages[i]["channel_id"])
            original_message = await original_channel.fetch_message(most_reacted_messages[i]["message_id"])

            await hall_of_fame_message.edit(embed=create_embed(original_message))
            await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**")
            if original_message.attachments:
                await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**\n{original_message.attachments[0].url}")


@bot.command(name='apply_reaction_checker')
async def check_all_server_messages(payload=None):
    if payload is None:
        guild_id = 323488126859345931
        guild = bot.get_guild(guild_id)
    else:
        guild = payload.guild
        if not payload.author.id == 230698327589650432:
            payload.message.reply("You are not allowed to use this command")
            return

    try:
        for channel in guild.channels:
            if not isinstance(channel, discord.TextChannel):
                continue
            async for message in channel.history(limit=2000):
                if message.author.bot:
                    continue  # Ignore messages from bots

                if any(reaction.count >= reaction_threshold for reaction in message.reactions):
                    if collection.find_one({"message_id": int(message.id)}):
                        await update_reaction_counter(message.id, message.channel.id)
                        # continue # if a total channel sweep is needed
                        break  # if message is already in the database, no need to check further

                    await post_hall_of_fame_message(message)
    except Exception as e:
        print(f'An error occurred: {e}')


async def post_hall_of_fame_message(message):
    target_channel = bot.get_channel(target_channel_id)
    video_link = check_video_extension(message)

    if video_link:
        await target_channel.send(video_link)

    embed = create_embed(message)
    hall_of_fame_message = await target_channel.send(embed=embed)

    collection.insert_one({"message_id": int(message.id),
                           "channel_id": int(message.channel.id),
                           "guild_id": int(message.guild.id),
                           "hall_of_fame_message_id": int(hall_of_fame_message.id),
                           "reaction_count": int(max(reaction.count for reaction in message.reactions))})
    await update_leaderboard()


def create_embed(message):
    embed = discord.Embed(
        title=f"Message in #{message.channel.name} has surpassed {reaction_threshold} reactions",
        description=message.content,
        color=0x00ff00
    )
    most_reactions = message_reactions.most_reactions(message.reactions)

    embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
    if message.attachments:
        embed.set_image(url=message.attachments[0].url)
    embed.add_field(name=f"{most_reactions[0].count} Reactions ", value=most_reactions[0].emoji, inline=True)
    embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
    return embed


@bot.command(name='get_random_message')
async def cmd_random_message(payload):
    sender_channel = payload.channel.id
    random_msg = get_random_message()

    msg_channel = bot.get_channel(int(random_msg["channel_id"]))
    message = await msg_channel.fetch_message(int(random_msg["message_id"]))
    target_channel = bot.get_channel(sender_channel)

    video_link = check_video_extension(message)
    if video_link:
        await target_channel.send(video_link)

    embed = create_embed(message)
    await target_channel.send(embed=embed)


@bot.command(name='commands')
async def cmd_help(payload):
    embed = discord.Embed(
        title="Commands",
        color=0x00ff00
    )
    embed.add_field(name="!commands", value="List of commands", inline=False)
    embed.add_field(name="!get_random_message", value="Get a random message from the database", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    await payload.send(embed=embed)


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id == target_channel_id and not message.author.bot:
        await message.delete()
        msg = await message.channel.send(f"Kun bot posts herinde {message.author.mention}")
        await asyncio.sleep(5)
        await msg.delete()
    await bot.process_commands(message)


def check_video_extension(message):
    if not message.attachments:
        return None
    url = message.attachments[0].url

    for extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        if extension in url:
            video_url = url.split(extension)[0] + extension
            return video_url
    return None


def get_random_message():
    all_messages = [x for x in collection.find()]
    random_num = random.randint(0, len(all_messages)-1)
    return all_messages[random_num]


# Check if the TOKEN variable is set
if TOKEN is None or mongo_uri is None:
    raise ValueError("TOKEN environment variable is not set in the .env file")
bot.run(TOKEN)

