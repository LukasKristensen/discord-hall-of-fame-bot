from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands as discord_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
import commands
import events
import utils
import asyncio
import version

dev_test = os.getenv('DEV_TEST') == "True"
load_dotenv()
if dev_test:
    TOKEN = os.getenv('DEV_KEY')
    # mongo_uri = os.getenv('DEV_MONGO_URI')
else:
    TOKEN = os.getenv('KEY')
mongo_uri = os.getenv('MONGO_URI')
db_client = MongoClient(mongo_uri)
messages_processing = []
total_message_count = 0

bot = discord_commands.Bot(command_prefix="!", intents=discord.Intents.default() | discord.Intents(members=True))
tree = bot.tree
server_classes = {}
dev_user = 230698327589650432

#region Events
@bot.event
async def on_ready():
    global server_classes
    global total_message_count

    version.DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await events.bot_login(bot, tree)
    await utils.error_logging(bot, f"Logged in as {bot.user}")

    server_classes = utils.get_server_classes(db_client)
    new_server_classes_dict = await events.check_for_new_server_classes(bot, db_client)
    for key, value in new_server_classes_dict.items():
        server_classes[key] = value
    await utils.error_logging(bot, f"Loaded a total of {len(server_classes)} servers")

    if not dev_test:
        total_message_count = await events.historical_sweep(bot, db_client, server_classes)
        await utils.error_logging(bot, f"Loaded a total of {total_message_count} hall of fame messages in the database")
        await events.post_wrapped()

    print("Starting daily task")
    daily_task.start()

@tasks.loop(hours=24)
async def daily_task():
    try:
        print("Running daily task")
        await events.daily_task(bot, db_client, server_classes, dev_test)
        await utils.error_logging(bot, f"Daily task completed")
    except Exception as e:
        print(f"Error in daily_task: {e}")
        await utils.error_logging(bot, f"Error in daily_task: {e}")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    server_class = server_classes[payload.guild_id]
    collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_class.reaction_threshold
    post_due_date = server_class.post_due_date
    target_channel_id = server_class.hall_of_fame_channel_id
    check_for_msg_in_hof = server_class.allow_messages_in_hof_channel

    if not payload.message_id in messages_processing:
        messages_processing.append(payload.message_id)
        await events.on_raw_reaction_add(payload, bot, collection, temp_reaction_threshold, post_due_date, target_channel_id, check_for_msg_in_hof)
        messages_processing.remove(payload.message_id)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    server_class = server_classes[payload.guild_id]
    collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_class.reaction_threshold
    post_due_date = server_class.post_due_date
    target_channel_id = server_class.hall_of_fame_channel_id
    check_for_msg_in_hof = server_class.allow_messages_in_hof_channel

    if not payload.message_id in messages_processing:
        messages_processing.append(payload.message_id)
        await events.on_raw_reaction_remove(payload, bot, collection, temp_reaction_threshold, post_due_date, target_channel_id, check_for_msg_in_hof)
        messages_processing.remove(payload.message_id)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    server_class = server_classes[message.guild.id]
    target_channel_id = server_class.hall_of_fame_channel_id
    allow_messages_in_hof = server_class.allow_messages_in_hof_channel
    await events.on_message(message, bot, target_channel_id, allow_messages_in_hof)

@bot.event
async def on_guild_join(server):
    new_server_class = await events.guild_join(server, db_client)
    server_classes[server.id] = new_server_class
    await utils.error_logging(bot, f"Joined server {server.name} server_id: {server.id}")

@bot.event
async def on_guild_remove(server):
    await utils.error_logging(bot, f"Left server {server.name}", server.id)
    await events.guild_remove(server, db_client)
    server_classes.pop(server.id)

@bot.command(name="restart")
async def restart(payload):
    if payload.message.author.id != dev_user:
        await payload.message.channel.send("You are not authorized to use this command")
        return

    await utils.error_logging(bot, "Restarting the bot")
    await bot.close()

@tree.command(name="setup", description="Setup the bot for the server if it is not already [Owner Only]")
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
    await utils.error_logging(bot, f"Setup the bot for the server {interaction.guild.name}", interaction.guild.id)

@tree.command(name="get_random_message", description="Get a random message from the Hall of Fame database")
async def get_random_message(interaction: discord.Interaction):
    collection = db_client[str(interaction.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_classes[interaction.guild_id].reaction_threshold
    await commands.get_random_message(interaction, collection, bot, temp_reaction_threshold)
    await utils.error_logging(bot, f"Get random message command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="help", description="List of commands")
async def get_help(interaction: discord.Interaction):
    await commands.get_help(interaction)
    await utils.error_logging(bot, f"Help command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

# Disabled for now
async def manual_sweep(interaction: discord.Interaction, guild_id: str):
    if not await check_if_dev_user(interaction): return
    collection = db_client[guild_id]["hall_of_fame_messages"]

    guild_id = int(guild_id)
    temp_reaction_threshold = server_classes[guild_id].reaction_threshold
    post_due_date = server_classes[guild_id].post_due_date
    target_channel_id = server_classes[guild_id].hall_of_fame_channel_id
    check_for_msg_in_hof = server_classes[guild_id].allow_messages_in_hof_channel

    await commands.manual_sweep(interaction, int(guild_id), None, False, bot, collection,
                                temp_reaction_threshold, post_due_date, target_channel_id, dev_user, check_for_msg_in_hof)
    await utils.error_logging(bot, f"Manual sweep command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="reaction_threshold_configure", description="Configure the amount of reactions needed to post a message in the Hall of Fame [Owner Only]")
async def configure_bot(interaction: discord.Interaction, reaction_threshold: int):
    if not await check_if_server_owner(interaction): return

    completion = await commands.set_reaction_threshold(interaction, reaction_threshold, db_client)
    if completion:
        server_classes[interaction.guild_id].reaction_threshold = reaction_threshold
    await utils.error_logging(bot, f"Reaction threshold configure command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="feedback", description="Send feedback to the developer")
async def send_feedback(interaction: discord.Interaction):
    await utils.create_feedback_form(interaction, bot)

@tree.command(name="include_authors_reaction", description="Should the author's own reaction be included in the reaction threshold calculation? [Owner Only]")
async def include_author_own_reaction_in_threshold(interaction: discord.Interaction, include: bool):
    if not await check_if_server_owner(interaction): return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"include_author_in_reaction_calculation": include}})
    server_classes[interaction.guild_id].include_author_in_reaction_calculation = include
    await interaction.response.send_message(f"Author's own reaction included in the reaction threshold: {include}")
    await utils.error_logging(bot, f"Include author's own reaction in threshold command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)
    await asyncio.sleep(5)
    await interaction.delete_original_response()

@tree.command(name="allow_messages_in_hof_channel", description="Should people be allowed to send messages in the Hall of Fame channel? [Owner Only]")
async def allow_messages_in_hof_channel(interaction: discord.Interaction, allow: bool):
    if not await check_if_server_owner(interaction): return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"allow_messages_in_hof_channel": allow}})
    server_classes[interaction.guild_id].allow_messages_in_hof_channel = allow
    await interaction.response.send_message(f"People are allowed to send messages in the Hall of Fame channel: {allow}")
    await utils.error_logging(bot, f"Allow messages in Hall of Fame channel command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)
    await asyncio.sleep(5)
    await interaction.delete_original_response()

@tree.command(name="vote", description="Vote for the bot on top.gg")
async def vote(interaction: discord.Interaction):
    await interaction.response.send_message("Vote for the bot on top.gg: https://top.gg/bot/1177041673352663070/vote")
    await utils.error_logging(bot, f"Vote command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="custom_emoji_check_logic", description="Here you can decide if it only should be whitelisted emojis or all emojis")
@discord.app_commands.choices(
    config_option=[
        app_commands.Choice(name="All emojis", value="all_emojis"),
        app_commands.Choice(name="Only whitelisted emojis", value="whitelisted_emojis")
    ]
)
async def custom_emoji_check_logic(interaction: discord.Interaction, config_option: app_commands.Choice[str]):
    if not await check_if_server_owner(interaction): return
    custom_emoji_check = False
    if config_option.value == "whitelisted_emojis":
        custom_emoji_check = True

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"custom_emoji_check_logic": custom_emoji_check}})
    server_classes[interaction.guild_id].custom_emoji_check_logic = custom_emoji_check
    response = f"Custom emoji check logic set to {config_option.name}"
    if config_option.value == "whitelisted_emojis":
        response += "\n\nYou can now use the commands `/whitelist_emoji`, `/unwhitelist_emoji` and `/clear_whitelist` to manage the whitelist"
    await interaction.response.send_message(response)
    await utils.error_logging(bot, f"Custom emoji check logic command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="whitelist_emoji", description="Whitelist an emoji for the server if custom emoji check logic is enabled [Owner Only]")
async def whitelist_emoji(interaction: discord.Interaction, emoji: str):
    if not await check_if_server_owner(interaction): return

    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        await interaction.response.send_message("Custom emoji check logic is not enabled for this server")
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    whitelist = db['server_config'].find_one({"guild_id": interaction.guild_id})["whitelisted_emojis"]

    if emoji not in whitelist:
        whitelist.append(emoji)
        server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"whitelisted_emojis": whitelist}})
        server_class.whitelisted_emojis = whitelist
        await interaction.response.send_message(f"Emoji {emoji} added to the whitelist")
    else:
        await interaction.response.send_message(f"Emoji {emoji} is already in the whitelist")
    await utils.error_logging(bot, f"Whitelist emoji command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


@tree.command(name="unwhitelist_emoji", description="Unwhitelist an emoji for the server if custom emoji check logic is enabled [Owner Only]")
async def unwhitelist_emoji(interaction: discord.Interaction, emoji: str):
    if not await check_if_server_owner(interaction): return

    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        await interaction.response.send_message("Custom emoji check logic is not enabled for this server")
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    whitelist = db['server_config'].find_one({"guild_id": interaction.guild_id})["whitelisted_emojis"]

    if emoji in whitelist:
        whitelist.remove(emoji)
        server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"whitelisted_emojis": whitelist}})
        server_class.whitelisted_emojis = whitelist
        await interaction.response.send_message(f"Emoji {emoji} removed from the whitelist")
    else:
        await interaction.response.send_message(f"Emoji {emoji} is not in the whitelist")
    await utils.error_logging(bot, f"Unwhitelist emoji command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="clear_whitelist", description="Clear the whitelist for the server if custom emoji check logic is enabled [Owner Only]")
async def clear_whitelist(interaction: discord.Interaction):
    if not await check_if_server_owner(interaction): return
    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        await interaction.response.send_message("Custom emoji check logic is not enabled for this server")
        return
    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"whitelisted_emojis": []}})
    server_class.whitelisted_emojis = []
    await interaction.response.send_message("Whitelist cleared")
    await utils.error_logging(bot, f"Clear whitelist command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


@tree.command(name="get_server_config", description="Get the server config")
async def get_server_config(interaction: discord.Interaction):
    server_class = server_classes[interaction.guild_id]
    print("server_class: ", server_class)
    config_message = (
        f"**Server Configuration:**\n"
        f"```"
        f"Reaction Threshold: {server_class.reaction_threshold}\n"
        f"Post Validity (How many days back a post is considered valid): {server_class.post_due_date}\n"
        f"Allow Messages in HOF Channel: {server_class.allow_messages_in_hof_channel}\n"
        f"Include Author in Reaction Calculation: {server_class.include_author_in_reaction_calculation}\n"
        f"Custom Emoji Check Logic: {server_class.custom_emoji_check_logic}\n"
    )
    if server_class.custom_emoji_check_logic:
        config_message += f"Whitelisted Emojis: {', '.join(server_class.whitelisted_emojis)}\n"
    config_message += f"```"

    await interaction.response.send_message(config_message)
    await utils.error_logging(bot, f"Get server config command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="set_post_due_date", description="How many days ago should the post be to be considered old and not valid? [Owner Only]")
async def set_post_due_date(interaction: discord.Interaction, post_due_date: int):
    if not await check_if_server_owner(interaction): return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"post_due_date": post_due_date}})
    server_classes[interaction.guild_id].post_due_date = post_due_date
    await interaction.response.send_message(f"Post due date set to {post_due_date} days")
    await utils.error_logging(bot, f"Set post due date command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

@tree.command(name="invite", description="Invite the bot to your server")
async def invite(interaction: discord.Interaction):
    await interaction.response.send_message("Invite the bot to your server: https://discord.com/oauth2/authorize?client_id=1177041673352663070")
    await utils.error_logging(bot, f"Invite command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)

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

if __name__ == "__main__":
    # Check if the TOKEN variable is set
    if TOKEN is None or mongo_uri is None:
        raise ValueError("TOKEN environment variable is not set in the .env file")
    bot.run(TOKEN)
