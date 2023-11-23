import discord
from discord.ext import commands

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
YOUR_DEDICATED_CHANNEL_ID = 1177040595395547197
# Open as text file
bot_token = open("bot_token.txt", "r").read().splitlines()[0]

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")

@bot.event
async def on_raw_reaction_add(payload):
    channel_id = payload.channel_id
    message_id = payload.message_id
    guild_id = payload.guild_id

    # Adjust these values according to your requirements
    target_channel_id = YOUR_DEDICATED_CHANNEL_ID
    reaction_threshold = 1

    if channel_id == target_channel_id:
        return  # Ignore reactions in the dedicated channel

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)

    # Check if the message has surpassed the reaction threshold
    if len(message.reactions) >= reaction_threshold:
        # Get the dedicated channel
        target_channel = bot.get_channel(target_channel_id)

        # Send the message content and a link to the original message
        await target_channel.send(
            f"Message with ID {message.id} in {channel.mention} has surpassed {reaction_threshold} reactions:\n"
            f"{message.content}\n"
            f"[Jump to Message]({message.jump_url})"
        )

# Run the bot with your token
bot.run(bot_token)
