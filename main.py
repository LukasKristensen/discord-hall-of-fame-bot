import random
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
from message_reactions import most_reactions, reaction_count_without_author
import asyncio
import llm_msg
import hof_wrapped
import datetime
from datetime import timezone

load_dotenv()
TOKEN = os.getenv('KEY')
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

# todo: Make dynamic for multiple servers
#       -   If opening up for multiple servers: create security measures to
#           validate that the origin of the message correlates to the server
#       -   Research topic: How reliable is the `guild_id` attribute of a message? Can it be spoofed?

db = client['caroon']
collection = db['hall_of_fame_messages']
server_config = db['server_config']
target_channel_id = 1176965358796681326 # Hall-Of-Fame (HOF) channel
reaction_threshold = 7
post_due_date = 28
llm_threshold = 0.99
dev_user = 230698327589650432

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.CustomActivity(name=f'{len([x for x in collection.find()])} Hall of Fame messages', type=5))
    await check_all_server_messages()
    await update_leaderboard()

    if datetime.datetime.now().month == 12 and datetime.datetime.now().day == 28:
        await hof_wrapped.main(bot.get_guild(323488126859345931), bot, reaction_threshold)


async def check_outlier(msg_content: str):
    """
    Checks whether a message is an outlier for a voting-based message
    :param msg_content:
    :return: boolean based on cut-off confidence from LLM
    """
    outlier_detection_confidence = llm_msg.check_hof_msg(str(msg_content))
    if outlier_detection_confidence > llm_threshold:
        bot_dev = bot.get_user(dev_user)
        await bot_dev.send(f'Outlier detected with confidence: {outlier_detection_confidence}. Msg: {str(msg_content)}')
        return True
    return False


async def validate_message(message):
    channel_id: int = message.channel_id
    message_id: int = message.message_id

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)

    if (datetime.datetime.now(timezone.utc) - message.created_at).days > post_due_date:
        return

    # Checks if the post is from the HOF channel or is from a bot
    if channel_id == target_channel_id or message.author.bot:
        return

    # Gets the adjusted reaction count corrected for not accounting the author
    corrected_reactions = await reaction_count_without_author(message)
    if corrected_reactions < reaction_threshold:
        if collection.find_one({"message_id": int(message_id)}):
            await remove_embed(message_id)
        return

    if await check_outlier(str(message.content)):
        return

    if collection.find_one({"message_id": int(message.id)}):
        collection.update_one({"message_id": int(message.id)},
                              {"$set": {"reaction_count": await reaction_count_without_author(message)}})
        await update_reaction_counter(message)
        return
    await post_hall_of_fame_message(message)

messages_processing = []


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if not payload.message_id in messages_processing:
        messages_processing.append(payload.message_id)
        await validate_message(payload)
        messages_processing.remove(payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if not payload.message_id in messages_processing:
        messages_processing.append(payload.message_id)
        await validate_message(payload)
        messages_processing.remove(payload.message_id)


async def update_reaction_counter(message: discord.Message):
    message_sent = collection.find_one({"message_id": int(message.id)})
    if not message_sent["hall_of_fame_message_id"]:
        return
    hall_of_fame_message_id = message_sent["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)

    embed = hall_of_fame_message.embeds[0]
    corrected_reactions = await reaction_count_without_author(message)

    embed.set_field_at(index=0, name=f"{corrected_reactions} Reactions ", value=most_reactions(message.reactions)[0].emoji, inline=True)
    await hall_of_fame_message.edit(embed=embed)


async def remove_embed(message_id: int):
    message = collection.find_one({"message_id": int(message_id)})
    if "hall_of_fame_message_id" not in message:
        return
    hall_of_fame_message_id = message["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)
    await hall_of_fame_message.edit(content="** **", embed=None)


async def update_leaderboard():
    most_reacted_messages = list(collection.find().sort("reaction_count", -1).limit(30))
    msg_id_array = server_config.find_one({"leaderboard_message_ids_updated": {"$exists": True}})

    # Update the reaction count of the top 30 most reacted messages
    for i in range(30):
        message = most_reacted_messages[i]
        channel = bot.get_channel(message["channel_id"])
        message = await channel.fetch_message(message["message_id"])
        collection.update_one({"message_id": int(message.id)},
                              {"$set": {"reaction_count": await reaction_count_without_author(message)}})

    # Updated all the reaction counts
    most_reacted_messages = list(collection.find().sort("reaction_count", -1).limit(20))

    # Update the embeds of the top 20 most reacted messages
    if msg_id_array:
        for i in range(20):
            hall_of_fame_channel = bot.get_channel(target_channel_id)
            hall_of_fame_message = await hall_of_fame_channel.fetch_message(msg_id_array["leaderboard_message_ids_updated"][i])
            original_channel = bot.get_channel(most_reacted_messages[i]["channel_id"])
            original_message = await original_channel.fetch_message(most_reacted_messages[i]["message_id"])

            await hall_of_fame_message.edit(embed=await create_embed(original_message))
            await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**")
            if original_message.attachments:
                await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**\n{original_message.attachments[0].url}")


@bot.command(name='manual_sweep')
async def cmd_manual_sweep(payload):
    if not payload.author.id == dev_user:
        payload.message.reply("You are not allowed to use this command")
        return
    sweep_limit = payload.message.content.split(" ")[1]
    guild_id = payload.message.content.split(" ")[2]
    await check_all_server_messages(guild_id, sweep_limit)

async def check_all_server_messages(guild_id = 323488126859345931, sweep_limit = 2000, sweep_limited=False):
    guild = bot.get_guild(guild_id)

    for channel in guild.channels:
        if not isinstance(channel, discord.TextChannel):
            continue # Ignore if the current channel is not a text channel
        async for message in channel.history(limit=sweep_limit):
            try:
                if message.author.bot:
                    continue  # Ignore messages from bots
                if (datetime.datetime.now(timezone.utc) - message.created_at).days > post_due_date:
                    break
                message_reactions = await reaction_count_without_author(message)

                if message_reactions >= reaction_threshold:
                    if collection.find_one({"message_id": int(message.id)}):
                        await update_reaction_counter(message)
                        if sweep_limited:
                            break  # if message is already in the database, no need to check further
                        else:
                            continue # if a total channel sweep is needed
                    if await check_outlier(str(message.content)):
                        continue # if the message is an outlier for a voting message ignore it
                    await post_hall_of_fame_message(message)
                elif message_reactions >= reaction_threshold-3:
                    if collection.find_one({"message_id": int(message.id)}):
                        await remove_embed(message.id)
            except Exception as e:
                print(f'An error occurred: {e}')


async def post_hall_of_fame_message(message: discord.Message):
    target_channel = bot.get_channel(target_channel_id)
    video_link = check_video_extension(message)

    if video_link:
        await target_channel.send(video_link)

    embed = await create_embed(message)
    hall_of_fame_message = await target_channel.send(embed=embed)

    collection.insert_one({"message_id": int(message.id),
                           "channel_id": int(message.channel.id),
                           "guild_id": int(message.guild.id),
                           "hall_of_fame_message_id": int(hall_of_fame_message.id),
                           "reaction_count": int(await reaction_count_without_author(message))})


async def create_embed(message: discord.Message):
    # Check if the message is a reply to another message
    if message.reference and not message.attachments:
        reference_message = await message.channel.fetch_message(message.reference.message_id)

        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=message.author.color
        )
        top_reaction = most_reactions(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)

        corrected_reactions = await reaction_count_without_author(message)
        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        if reference_message.attachments:
            # Author of the original message
            embed.add_field(name=f"{message.author.name}'s reply:", value=message.content, inline=False)

            # Replied message
            embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)
            embed.set_image(url=reference_message.attachments[0].url)
        else:
            # Author of the replied message
            embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)
            # Author of the original message
            embed.add_field(name=f"{message.author.name}'s reply:", value=message.content, inline=False)
        return embed

    # Include the reference message in the embed if the message has both a reference and attachments
    elif message.reference and message.attachments:
        reference_message = await message.channel.fetch_message(message.reference.message_id)

        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=message.author.color
        )

        top_reaction = most_reactions(message.reactions)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)

        corrected_reactions = await reaction_count_without_author(message)

        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        # Original message
        embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)

        # Reply message
        embed.add_field(name=f"{message.author.name}'s reply:", value=message.content, inline=False)

        attachment = message.attachments[0]
        if attachment.content_type and attachment.content_type.startswith('image'):
            embed.set_image(url=attachment.url)
        else:
            embed.add_field(name="Attachment", value=f"{attachment.url}", inline=False)
        return embed

    else:
        embed = discord.Embed(
            title=f"Message in <#{message.channel.id}> has surpassed {reaction_threshold} reactions",
            description=message.content,
            color=message.author.color
        )
        top_reaction = most_reactions(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        corrected_reactions = await reaction_count_without_author(message)
        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        return embed


@bot.command(name='get_random_message')
async def cmd_random_message(payload):
    sender_channel = payload.channel.id

    all_messages = [x for x in collection.find()]
    random_num = random.randint(0, len(all_messages)-1)
    random_msg = all_messages[random_num]

    msg_channel = bot.get_channel(int(random_msg["channel_id"]))
    message = await msg_channel.fetch_message(int(random_msg["message_id"]))
    target_channel = bot.get_channel(sender_channel)

    video_link = check_video_extension(message)
    if video_link:
        await target_channel.send(video_link)

    embed = await create_embed(message)
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
async def on_message(message: discord.Message):
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


# Check if the TOKEN variable is set
if TOKEN is None or mongo_uri is None:
    raise ValueError("TOKEN environment variable is not set in the .env file")
bot.run(TOKEN)

