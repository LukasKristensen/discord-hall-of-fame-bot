import random
import discord
import utils
import version
import main

async def get_random_message(interaction, collection, bot, reaction_threshold):
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

async def get_help(interaction):
    """
    Command to get a list of commands
    :param interaction:
    :return:
    """
    embed = discord.Embed(
        title="Commands",
        color=0x00ff00
    )
    embed.add_field(name="/help", value="List of commands", inline=False)
    embed.add_field(name="/set_reaction_threshold", value="Set the amount of reactions needed for a post to reach hall of fame", inline=False)
    embed.add_field(name="/include_authors_reaction", value="Should the author of a message be included in the reaction count?", inline=False)
    embed.add_field(name="/allow_messages_in_hof_channel", value="Allow anyone to type in the Hall of Fame channel", inline=False)
    embed.add_field(name="/custom_emoji_check_logic", value="Use only whitelisted emojis for the reaction count", inline=False)
    embed.add_field(name="/whitelist_emoji", value="Add a whitelisted emoji to the list [custom_emoji_check_logic]", inline=False)
    embed.add_field(name="/unwhitelist_emoji", value="Remove a whitelisted emoji from the list [custom_emoji_check_logic]", inline=False)
    embed.add_field(name="/clear_whitelist", value="Clear the whitelist of emojis [custom_emoji_check_logic]", inline=False)
    embed.add_field(name="/get_server_config", value="Get the current bot configuration for the server", inline=False)
    embed.add_field(name="/vote", value="Support the bot by voting for it on top.gg: https://top.gg/bot/1177041673352663070/vote", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Having trouble setting up the bot?", value="Make sure the bot has the correct permissions in the server or try to re-invite it", inline=False)
    embed.add_field(name="Need help?", value="Join the community server: https://discord.gg/r98WC5GHcn", inline=False)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    embed.add_field(name="Invite the bot", value="https://discord.com/oauth2/authorize?client_id=1177041673352663070", inline=False)
    embed.set_footer(text=f"Bot Version: {version.VERSION} - {version.DATE}")
    await interaction.response.send_message(embed=embed)

async def manual_sweep(interaction, guild_id: int, sweep_limit, sweep_limited: bool, bot: discord.Client,
                       collection, reaction_threshold: int, post_due_date: int, target_channel_id: int, dev_user: int,
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
    :param dev_user:
    :param allow_messages_in_hof_channel:
    :return:
    """
    if interaction.user.id != dev_user:
        await interaction.response.send_message("You are not authorized to use this command")
        return
    await utils.check_all_server_messages(int(guild_id), sweep_limit, sweep_limited, bot, collection, reaction_threshold, post_due_date, target_channel_id, allow_messages_in_hof_channel)

async def set_reaction_threshold(interaction, reaction_threshold: int, db_client):
    """
    Command to set the reaction threshold for posting a message in the Hall of Fame
    :param interaction:
    :param reaction_threshold:
    :param db_client:
    :return:
    """
    if not await main.check_if_user_has_manage_server_permission(interaction): return

    db = db_client[str(interaction.guild_id)]
    server_config = db['server_config']
    server_config.update_one({"guild_id": interaction.guild_id}, {"$set": {"reaction_threshold": reaction_threshold}})

    await interaction.response.send_message(f"Reaction threshold set to {reaction_threshold}")
    return True
