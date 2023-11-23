import discord
from discord.ext import commands

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
YOUR_DEDICATED_CHANNEL_ID = 1177040595395547197
# Open as text file
bot_token = open("bot_token.txt", "r").read().splitlines()[0]

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


@bot.event
async def on_raw_reaction_add(payload):
    channel_id = payload.channel_id
    message_id = payload.message_id
    guild_id = payload.guild_id

    # Adjust these values according to your requirements
    target_channel_id = YOUR_DEDICATED_CHANNEL_ID
    reaction_threshold = 1  # Update the reaction threshold to 1

    if channel_id == target_channel_id:
        return  # Ignore reactions in the dedicated channel

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)

    # Check if the message has surpassed the reaction threshold
    if len(message.reactions) >= reaction_threshold and message.id not in sent_messages:
        # Get the dedicated channel
        target_channel = bot.get_channel(target_channel_id)

        # Find the first attachment (assuming it's an image or video)
        attachment_url = message.attachments[0].url if message.attachments else None

        # Send a simple message with the media link
        if attachment_url:
            await target_channel.send(f"{attachment_url}")

        # Fetch the member to access avatar_url
        member = await bot.get_guild(guild_id).fetch_member(message.author.id)

        # Create a custom embed
        embed = discord.Embed(
            title=f"Message with ID {message.id} in {channel.name} has surpassed {reaction_threshold} reactions",
            description=message.content,
            color=0x00ff00  # Green color, you can change this
        )

        # Add sender's username and avatar to the embed
        embed.set_author(name=member.name, icon_url=member.avatar.url)

        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        # Send the embed
        await target_channel.send(embed=embed)

        # Add the sent message ID to the set and the file
        sent_messages.add(message.id)
        with open(file_path, 'a') as file:
            file.write(f"{message.id}\n")

# Run the bot with your token
bot.run(bot_token)
