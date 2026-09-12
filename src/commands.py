import discord
import utils
from constants import version
from enums import command_refs
from repositories import server_config_repo, server_user_repo
from caches import ExpiringSet

async def get_help(interaction: discord.Interaction):
    """
    Command to get a list of commands
    :param interaction:
    :return:
    """
    embed = discord.Embed(
        title="Commands",
        color=0x00ff00
    )
    embed.add_field(name=command_refs.HELP, value="List of commands", inline=False)
    embed.add_field(name=command_refs.SET_REACTION_THRESHOLD, value="Set the amount of reactions needed for a post to reach hall of fame", inline=False)
    embed.add_field(name=command_refs.INCLUDE_AUTHORS_REACTION, value="Should the author of a message be included in the reaction count?", inline=False)
    embed.add_field(name=command_refs.ALLOW_MESSAGES_IN_HOF_CHANNEL, value="Allow anyone to type in the Hall of Fame channel", inline=False)
    embed.add_field(name=command_refs.CUSTOM_EMOJI_CHECK_LOGIC, value="Use only whitelisted emojis for the reaction count", inline=False)
    embed.add_field(name=command_refs.WHITELIST_EMOJI, value="Add a whitelisted emoji to the list [custom_emoji_check_logic]", inline=False)
    embed.add_field(name=command_refs.UNWHITELIST_EMOJI, value="Remove a whitelisted emoji from the list [custom_emoji_check_logic]", inline=False)
    embed.add_field(name=command_refs.CLEAR_WHITELIST, value="Clear the whitelist of emojis [custom_emoji_check_logic]", inline=False)
    embed.add_field(name=command_refs.GET_SERVER_CONFIG, value="Get the current bot configuration for the server", inline=False)
    embed.add_field(name=command_refs.IGNORE_BOT_MESSAGES, value="Should the bot ignore messages from other bots?", inline=False)
    embed.add_field(name=command_refs.HIDE_HOF_POST_BELOW_THRESHOLD, value="Should hall of fame posts be hidden when they go below the reaction threshold? (Will be visible again when they reach the threshold again)", inline=False)
    embed.add_field(name=command_refs.CALCULATION_METHOD, value="Change the calculation method for reactions", inline=False)
    embed.add_field(name=command_refs.SET_POST_DUE_DATE, value="Set how many days back a post is considered valid for reaching the Hall of Fame", inline=False)
    embed.add_field(name=command_refs.USER_PROFILE, value="Get the Hall of Fame profile for a user", inline=False)
    embed.add_field(name=command_refs.LEADERBOARD, value="Get the Hall of Fame leaderboard for the server", inline=False)
    embed.add_field(name=command_refs.SET_HALL_OF_FAME_CHANNEL, value="Manually set the Hall of Fame channel for the server", inline=False)
    embed.add_field(name=command_refs.FEEDBACK, value="Got a feature request or bug report? Let us know!", inline=False)
    embed.add_field(name=command_refs.VOTE_BOT, value="Support the bot by voting for it on top.gg: https://top.gg/bot/1177041673352663070/vote", inline=False)
    embed.add_field(name=command_refs.HOF_WRAPPED, value="Get your personal Hall of Fame wrap-up for the year", inline=False)
    embed.add_field(name=command_refs.SERVER_HOF_WRAPPED, value="Get the server's Hall of Fame wrap-up for the year", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Having trouble setting up the bot?", value="Make sure the bot has the correct permissions in the server or try to re-invite it", inline=False)
    embed.add_field(name="Need help?", value="Join the community server: https://discord.gg/r98WC5GHcn", inline=False)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    embed.add_field(name="Invite the bot", value="https://discord.com/oauth2/authorize?client_id=1177041673352663070", inline=False)
    embed.set_footer(text=f"Bot Version: {version.VERSION} - {version.DATE}")
    embed.set_image(url="https://raw.githubusercontent.com/LukasKristensen/discord-hall-of-fame-bot/refs/heads/main/Assets/reaction_calculation_methods_wide.jpg")
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=embed)


async def manual_sweep(interaction: discord.Interaction, guild_id: int, sweep_limit, sweep_limited: bool, bot: discord.Client,
                       collection, reaction_threshold: int, post_due_date: int, target_channel_id: int,
                       allow_messages_in_hof_channel: bool):
    """
    Command to manually sweep all messages in a server [DEV]
    :param interaction:
    :param guild_id:
    :param sweep_limit:
    :param sweep_limited:
    :param bot:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :param allow_messages_in_hof_channel:
    :return:
    """
    await utils.check_all_server_messages(int(guild_id), sweep_limit, sweep_limited, bot, collection, reaction_threshold, post_due_date, target_channel_id, allow_messages_in_hof_channel, interaction)


async def set_reaction_threshold(interaction: discord.Interaction, reaction_threshold: int, connection):
    """
    Command to set the reaction threshold for posting a message in the Hall of Fame
    :param interaction:
    :param reaction_threshold:
    :param connection:
    :return:
    """
    server_config_repo.update_server_config_param(interaction.guild.id, 'reaction_threshold', reaction_threshold, connection)
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(f"Reaction threshold set to {reaction_threshold}.\n"
                                            f"Note: The reaction threshold is based on the highest reaction count"
                                            f" of a single emoji per message.")


async def user_server_profile(interaction, user, user_stats, connection, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame profile for a user in a specific server
    :param interaction:
    :param user:
    :param user_stats:
    :param connection:
    :param month_emoji:
    :param all_time_emoji:
    :return:
    """
    user_has_most_this_month_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "this_month_hall_of_fame_messages")
    user_with_most_all_time_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "total_hall_of_fame_messages")

    embed = discord.Embed(
        title=f"📊 {user.name}'s Server Profile",
        description=f"Here are your stats for **{interaction.guild.name}**:",
        color=discord.Color.gold()
    )
    if user_has_most_this_month_hall_of_fame_messages and user_stats:
        embed.add_field(name=f"{month_emoji} **Monthly Hall of Fame Champion**",
                        value=f"**{user.name}** is the champion of this month's Hall of Fame with **{user_stats.get('this_month_hall_of_fame_messages', 0)}** messages!",
                        inline=False)
    if user_with_most_all_time_hall_of_fame_messages and user_stats:
        embed.add_field(name=f"{all_time_emoji} **All-Time Hall of Fame Champion**",
                        value=f"**{user.name}** is the all-time champion with **{user_stats.get('total_hall_of_fame_messages', 0)}** messages!",
                        inline=False)
    embed.add_field(name="", value="", inline=False)
    if user_stats:
        embed.add_field(name="🏆 **This Month's Hall of Fame Messages**",
                        value=f"**{user_stats.get('this_month_hall_of_fame_messages', 0)}** "
                              f"(Rank: {user_stats.get('monthly_message_rank', 'N/A')})", inline=False)
        embed.add_field(name="🌟 **Total Hall of Fame Messages**",
                        value=f"**{user_stats.get('total_hall_of_fame_messages', 0)}** "
                              f"(Rank: {user_stats.get('total_message_rank', 'N/A')})", inline=False)
        embed.add_field(name="💬 **Reactions Received This Month on Hall of Fame Messages**",
                        value=f"**{user_stats.get('this_month_hall_of_fame_message_reactions', 0)}** "
                              f"(Rank: {user_stats.get('monthly_reaction_rank', 'N/A')})", inline=False)
        embed.add_field(name="💬 **Total Reactions Received on Hall of Fame Messages**",
                        value=f"**{user_stats.get('total_hall_of_fame_message_reactions', 0)}** "
                              f"(Rank: {user_stats.get('total_reaction_rank', 'N/A')})", inline=False)
    else:
        embed.add_field(name="🏆 **This Month's Hall of Fame Messages**", value="**0**", inline=False)
        embed.add_field(name="", value="", inline=False)
        embed.add_field(name="🌟 **Total Hall of Fame Messages**", value="**0**", inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Note that this is calculated every 24 hours, so it may not be up to date.")
    await interaction.response.send_message(embed=embed)


async def server_leaderboard(interaction, connection, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame leaderboard for a server
    :param interaction:
    :param connection:
    :param month_emoji:
    :param all_time_emoji:
    :return:
    """
    # Defer the interaction response to prevent timeout
    await interaction.response.defer()

    embed = discord.Embed(
        title=f"📊 {interaction.guild.name} Hall of Fame Leaderboard",
        description="Here are the top users in this server:",
        color=discord.Color.blue()
    )

    # Consolidated Leaderboard
    leaderboard = ""

    # Top 5 This Month's Hall of Fame Messages
    top_monthly = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "this_month_hall_of_fame_messages", limit=5)
    leaderboard += f"{month_emoji} **Top 5 This Month's Hall of Fame Messages**\n"
    for rank, user in enumerate(top_monthly, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"

    # Top 5 All-Time Hall of Fame Messages
    top_all_time = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "total_hall_of_fame_messages", limit=5)
    leaderboard += f"\n{all_time_emoji} **Top 5 All-Time Hall of Fame Messages**\n"
    for rank, user in enumerate(top_all_time, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_messages', 0)} messages\n"

    # Top 5 This Month's Reactions
    top_monthly_reactions = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "this_month_hall_of_fame_message_reactions", limit=5)
    leaderboard += f"\n💬 **Top 5 This Month's Reactions**\n"
    for rank, user in enumerate(top_monthly_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"

    # Top 5 All-Time Reactions
    top_all_time_reactions = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "total_hall_of_fame_message_reactions", limit=5)
    leaderboard += f"\n💬 **Top 5 All-Time Reactions**\n"
    for rank, user in enumerate(top_all_time_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_message_reactions', 0)} reactions\n"

    embed.add_field(name="Leaderboard", value=leaderboard, inline=False)
    embed.set_footer(text="Note that this is calculated every 24 hours, so it may not be up to date.")
    await interaction.followup.send(embed=embed)


# A ping is answered at most once per channel in this window, so that it cannot be used to make the
# bot flood a channel
mention_cooldown_seconds = 30
recently_answered_mentions = ExpiringSet(ttl_seconds=mention_cooldown_seconds)


def is_bot_mention(message: discord.Message, bot_user) -> bool:
    """
    Decide whether a message is somebody pinging the bot to ask what it is.

    Deliberately narrow. A role ping or an @everyone is not addressed to the bot, a reply carries a
    mention of the author it is replying to, and a message that mentions the bot in passing is a
    conversation rather than a question. Answering any of those turns the bot into a nuisance.
    :param message: The message that was sent
    :param bot_user: The bot's own user
    :return: True when the message is a bare mention of the bot
    """
    if bot_user is None or message.author.bot:
        return False
    if not any(user.id == bot_user.id for user in message.mentions):
        return False
    if message.reference is not None:
        return False

    remaining = message.content
    for mention in (f"<@{bot_user.id}>", f"<@!{bot_user.id}>"):
        remaining = remaining.replace(mention, "")
    return remaining.strip() == ""


def build_bot_info_embed(guild, bot_user, server_config) -> discord.Embed:
    """
    The card the bot answers a ping with: what it is, how this server has it set up, and where to go
    :param guild: The server the ping came from
    :param bot_user: The bot's own user, for the thumbnail
    :param server_config: The server's configuration, or None when it has not been set up
    :return: The embed to send
    """
    embed = discord.Embed(
        title="🏆 Hall of Fame",
        description="Your server's best moments, and the members behind them. React to a message, "
                    "and once it passes the threshold it is reposted to the hall of fame channel "
                    "and credited to whoever posted it.\n\n"
                    "Landing there is meant to be worth something, so the bot keeps score: "
                    "leaderboards, member profiles and a yearly wrapped.",
        color=discord.Color.gold()
    )

    if server_config is not None:
        method = str(server_config.reaction_count_calculation_method).replace("_", " ")
        embed.add_field(
            name="Set up in this server",
            value=f"Board: <#{server_config.hall_of_fame_channel_id}>\n"
                  f"Reactions needed: **{server_config.reaction_threshold}**\n"
                  f"Counting: {method}\n"
                  f"Full configuration with {command_refs.GET_SERVER_CONFIG}",
            inline=False)
    else:
        embed.add_field(
            name="Not set up in this server yet",
            value=f"Point the bot at a channel with {command_refs.SET_HALL_OF_FAME_CHANNEL}, then "
                  f"pick how many reactions a message needs with {command_refs.SET_REACTION_THRESHOLD}. "
                  f"Both need the Manage Server permission.",
            inline=False)

    embed.add_field(
        name="For everyone",
        value=f"{command_refs.LEADERBOARD} rank the server\n"
              f"{command_refs.USER_PROFILE} a member's standing\n"
              f"{command_refs.HOF_WRAPPED} your year in review\n"
              f"{command_refs.HELP} every command",
        inline=True)
    embed.add_field(
        name="Links",
        value="[Add to a server](https://discord.com/oauth2/authorize?client_id=1177041673352663070)\n"
              "[Support server](https://discord.gg/r98WC5GHcn)\n"
              "[Vote](https://top.gg/bot/1177041673352663070/vote)\n"
              "[Source](https://github.com/LukasKristensen/discord-hall-of-fame-bot)",
        inline=True)

    if bot_user is not None and getattr(bot_user, "display_avatar", None) is not None:
        embed.set_thumbnail(url=bot_user.display_avatar.url)
    embed.set_footer(text=f"Hall of Fame {version.VERSION}")
    return embed


async def answer_bot_mention(message: discord.Message, bot_user, server_config) -> bool:
    """
    Answer a ping with the information card, when the bot is able and has not just answered.
    :param message: The message that pinged the bot
    :param bot_user: The bot's own user
    :param server_config: The server's configuration, or None when it has not been set up
    :return: True when something was sent
    """
    permissions = message.channel.permissions_for(message.guild.me)
    if not permissions.send_messages:
        return False

    if not recently_answered_mentions.add_if_absent(message.channel.id):
        return False

    if not permissions.embed_links:
        # Without this permission an embed is dropped silently, so the answer is given as text
        await message.channel.send(
            f"**Hall of Fame** turns your server's best moments into a highlight reel and credits "
            f"the members behind them. Use {command_refs.HELP} for the commands. "
            f"(Grant the bot the Embed Links permission for the full card.)")
        return True

    await message.channel.send(embed=build_bot_info_embed(message.guild, bot_user, server_config))
    return True
