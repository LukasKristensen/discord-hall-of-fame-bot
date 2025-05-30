from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands as discord_commands
from discord.ext import tasks
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
import commands
import events
import utils
import version
from bot_stats import BotStats
import topgg_api
import os
from translations import messages

dev_test = os.getenv('DEV_TEST') == "True"
load_dotenv()
if dev_test:
    TOKEN = os.getenv('DEV_KEY')
    # mongo_uri = os.getenv('DEV_MONGO_URI')
else:
    TOKEN = os.getenv('KEY')
mongo_uri = os.getenv('MONGO_URI')
topgg_api_key = os.getenv('TOPGG_API_KEY')
db_client = MongoClient(mongo_uri)
messages_processing = []

bot = discord_commands.Bot(command_prefix="!", intents=discord.Intents.default() | discord.Intents(members=True))
tree = bot.tree
server_classes = {}
dev_user = 230698327589650432
bot_stats = BotStats()


# region Events
@bot.event
async def on_ready():
    global server_classes

    version.DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await events.bot_login(bot, tree)
    await utils.error_logging(bot, f"Logged in as {bot.user}", log_type="system")

    server_classes = await utils.get_server_classes(db_client, bot)
    new_server_classes_dict = await events.check_for_new_server_classes(bot, db_client)
    for key, value in new_server_classes_dict.items():
        server_classes[key] = value
    await utils.error_logging(bot, f"Loaded a total of {len(server_classes)} servers")
    await utils.error_logging(bot,f"Loaded a total of {bot_stats.total_messages} hall of fame messages in the database")
    if bot_stats.total_messages > 0:
        await bot.change_presence(activity=discord.CustomActivity(name=f'{bot_stats.total_messages} Hall of Fame messages', type=5))
    await events.post_wrapped()
    daily_task.start()


@tasks.loop(hours=24)
async def daily_task():
    await utils.error_logging(bot,"Running daily task")
    try:
        await events.daily_task(bot, db_client, server_classes, dev_test)
        await utils.error_logging(bot, f"Daily task completed")
    except Exception as e:
        await utils.error_logging(bot, f"Error in daily_task: {e}")
    await utils.error_logging(bot, f"Total messages in the database: {bot_stats.total_messages}")

    if not dev_test:
        db_client["bot_stats"]["total_messages"].insert_one(
            {"timestamp": datetime.now(),
             "total_messages": bot_stats.total_messages})
        db_client["bot_stats"]["server_count"].insert_one(
            {"timestamp": datetime.now(),
             "server_count": len(server_classes)})
    await post_topgg_stats()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    server_class = server_classes[payload.guild_id]
    collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]

    if payload.message_id not in messages_processing:
        messages_processing.append(payload.message_id)
        await events.on_raw_reaction(payload, bot, collection, server_class.reaction_threshold,
                                     server_class.post_due_date, server_class.hall_of_fame_channel_id,
                                     server_class.ignore_bot_messages)
        messages_processing.remove(payload.message_id)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    server_class = server_classes[payload.guild_id]
    collection = db_client[str(server_class.guild_id)]["hall_of_fame_messages"]

    if payload.message_id not in messages_processing:
        messages_processing.append(payload.message_id)
        await events.on_raw_reaction(payload, bot, collection, server_class.reaction_threshold,
                                     server_class.post_due_date, server_class.hall_of_fame_channel_id,
                                     server_class.ignore_bot_messages)
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
    new_server_class = await events.guild_join(server, db_client, bot)
    if new_server_class is None:
        return
    server_classes[server.id] = new_server_class
    await utils.error_logging(bot, f"Joined server {server.name}", server.id, log_type="system")
    await post_topgg_stats()


@bot.event
async def on_guild_remove(server):
    await utils.error_logging(bot, f"Left server {server.name}", server.id, log_type="system")
    await events.guild_remove(server, db_client)
    if server.id in server_classes:
        del server_classes[server.id]
    await post_topgg_stats()


@bot.command(name="restart")
async def restart(payload):
    if payload.message.author.id != dev_user:
        await payload.message.channel.send(messages.NOT_AUTHORIZED)
        return

    await utils.error_logging(bot, "Restarting the bot")
    await bot.close()


@tree.command(name="help", description="List of commands")
async def get_help(interaction: discord.Interaction):
    await commands.get_help(interaction)
    await utils.error_logging(bot, f"Help command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


# Disabled for now
async def manual_sweep(interaction: discord.Interaction):
    if not await check_if_user_has_manage_server_permission(interaction):
        return
    if interaction.guild_id == 1180006529575960616: return
    collection = db_client[str(interaction.guild_id)]["hall_of_fame_messages"]
    temp_reaction_threshold = server_classes[interaction.guild_id].reaction_threshold
    target_channel_id = server_classes[interaction.guild_id].hall_of_fame_channel_id

    await utils.error_logging(bot, f"Manual sweep command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)
    await commands.manual_sweep(interaction, interaction.guild_id, None, False, bot, collection,
                                temp_reaction_threshold, 36500, target_channel_id, False)


@tree.command(name="set_reaction_threshold", description="Configure the amount of reactions needed to post a message in the Hall of Fame")
async def configure_bot(interaction: discord.Interaction, reaction_threshold: int):
    if not await check_if_user_has_manage_server_permission(interaction):
        return
    if reaction_threshold < 1:
        reaction_threshold = 1

    completion = await commands.set_reaction_threshold(interaction, reaction_threshold, db_client)
    if completion:
        server_classes[interaction.guild_id].reaction_threshold = reaction_threshold
    await utils.error_logging(bot, f"Reaction threshold configure command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, reaction_threshold)


@tree.command(name="feedback", description="Send feedback to the developer")
async def send_feedback(interaction: discord.Interaction):
    await utils.create_feedback_form(interaction, bot)


@tree.command(name="include_authors_reaction", description="Should the author's own reaction be included in the reaction threshold calculation?")
async def include_author_own_reaction_in_threshold(interaction: discord.Interaction, include: bool):
    if not await check_if_user_has_manage_server_permission(interaction):
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id},
                             {"$set": {"include_author_in_reaction_calculation": include}})
    server_classes[interaction.guild_id].include_author_in_reaction_calculation = include
    await interaction.response.send_message(messages.AUTHOR_REACTION_INCLUDED.format(include=include))
    await utils.error_logging(bot, f"Include author's own reaction in threshold command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, include)


@tree.command(name="allow_messages_in_hof_channel", description="Should people be allowed to send messages in the Hall of Fame channel?")
async def allow_messages_in_hof_channel(interaction: discord.Interaction, allow: bool):
    if not await check_if_user_has_manage_server_permission(interaction):
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"allow_messages_in_hof_channel": allow}})
    server_classes[interaction.guild_id].allow_messages_in_hof_channel = allow
    await interaction.response.send_message(messages.ALLOW_POST_IN_HOF.format(allow=allow))
    await utils.error_logging(bot, f"Allow messages in Hall of Fame channel command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, allow)


@tree.command(name="vote", description="Vote for the bot on top.gg")
async def vote(interaction: discord.Interaction):
    await interaction.response.send_message(messages.VOTE_MESSAGE)
    await utils.error_logging(bot, f"Vote command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


@tree.command(name="custom_emoji_check_logic",
              description="Here you can decide if it only should be whitelisted emojis or all emojis")
@discord.app_commands.choices(
    config_option=[
        app_commands.Choice(name="All emojis", value="all_emojis"),
        app_commands.Choice(name="Only whitelisted emojis", value="whitelisted_emojis")
    ]
)
async def custom_emoji_check_logic(interaction: discord.Interaction, config_option: app_commands.Choice[str]):
    if not await check_if_user_has_manage_server_permission(interaction):
        return
    custom_emoji_check = False
    if config_option.value == "whitelisted_emojis":
        custom_emoji_check = True

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"custom_emoji_check_logic": custom_emoji_check}})
    server_classes[interaction.guild_id].custom_emoji_check_logic = custom_emoji_check
    response = f"Custom emoji check logic set to {config_option.name}"
    if config_option.value == "whitelisted_emojis":
        response += "\n\nYou can now use the commands </whitelist_emoji:1358208382473076849>, </unwhitelist_emoji:1358208382473076850> and </clear_whitelist:1358208382473076851> to manage the whitelist"
    await interaction.response.send_message(response)
    await utils.error_logging(bot, f"Custom emoji check logic command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, str(config_option.value))


@tree.command(name="whitelist_emoji", description="Whitelist an emoji for the server if custom emoji check logic is enabled")
async def whitelist_emoji(interaction: discord.Interaction, emoji: str):
    if not await check_if_user_has_manage_server_permission(interaction):
        return

    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        await interaction.response.send_message(messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    whitelist = db['server_config'].find_one({"guild_id": interaction.guild_id})["whitelisted_emojis"]

    if emoji not in whitelist:
        whitelist.append(emoji)
        server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"whitelisted_emojis": whitelist}})
        server_class.whitelisted_emojis = whitelist
        await interaction.response.send_message(messages.WHITELIST_ADDED.format(emoji=emoji))
    else:
        await interaction.response.send_message(messages.WHITELIST_ALREADY_EXISTS.format(emoji=emoji))
    await utils.error_logging(bot, f"Whitelist emoji command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, emoji)


@tree.command(
    name="unwhitelist_emoji",
    description="Unwhitelist an emoji for the server if custom emoji check logic is enabled")
async def unwhitelist_emoji(interaction: discord.Interaction, emoji: str):
    if not await check_if_user_has_manage_server_permission(interaction):
        return

    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        await interaction.response.send_message(messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    whitelist = db['server_config'].find_one({"guild_id": interaction.guild_id})["whitelisted_emojis"]

    if emoji in whitelist:
        whitelist.remove(emoji)
        server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"whitelisted_emojis": whitelist}})
        server_class.whitelisted_emojis = whitelist
        await interaction.response.send_message(messages.WHITELIST_REMOVED.format(emoji=emoji))
    else:
        await interaction.response.send_message(messages.WHITELIST_NOT_FOUND.format(emoji=emoji))
    await utils.error_logging(bot, f"Unwhitelist emoji command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, emoji)


@tree.command(name="clear_whitelist", description="Clear the whitelist for the server if custom emoji check logic is enabled")
async def clear_whitelist(interaction: discord.Interaction):
    if not await check_if_user_has_manage_server_permission(interaction):
        return
    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        await interaction.response.send_message(messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return
    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"whitelisted_emojis": []}})
    server_class.whitelisted_emojis = []
    await interaction.response.send_message(messages.WHITELIST_CLEARED)
    await utils.error_logging(bot, f"Clear whitelist command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


@tree.command(name="get_server_config", description="Get the server config")
async def get_server_config(interaction: discord.Interaction):
    server_class = server_classes[interaction.guild_id]
    config_message = messages.SERVER_CONFIG.format(
        reaction_threshold=server_class.reaction_threshold,
        allow_messages_in_hof_channel=server_class.allow_messages_in_hof_channel,
        include_author_in_reaction_calculation=server_class.include_author_in_reaction_calculation,
        custom_emoji_check_logic=server_class.custom_emoji_check_logic,
        ignore_bot_messages=server_class.ignore_bot_messages,
        post_due_date=server_class.post_due_date,
        whitelisted_emojis=', '.join(server_class.whitelisted_emojis) if server_class.custom_emoji_check_logic else ''
    )
    if server_class.custom_emoji_check_logic:
        config_message += f"Whitelisted Emojis: {', '.join(server_class.whitelisted_emojis)}\n"
    config_message += f"```"

    await interaction.response.send_message(config_message)
    await utils.error_logging(bot, f"Get server config command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


@tree.command(
    name="set_post_due_date",
    description="How many days ago should the post be to be considered old and not valid?")
async def set_post_due_date(interaction: discord.Interaction, post_due_date: int):
    if not await check_if_user_has_manage_server_permission(interaction):
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"post_due_date": post_due_date}})
    server_classes[interaction.guild_id].post_due_date = post_due_date
    await interaction.response.send_message(messages.POST_DUE_DATE_SET.format(post_due_date=post_due_date))
    await utils.error_logging(bot, f"Set post due date command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, post_due_date)


@tree.command(name="invite", description="Invite the bot to your server")
async def invite(interaction: discord.Interaction):
    await interaction.response.send_message(messages.INVITE_MESSAGE)
    await utils.error_logging(bot, f"Invite command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id)


@tree.command(name="ignore_bot_messages", description="Should the bot ignore messages from other bots?")
async def ignore_bot_messages(interaction: discord.Interaction, should_ignore_bot_messages: bool):
    if not await check_if_user_has_manage_server_permission(interaction):
        return
    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"ignore_bot_messages": should_ignore_bot_messages}})
    server_classes[interaction.guild_id].ignore_bot_messages = should_ignore_bot_messages
    await interaction.response.send_message(messages.IGNORE_BOT_MESSAGES.format(should_ignore_bot_messages=should_ignore_bot_messages))
    await utils.error_logging(bot, f"Ignore bot messages command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, should_ignore_bot_messages)


@tree.command(name="calculation_method", description="Set the calculation method for reactions")
@discord.app_commands.choices(
    config_option=[
        app_commands.Choice(name="Total Reactions", value="total"),
        app_commands.Choice(name="Unique Users", value="unique"),
        app_commands.Choice(name="Most Reacted Emoji", value="most_reacted")
    ]
)
async def calculation_method(interaction: discord.Interaction, method: app_commands.Choice[str]):
    if not await check_if_user_has_manage_server_permission(interaction):
        return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"reaction_count_calculation_method": method.value}})
    server_classes[interaction.guild_id].reaction_count_calculation_method = method.value
    await interaction.response.send_message(f"Reaction count calculation method set to {method.name}")
    await utils.error_logging(bot, f"Calculation method command used by {interaction.user.name} in {interaction.guild.name}", interaction.guild.id, method.value)

async def check_if_user_has_manage_server_permission(interaction: discord.Interaction):
    """
    Check if the user has manage server permission
    :param interaction:
    :return: True if the user has manage server permission
    """
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(messages.NOT_AUTHORIZED)
        await utils.error_logging(bot, f"User {interaction.user.name} does not have manage server permission", interaction.guild_id)
        return False
    if len(server_classes) > 1 and (interaction.guild_id not in server_classes or server_classes[interaction.guild_id] is None):
        await interaction.response.send_message(messages.ERROR_SERVER_NOT_SETUP)
        return False
    return True


async def check_if_dev_user(interaction: discord.Interaction):
    """
    Check if the user is a developer
    :param interaction:
    :return: True if the user is a developer
    """
    if interaction.user.id != dev_user:
        await interaction.response.send_message(messages.DEV_NOT_AUTHORIZED)
        await utils.error_logging(bot, f"User {interaction.user.name} is not a developer", interaction.guild_id)
        return False
    return True


async def post_topgg_stats():
    """
    Post the bot stats to top.gg
    """
    if not dev_test:
        topgg_response = topgg_api.post_bot_stats(len(bot.guilds), topgg_api_key)
        await utils.error_logging(bot, f"Posted bot stats to top.gg: {topgg_response[0]} - {topgg_response[1]}")

if __name__ == "__main__":
    # Check if the TOKEN variable is set
    if TOKEN is None or mongo_uri is None:
        raise ValueError("TOKEN environment variable is not set in the .env file")
    bot.run(TOKEN)
