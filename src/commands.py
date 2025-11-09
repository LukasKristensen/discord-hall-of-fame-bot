import random
import discord
import utils
from classes import version


async def get_random_message(interaction: discord.Interaction, collection, bot, reaction_threshold):
    """
    Command to get a random message from the Hall of Fame database
    :param interaction:
    :param collection:
    :param bot:
    :param reaction_threshold:
    :return:
    """
    sender_channel = interaction.channel.id

    all_messages = [x for x in collection.find()]
    if not all_messages:
        await interaction.response.send_message("No available messages in the database for this server")
        return
    random_num = random.randint(0, len(all_messages)-1)
    random_msg = all_messages[random_num]

    msg_channel = bot.get_channel(int(random_msg["channel_id"]))
    if not msg_channel:
        await interaction.response.send_message("No available messages in the database for this server")
        return
    message = await msg_channel.fetch_message(int(random_msg["message_id"]))
    target_channel = bot.get_channel(sender_channel)

    video_link = utils.check_video_extension(message)
    if video_link:
        await target_channel.send(video_link)

    embed = await utils.create_embed(message, reaction_threshold)
    await interaction.response.send_message(embed=embed)


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
    embed.add_field(name="</help:1343460166263115796>", value="List of commands", inline=False)
    embed.add_field(name="</set_reaction_threshold:1367582528675774595>", value="Set the amount of reactions needed for a post to reach hall of fame", inline=False)
    embed.add_field(name="</include_authors_reaction:1348428694007316570>", value="Should the author of a message be included in the reaction count?", inline=False)
    embed.add_field(name="</allow_messages_in_hof_channel:1348428694007316571>", value="Allow anyone to type in the Hall of Fame channel", inline=False)
    embed.add_field(name="</custom_emoji_check_logic:1358208382473076848>", value="Use only whitelisted emojis for the reaction count", inline=False)
    embed.add_field(name="</whitelist_emoji:1358208382473076849>", value="Add a whitelisted emoji to the list [custom_emoji_check_logic]", inline=False)
    embed.add_field(name="</unwhitelist_emoji:1358208382473076850>", value="Remove a whitelisted emoji from the list [custom_emoji_check_logic]", inline=False)
    embed.add_field(name="</clear_whitelist:1358208382473076851>", value="Clear the whitelist of emojis [custom_emoji_check_logic]", inline=False)
    embed.add_field(name="</get_server_config:1358208382473076852>", value="Get the current bot configuration for the server", inline=False)
    embed.add_field(name="</ignore_bot_messages:1369721901726961686>", value="Should the bot ignore messages from other bots?", inline=False)
    embed.add_field(name="</hide_hof_post_below_threshold:1379918311197769800>", value="Should hall of fame posts be hidden when they go below the reaction threshold? (Will be visible again when they reach the threshold again)", inline=False)
    embed.add_field(name="</calculation_method:1378150000600678440>", value="Change the calculation method for reactions", inline=False)
    embed.add_field(name="</user_profile:1437074090707124316>", value="Get the Hall of Fame profile for a user", inline=False)
    embed.add_field(name="</leaderboard:1437111068987101305>", value="Get the Hall of Fame leaderboard for the server", inline=False)
    embed.add_field(name="</set_hall_of_fame_channel:1393576242237804768>", value="Manually set the Hall of Fame channel for the server", inline=False)
    embed.add_field(name="</feedback:1345567421834068060>", value="Got a feature request or bug report? Let us know!", inline=False)
    embed.add_field(name="</vote:1357399188526334074>", value="Support the bot by voting for it on top.gg: https://top.gg/bot/1177041673352663070/vote", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Having trouble setting up the bot?", value="Make sure the bot has the correct permissions in the server or try to re-invite it", inline=False)
    embed.add_field(name="Need help?", value="Join the community server: https://discord.gg/r98WC5GHcn", inline=False)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    embed.add_field(name="Invite the bot", value="https://discord.com/oauth2/authorize?client_id=1177041673352663070", inline=False)
    embed.set_footer(text=f"Bot Version: {version.VERSION} - {version.DATE}")
    embed.set_image(url="https://raw.githubusercontent.com/LukasKristensen/discord-hall-of-fame-bot/refs/heads/main/Assets/reaction_calculation_methods_wide.jpg")
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


async def set_reaction_threshold(interaction: discord.Interaction, reaction_threshold: int, db_client):
    """
    Command to set the reaction threshold for posting a message in the Hall of Fame
    :param interaction:
    :param reaction_threshold:
    :param db_client:
    :return:
    """
    server_config = db_client['server_configs']
    server_config.update_one({"guild_id": int(interaction.guild_id)}, {"$set": {"reaction_threshold": reaction_threshold}})

    await interaction.response.send_message(f"Reaction threshold set to {reaction_threshold}.\n"
                                            f"Note: The reaction threshold is based on the highest reaction count"
                                            f" of a single emoji per message.")


async def user_server_profile(interaction, user, user_stats, db_client, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame profile for a user in a specific server
    :param interaction:
    :param user:
    :param user_stats:
    :param db_client:
    :param month_emoji:
    :param all_time_emoji:
    :return:
    """
    user_has_most_this_month_hall_of_fame_messages = db_client['server_users'].find_one(
        {"guild_id": interaction.guild_id}, sort=[("this_month_hall_of_fame_messages", -1)])
    user_with_most_all_time_hall_of_fame_messages = db_client['server_users'].find_one(
        {"guild_id": interaction.guild_id}, sort=[("total_hall_of_fame_messages", -1)])
    embed = discord.Embed(
        title=f"📊 {user.name}'s Server Profile",
        description=f"Here are your stats for **{interaction.guild.name}**:",
        color=discord.Color.gold()
    )
    if user_has_most_this_month_hall_of_fame_messages and user.id == user_has_most_this_month_hall_of_fame_messages.get("user_id") and user_stats:
        embed.add_field(name=f"{month_emoji} **Monthly Hall of Fame Champion**",
                        value=f"**{user.name}** is the champion of this month's Hall of Fame with **{user_stats.get('this_month_hall_of_fame_messages', 0)}** messages!",
                        inline=False)
    if user_with_most_all_time_hall_of_fame_messages and user.id == user_with_most_all_time_hall_of_fame_messages.get("user_id") and user_stats:
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


async def server_leaderboard(interaction, db_client, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame leaderboard for a server
    :param interaction:
    :param db_client:
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
    top_monthly = db_client['server_users'].find({"guild_id": interaction.guild_id}).sort(
        "this_month_hall_of_fame_messages", -1).limit(5)
    leaderboard += f"{month_emoji} **Top 5 This Month's Hall of Fame Messages**\n"
    for rank, user in enumerate(top_monthly, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"

    # Top 5 All-Time Hall of Fame Messages
    top_all_time = db_client['server_users'].find({"guild_id": interaction.guild_id}).sort(
        "total_hall_of_fame_messages", -1).limit(5)
    leaderboard += f"\n{all_time_emoji} **Top 5 All-Time Hall of Fame Messages**\n"
    for rank, user in enumerate(top_all_time, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_messages', 0)} messages\n"

    # Top 5 This Month's Reactions
    top_monthly_reactions = db_client['server_users'].find({"guild_id": interaction.guild_id}).sort(
        "this_month_hall_of_fame_message_reactions", -1).limit(5)
    leaderboard += f"\n💬 **Top 5 This Month's Reactions**\n"
    for rank, user in enumerate(top_monthly_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"

    # Top 5 All-Time Reactions
    top_all_time_reactions = db_client['server_users'].find({"guild_id": interaction.guild_id}).sort(
        "total_hall_of_fame_message_reactions", -1).limit(5)
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
