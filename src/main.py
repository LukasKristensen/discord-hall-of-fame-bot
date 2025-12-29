from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands as discord_commands
from discord.ext import tasks
from dotenv import load_dotenv
import commands
import events
import utils
from constants import version
from enums import command_refs, log_type, calculation_method_type
from classes.bot_stats import BotStats
from api_services import topgg_api, discordbotlist_api
import os
from translations import messages
import psycopg2
from psycopg2 import pool
from repositories import server_config_repo, hall_of_fame_message_repo, server_user_repo, hof_wrapped_repo
import hof_wrapped
from contextlib import asynccontextmanager

load_dotenv()
dev_test = os.getenv('DEV_TEST') == "True"
if dev_test:
    TOKEN = os.getenv('DEV_KEY')
else:
    TOKEN = os.getenv('KEY')
topgg_api_key = os.getenv('TOPGG_API_KEY')

"""
connection = psycopg2.connect(host=os.getenv('POSTGRES_HOST'),
                              database=os.getenv('POSTGRES_DB'),
                              user=os.getenv('POSTGRES_USER'),
                              password=os.getenv('POSTGRES_PASSWORD'))
"""

connection_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    host=os.getenv('POSTGRES_HOST'),
    database=os.getenv('POSTGRES_DB'),
    user=os.getenv('POSTGRES_USER'),
    password=os.getenv('POSTGRES_PASSWORD'))

messages_processing = []
daily_command_cooldowns = {}

intents = discord.Intents.default()
intents.message_content = True
bot = discord_commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree
server_classes = {}
dev_user = 230698327589650432  # todo: put in env variable
bot_stats = BotStats()

month_emoji = "<:month_most_hof_messages:1380272332609683517>" if not dev_test else "<:month_most_hof_messages:1380272983368532160>"
all_time_emoji = "<:all_time_most_hof_messages:1380272422842007622>" if not dev_test else "<:all_time_most_hof_messages:1380272953098244166>"


@asynccontextmanager
async def get_db_connection(connection_pool):
    conn = connection_pool.getconn()
    try:
        try:
            yield conn
            conn.commit()
        except Exception as e:
            await utils.logging(bot, f"Database error: {e}", log_level=log_type.CRITICAL)
            raise
    finally:
        connection_pool.putconn(conn)

@bot.event
async def on_ready():
    global server_classes

    version.DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await events.bot_login(bot, tree)
    await utils.logging(bot, f"Logged in as {bot.user}", log_level=log_type.SYSTEM)

    async with get_db_connection(connection_pool) as connection:
        server_classes = server_config_repo.get_server_classes(connection)
        new_server_classes_dict = await events.check_for_new_server_classes(bot, connection)

    for key, value in new_server_classes_dict.items():
        server_classes[key] = value
    await utils.logging(bot, f"Loaded a total of {len(server_classes)} servers")
    await bot.change_presence(activity=discord.CustomActivity(name=f'🏆 Hall of Fame - {sum(server.member_count for server in bot.guilds)} users', type=5))

    await events.post_wrapped()
    daily_task.start()

@tasks.loop(hours=24)
async def daily_task():
    await utils.logging(bot, "Running daily task")
    try:
        async with get_db_connection(connection_pool) as connection:
            await events.daily_task(bot, connection, server_classes, dev_test)
        await utils.logging(bot, f"Daily task completed")
    except Exception as e:
        await utils.logging(bot, f"Error in daily_task: {e}")

    daily_command_cooldowns.clear()
    total_server_members = sum(server.member_count for server in bot.guilds)
    await bot.change_presence(activity=discord.CustomActivity(name=f'🏆 Hall of Fame - {total_server_members} users', type=5))
    await post_api_bot_stats()

def setup_databases(connection):
    print("Setting up databases...")
    print("Creating server config table...")
    server_config_repo.create_server_config_table(connection)
    print("Creating hall of fame message table...")
    hall_of_fame_message_repo.create_hall_of_fame_message_table(connection)
    print("Creating server user table...")
    server_user_repo.create_server_user_table(connection)
    print("Creating hof wrapped table...")
    hof_wrapped_repo.create_hof_wrapped_table(connection)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id not in server_classes:
        return
    try:
        server_class = server_classes[payload.guild_id]

        if payload.message_id not in messages_processing:
            messages_processing.append(payload.message_id)
            async with get_db_connection(connection_pool) as connection:
                await events.on_raw_reaction(payload, bot, connection, server_class.reaction_threshold,
                                             server_class.post_due_date, server_class.hall_of_fame_channel_id,
                                             server_class.ignore_bot_messages, server_class.hide_hof_post_below_threshold)
            messages_processing.remove(payload.message_id)
    except Exception as e:
        await utils.logging(bot, f"Error in on_raw_reaction_add: {e}", payload.guild_id)
        if payload.message_id in messages_processing:
            messages_processing.remove(payload.message_id)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id not in server_classes:
        return
    try:
        server_class = server_classes[payload.guild_id]

        if payload.message_id not in messages_processing:
            messages_processing.append(payload.message_id)
            async with get_db_connection(connection_pool) as connection:
                await events.on_raw_reaction(payload, bot, connection, server_class.reaction_threshold,
                                             server_class.post_due_date, server_class.hall_of_fame_channel_id,
                                             server_class.ignore_bot_messages, server_class.hide_hof_post_below_threshold)
            messages_processing.remove(payload.message_id)
    except Exception as e:
        await utils.logging(bot, f"Error in on_raw_reaction_remove: {e}", payload.guild_id)
        if payload.message_id in messages_processing:
            messages_processing.remove(payload.message_id)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.guild is None or message.guild.id not in server_classes:
        return
    try:
        server_class = server_classes[message.guild.id]
        target_channel_id = server_class.hall_of_fame_channel_id
        allow_messages_in_hof = server_class.allow_messages_in_hof_channel
        await events.on_message(message, target_channel_id, allow_messages_in_hof)
    except Exception as e:
        await utils.logging(bot, f"Error in on_message: {e}", message.guild.id)

@bot.event
async def on_guild_join(server):
    await utils.logging(bot, f"Joined server {server.name}", server.id, log_level=log_type.SYSTEM)
    await utils.post_server_perms(bot, server)

    try:
        async with get_db_connection(connection_pool) as connection:
            server_config_repo.insert_server_config(connection, server.id)
    except Exception as e:
        await utils.logging(bot, f"Error in on_guild_join: {e}", server.id, log_level=log_type.ERROR)
        return

    new_server_class = await events.guild_join(server, connection, bot)
    if new_server_class is None:
        return
    server_classes[server.id] = new_server_class
    await post_api_bot_stats()

@bot.event
async def on_guild_remove(server):
    # Case where discord sends a guild remove event for a server which has already been removed
    if server_classes is None or server.id not in server_classes:
        return
    await utils.logging(bot, f"Left server {server.name}", server.id, log_level=log_type.SYSTEM)
    async with get_db_connection(connection_pool) as connection:
        await events.guild_remove(server, connection)
    if server.id in server_classes:
        del server_classes[server.id]
    await post_api_bot_stats()

@tree.command(name="help", description="List of commands")
async def get_help(interaction: discord.Interaction):
    if not bot_is_loaded():
        return

    await commands.get_help(interaction)
    await utils.logging(bot, f"Help command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="set_reaction_threshold", description="Configure the amount of reactions needed to post a message in the Hall of Fame")
async def configure_bot(interaction: discord.Interaction, reaction_threshold: int):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return
    reaction_threshold = reaction_threshold if reaction_threshold > 0 else 1

    async with get_db_connection(connection_pool) as connection:
        await commands.set_reaction_threshold(interaction, reaction_threshold, connection)
    server_classes[interaction.guild_id].reaction_threshold = reaction_threshold
    await utils.logging(bot, f"Reaction threshold configure command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, reaction_threshold, log_level=log_type.COMMAND)

@tree.command(name="feedback", description="Send feedback to the developer")
async def send_feedback(interaction: discord.Interaction):
    await utils.create_feedback_form(interaction, bot)

@tree.command(name="include_authors_reaction", description="Should the author's own reaction be included in the reaction threshold calculation?")
async def include_author_own_reaction_in_threshold(interaction: discord.Interaction, include: bool):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return
    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "include_author_in_reaction_calculation", include, connection)
    server_classes[interaction.guild_id].include_author_in_reaction_calculation = include
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.AUTHOR_REACTION_INCLUDED.format(include=include))
    await utils.logging(bot, f"Include author's own reaction in threshold command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, include, log_level=log_type.COMMAND)

@tree.command(name="allow_messages_in_hof_channel", description="Should people be allowed to send messages in the Hall of Fame channel?")
async def allow_messages_in_hof_channel(interaction: discord.Interaction, allow: bool):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "allow_messages_in_hof_channel", allow, connection)
    server_classes[interaction.guild_id].allow_messages_in_hof_channel = allow
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.ALLOW_POST_IN_HOF.format(allow=allow))
    await utils.logging(bot, f"Allow messages in Hall of Fame channel command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, allow, log_level=log_type.COMMAND)

@tree.command(name="vote", description="Vote for the bot on top.gg")
async def vote(interaction: discord.Interaction):
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.VOTE_MESSAGE)
    await utils.logging(bot, f"Vote command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="custom_emoji_check_logic",
              description="Here you can decide if it only should be whitelisted emojis or all emojis")
@discord.app_commands.choices(
    config_option=[
        app_commands.Choice(name="All emojis", value="all_emojis"),
        app_commands.Choice(name="Only whitelisted emojis", value="whitelisted_emojis")
    ]
)
async def custom_emoji_check_logic(interaction: discord.Interaction, config_option: app_commands.Choice[str]):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    custom_emoji_check = False
    if config_option.value == "whitelisted_emojis":
        custom_emoji_check = True

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "custom_emoji_check_logic", custom_emoji_check, connection)
    server_classes[interaction.guild_id].custom_emoji_check_logic = custom_emoji_check

    response = f"Custom emoji check logic set to {config_option.name}"
    if config_option.value == "whitelisted_emojis":
        response += f"\n\nYou can now use the commands {command_refs.WHITELIST_EMOJI}, {command_refs.UNWHITELIST_EMOJI} and {command_refs.CLEAR_WHITELIST} to manage the whitelist"
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(response)
    await utils.logging(bot, f"Custom emoji check logic command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(config_option.value), log_level=log_type.COMMAND)

@tree.command(name="whitelist_emoji", description="Whitelist an emoji for the server if custom emoji check logic is enabled")
async def whitelist_emoji(interaction: discord.Interaction, emoji: str):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return

    if not emoji.startswith('<') and len(emoji) > 1:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.INVALID_EMOJI_FORMAT)
        return

    async with get_db_connection(connection_pool) as connection:
        whitelist = server_config_repo.get_parameter_value(connection, interaction.guild_id, "whitelisted_emojis")

        if emoji not in whitelist:
            whitelist.append(emoji)
            server_config_repo.update_server_config_param(interaction.guild_id, "whitelisted_emojis", whitelist, connection)
            server_class.whitelisted_emojis = whitelist
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.WHITELIST_ADDED.format(emoji=emoji))
        else:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.WHITELIST_ALREADY_EXISTS.format(emoji=emoji))
    await utils.logging(bot, f"Whitelist emoji command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, emoji, log_level=log_type.COMMAND)


@tree.command(
    name="unwhitelist_emoji",
    description="Unwhitelist an emoji for the server if custom emoji check logic is enabled")
async def unwhitelist_emoji(interaction: discord.Interaction, emoji: str):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return

    async with get_db_connection(connection_pool) as connection:
        whitelist = server_config_repo.get_parameter_value(connection, interaction.guild_id, "whitelisted_emojis")

        if emoji in whitelist:
            whitelist.remove(emoji)
            server_config_repo.update_server_config_param(interaction.guild_id, "whitelisted_emojis", whitelist, connection)
            server_class.whitelisted_emojis = whitelist
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.WHITELIST_REMOVED.format(emoji=emoji))
        else:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.WHITELIST_NOT_FOUND.format(emoji=emoji))
    await utils.logging(bot, f"Unwhitelist emoji command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, emoji, log_level=log_type.COMMAND)


@tree.command(name="clear_whitelist", description="Clear the whitelist for the server if custom emoji check logic is enabled")
async def clear_whitelist(interaction: discord.Interaction):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return
    server_class = server_classes[interaction.guild_id]
    if not server_class.custom_emoji_check_logic:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.CUSTOM_EMOJI_CHECK_DISABLED)
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "whitelisted_emojis", [], connection)
    server_class.whitelisted_emojis = []
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.WHITELIST_CLEARED)
    await utils.logging(bot, f"Clear whitelist command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="get_server_config", description="Get the server config")
async def get_server_config(interaction: discord.Interaction):
    if not bot_is_loaded():
        return

    server_class = server_classes[interaction.guild_id]
    config_message = messages.SERVER_CONFIG.format(
        reaction_threshold=server_class.reaction_threshold,
        allow_messages_in_hof_channel=server_class.allow_messages_in_hof_channel,
        include_author_in_reaction_calculation=server_class.include_author_in_reaction_calculation,
        custom_emoji_check_logic=server_class.custom_emoji_check_logic,
        ignore_bot_messages=server_class.ignore_bot_messages,
        post_due_date=server_class.post_due_date,
        calculation_method=server_class.reaction_count_calculation_method,
        hide_hof_post_below_threshold=server_class.hide_hof_post_below_threshold,
        whitelisted_emojis=', '.join(server_class.whitelisted_emojis) if server_class.custom_emoji_check_logic else ''
    )
    if server_class.custom_emoji_check_logic:
        config_message += f"Whitelisted Emojis: {', '.join(server_class.whitelisted_emojis)}\n"
    config_message += f"```"

    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(config_message)
    await utils.logging(bot, f"Get server config command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(
    name="set_post_due_date",
    description="How many days ago should the post be to be considered old and not valid?")
async def set_post_due_date(interaction: discord.Interaction, post_due_date: int):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "post_due_date", post_due_date, connection)
    server_classes[interaction.guild_id].post_due_date = post_due_date
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.POST_DUE_DATE_SET.format(post_due_date=post_due_date))
    await utils.logging(bot, f"Set post due date command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, post_due_date, log_level=log_type.COMMAND)

@tree.command(name="invite", description="Invite the bot to your server")
async def invite(interaction: discord.Interaction):
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.INVITE_MESSAGE)
    await utils.logging(bot, f"Invite command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="ignore_bot_messages", description="Should the bot ignore messages from other bots?")
async def ignore_bot_messages(interaction: discord.Interaction, should_ignore_bot_messages: bool):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "ignore_bot_messages", should_ignore_bot_messages, connection)
    server_classes[interaction.guild_id].ignore_bot_messages = should_ignore_bot_messages
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(messages.IGNORE_BOT_MESSAGES.format(should_ignore_bot_messages=should_ignore_bot_messages))
    await utils.logging(bot, f"Ignore bot messages command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, should_ignore_bot_messages, log_level=log_type.COMMAND)

@tree.command(name="calculation_method", description="Set the calculation method for reactions")
@discord.app_commands.choices(
    method=[
        app_commands.Choice(name="reaction_count = Most reactions on an emoji (default, recommended)", value=calculation_method_type.MOST_REACTIONS_ON_EMOJI),
        app_commands.Choice(name="reaction_count = Total reactions", value=calculation_method_type.TOTAL_REACTIONS),
        app_commands.Choice(name="reaction_count = How many users reacted", value=calculation_method_type.UNIQUE_USERS)
    ]
)
async def calculation_method(interaction: discord.Interaction, method: app_commands.Choice[str]):
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "reaction_count_calculation_method", method.value, connection)
    server_classes[interaction.guild_id].reaction_count_calculation_method = method.value
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(f"Reaction count calculation method set to {method.name}")
    await utils.logging(bot, f"Calculation method command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, method.value, log_level=log_type.COMMAND)

@tree.command(name="hide_hof_post_below_threshold", description="Should hall of fame posts be hidden when they go below the reaction threshold?")
async def hide_hall_of_fame_posts_when_they_are_below_threshold(interaction: discord.Interaction, hide: bool):
    """
    Hide hall of fame posts when they are below the threshold
    :param interaction:
    :param hide: True to hide, False to not hide
    :return:
    """
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction):
        return

    async with get_db_connection(connection_pool) as connection:
        server_config_repo.update_server_config_param(interaction.guild_id, "hide_hof_post_below_threshold", hide, connection)
    server_classes[interaction.guild_id].hide_hof_post_below_threshold = hide
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(f"Hide hall of fame posts when they are below the threshold set to {hide}")
    await utils.logging(bot, f"Hide hall of fame posts command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(hide), log_level=log_type.COMMAND)

@tree.command(name="user_profile", description="Get the server profile of a user")
async def user_server_profile(interaction: discord.Interaction, specific_user: discord.User = None):
    """
    Get the server profile of a user
    :param interaction: The interaction object
    :param specific_user: The user to get the profile of, defaults to the interaction user
    :return: The server profile of the user
    """
    if not bot_is_loaded():
        return

    user = specific_user or interaction.user
    async with get_db_connection(connection_pool) as connection:
        user_stats = server_user_repo.get_server_user(connection, user.id, interaction.guild_id)

    if user_stats is None:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.PROFILE_NO_DATA)
        await utils.logging(bot, f"User server profile command used by {interaction.user.name} in {interaction.guild.name} but no data available for user {user.name}",
                            interaction.guild.id, str(user.id), log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        await commands.user_server_profile(interaction, user, user_stats, connection, month_emoji, all_time_emoji)
    await utils.logging(bot, f"Get user server profile command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(user.id), log_level=log_type.COMMAND)

@tree.command(name="leaderboard", description="Get the server leaderboard")
async def leaderboard(interaction: discord.Interaction):
    """
    Get the server leaderboard
    :param interaction: The interaction object
    :return: The server stats
    """
    if not bot_is_loaded():
        return

    if interaction.guild_id not in server_classes:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.ERROR_SERVER_NOT_SETUP)
        return

    async with get_db_connection(connection_pool) as connection:
        user_stat = server_user_repo.get_server_user(connection, interaction.user.id, interaction.guild_id)
        if not user_stat:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.LEADERBOARD_NO_DATA)
            await utils.logging(bot, f"Leaderboard command used by {interaction.user.name} in {interaction.guild.name} but no data available",
                                interaction.guild.id, log_level=log_type.COMMAND)
            return

        if interaction.user.id in daily_command_cooldowns and "leaderboard" in daily_command_cooldowns[interaction.user.id]:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(messages.COMMAND_ON_COOLDOWN)
            await utils.logging(bot, f"Leaderboard command on cooldown for {interaction.user.name} in {interaction.guild.name}",
                                interaction.guild.id, log_level=log_type.COMMAND)
            return

        if interaction.user.id not in daily_command_cooldowns:
            daily_command_cooldowns[interaction.user.id] = []
        daily_command_cooldowns[interaction.user.id].append("leaderboard")

        try:
            await commands.server_leaderboard(interaction, connection, month_emoji, all_time_emoji)
        except Exception as e:
            await utils.logging(bot, f"Error in leaderboard command: {e}", interaction.guild_id)
            return

    await utils.logging(bot, f"Leaderboard command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, log_level=log_type.COMMAND)

@tree.command(name="set_hall_of_fame_channel", description="Manually set the Hall of Fame channel for the server")
async def set_hall_of_fame_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """
    Set the Hall of Fame channel for the server
    :param interaction: The interaction object
    :param channel: The channel to set as the Hall of Fame channel
    """
    if not bot_is_loaded():
        return

    if not await check_if_user_has_manage_server_permission(interaction, False):
        return

    missing_permissions = []
    if not channel.permissions_for(interaction.guild.me).send_messages:
        missing_permissions.append("Send Messages")
    if not channel.permissions_for(interaction.guild.me).view_channel:
        missing_permissions.append("View Channel")
    if not channel.permissions_for(interaction.guild.me).read_message_history:
        missing_permissions.append("Read Message History")
    if missing_permissions:
        await interaction.response.send_message(f"Failed to set Hall of Fame channel. In {channel.mention}, the bot is missing the following permissions for the channel: {', '.join(missing_permissions)}")
        await utils.logging(bot, f"Failed to set Hall of Fame channel due to missing permissions by {interaction.user.name} in "
                                 f"{interaction.guild.name} with missing permissions: {', '.join(missing_permissions)}",
                                 interaction.guild.id, str(channel.id), log_level=log_type.COMMAND)
        return

    async with get_db_connection(connection_pool) as connection:
        if interaction.guild_id not in server_classes or server_classes[interaction.guild_id] is None:
            new_server_class = await events.guild_join(interaction.guild, connection, bot, channel)
            if new_server_class is None:
                return
            server_classes[interaction.guild_id] = new_server_class
        else:
            server_class = server_classes[interaction.guild_id]
            server_class.hall_of_fame_channel_id = channel.id

        server_config_repo.update_server_config_param(interaction.guild_id, "hall_of_fame_channel_id", channel.id, connection)

    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(f"Hall of Fame channel set to {channel.mention}")
    await utils.logging(bot, f"Set Hall of Fame channel command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(channel.id), log_level=log_type.COMMAND)

@tree.command(name="hof_wrapped", description="Get your Hall of Fame Wrapped for the year")
async def hof_wrapped_command(interaction: discord.Interaction):
    if not bot_is_loaded():
        return

    if not (interaction.guild_id in server_classes and server_classes[interaction.guild_id] is not None):
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message("Server is not set up for Hall of Fame yet.")
        return

    async with get_db_connection(connection_pool) as connection:
        user_wrapped = hof_wrapped_repo.get_hof_wrapped(connection, interaction.guild_id, interaction.user.id, version.WRAPPED_YEAR)
    if user_wrapped is None:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message("No Hall of Fame Wrapped data available for you this year. Participate more in Hall of Fame to get your wrapped next year!")
        await utils.logging(bot, f"HOF Wrapped command used by {interaction.user.name} in {interaction.guild.name} but no data available",
                            interaction.guild.id, str(interaction.user.id), log_level=log_type.COMMAND)
        return

    embed = await hof_wrapped.create_embed(interaction.user, user_wrapped, bot)
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed)

    await utils.logging(bot, f"HOF Wrapped command used by {interaction.user.name} in {interaction.guild.name}",
                        interaction.guild.id, str(interaction.user.id), log_level=log_type.COMMAND)

@tree.command(name="server_hof_wrapped", description="Get your Hall of Fame Wrapped for the year")
async def server_hof_wrapped_command(interaction: discord.Interaction):
    if not bot_is_loaded():
        return

    if not (interaction.guild_id in server_classes and server_classes[interaction.guild_id] is not None):
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message("Server is not set up for Hall of Fame yet.")
        return

    async with get_db_connection(connection_pool) as connection:
        all_users_wrapped = hof_wrapped_repo.get_all_hof_wrapped_for_guild(connection, interaction.guild_id,  version.WRAPPED_YEAR)
    embed = hof_wrapped.create_server_embed(interaction.guild, all_users_wrapped)
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed)

# Command disabled for now due to few customization requests
"""
@tree.command(name="request_to_set_bot_profile", description="Request to set a custom bot profile picture and cover")
async def set_bot_profile_picture(interaction: discord.Interaction, image_url: str = None, cover_url: str = None):
    if not await check_if_user_has_manage_server_permission(interaction):
        return
    await utils.create_custom_profile_picture_and_cover_form(interaction, bot, image_url, cover_url)
"""

def bot_is_loaded():
    """
    Check if the bot has loaded
    :return: True if the bot has loaded
    """
    if len(server_classes) <= 1:
        return False
    return True

async def check_if_user_has_manage_server_permission(interaction: discord.Interaction, check_server_set_up: bool = True):
    """
    Check if the user has manage server permission
    :param interaction:
    :param check_server_set_up: Whether to check if the server is set up
    :return: True if the user has manage server permission
    """
    if not interaction.user.guild_permissions.manage_guild:
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.NOT_AUTHORIZED)
        await utils.logging(bot, f"User {interaction.user.name} does not have manage server permission",
                            interaction.guild_id, log_level=log_type.COMMAND)
        return False
    if check_server_set_up and len(server_classes) > 1 and (interaction.guild_id not in server_classes or server_classes[interaction.guild_id] is None):
        # noinspection PyUnresolvedReferences
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
        # noinspection PyUnresolvedReferences
        await interaction.response.send_message(messages.DEV_NOT_AUTHORIZED)
        await utils.logging(bot, f"User {interaction.user.name} is not a developer", interaction.guild_id,
                            log_level=log_type.COMMAND)
        return False
    return True

async def post_api_bot_stats():
    """
    Post the bot stats to the API services
    """
    if dev_test:
        return

    try:
        topgg_response = topgg_api.post_bot_stats(len(bot.guilds), topgg_api_key)
        await utils.logging(bot, f"Posted bot stats to top.gg: {topgg_response[0]} - {topgg_response[1]}")
    except Exception as e:
        await utils.logging(bot, f"Failed to post bot stats to top.gg: {e}")

    try:
        discordbotlist_response = discordbotlist_api.post_bot_stats(len(bot.guilds))
        await utils.logging(bot, f"Posted bot stats to discordbotlist.com: {discordbotlist_response[0]} - {discordbotlist_response[1]}")
    except Exception as e:
        await utils.logging(bot, f"Failed to post bot stats to discordbotlist.com: {e}")

if __name__ == "__main__":
    if TOKEN is None:
        raise ValueError("TOKEN environment variable is not set in the .env file")
    bot.run(TOKEN)
    connection_pool.closeall()
