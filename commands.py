import random
import discord
import utils

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
    random_num = random.randint(0, len(all_messages)-1)
    random_msg = all_messages[random_num]

    msg_channel = bot.get_channel(int(random_msg["channel_id"]))
    message = await msg_channel.fetch_message(int(random_msg["message_id"]))
    target_channel = bot.get_channel(sender_channel)

    video_link = utils.check_video_extension(message)
    if video_link:
        await target_channel.send(video_link)

    embed = await utils.create_embed(message, reaction_threshold)
    await interaction.response.send_message(embed=embed)

async def get_commands(interaction):
    """
    Command to get a list of commands
    :param interaction:
    :return:
    """
    embed = discord.Embed(
        title="Commands",
        color=0x00ff00
    )
    embed.add_field(name="/commands", value="List of commands", inline=False)
    embed.add_field(name="/get_random_message", value="Get a random message from the database", inline=False)
    embed.add_field(name="", value="", inline=True)
    embed.add_field(name="Contribute on Github", value="https://github.com/LukasKristensen/discord-hall-of-fame-bot", inline=False)
    await interaction.response.send_message(embed=embed)

async def manual_sweep(interaction, guild_id: int, sweep_limit: int, sweep_limited: bool, bot: discord.Client,
                       collection, reaction_threshold: int, post_due_date: int, target_channel_id: int, dev_user: int):
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
    :return:
    """
    if interaction.user.id != dev_user:
        await interaction.response.send_message("You are not authorized to use this command")
        return
    await utils.check_all_server_messages(guild_id, sweep_limit, sweep_limited, bot, collection, reaction_threshold, post_due_date, target_channel_id)