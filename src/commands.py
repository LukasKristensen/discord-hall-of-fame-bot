import random
import discord
import utils
import version
import main


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
    if not await main.check_if_user_has_manage_server_permission(interaction):
        return False

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"reaction_threshold": reaction_threshold}})

    # Note for user - remember that the reaction threshold is based on the highest reaction count of a single emoji for each message
    await interaction.response.send_message(f"Reaction threshold set to {reaction_threshold}.\n"
                                            f"Note: The reaction threshold is based on the highest reaction count"
                                            f" of a single emoji per message.")
    return True
