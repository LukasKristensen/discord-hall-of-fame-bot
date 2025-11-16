import random
import discord
import datetime
from datetime import timezone
import asyncio
from message_reactions import most_reacted_emoji, reaction_count
from classes import Server_class
from classes import Log_type

daily_post_limit = 100


async def validate_message(message: discord.RawReactionActionEvent, bot: discord.Client, message_collection,
                           reaction_threshold: int, post_due_date: int, target_channel_id: int,
                           ignore_bot_messages: bool, hide_hof_post_below_threshold: bool):
    """
    Check if the message is valid for posting based on the reaction count, date and origin of the message
    :param message: The message to validate
    :param bot: The Discord bot
    :param message_collection: The MongoDB collection to store the message in
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :param post_due_date: The number of days after which a message is no longer eligible for the Hall of Fame
    :param target_channel_id: The ID of the Hall of Fame channel
    :param ignore_bot_messages: Whether to ignore messages from bots
    :param hide_hof_post_below_threshold: Whether to hide the Hall of Fame post if the reaction count is below the threshold
    :return: None
    """
    channel_id: int = message.channel_id
    message_id: int = message.message_id

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)

    # Checks if the post is older than the due date and has not been added to the database
    if ((datetime.datetime.now(timezone.utc) - message.created_at).days > post_due_date
            and not message_collection.find_one({"guild_id": int(message.guild.id), "channel_id": int(channel_id),
                                                 "message_id": int(message.id)})):
        return

    # Checks if the message is from a bot
    if message.author.bot and ignore_bot_messages:
        return

    if message_collection.count_documents(
        {"guild_id": int(message.guild.id),
         "created_at": {"$gte": datetime.datetime.now(timezone.utc) - datetime.timedelta(days=1)}
         }) > daily_post_limit:
        await logging(bot, f"Guild {message.guild.id} has exceeded the daily limit for hall of fame posts.", message.guild.id, log_type=Log_type.CRITICAL)
        hof_channel = bot.get_channel(target_channel_id)
        existing_messages = [message async for message in hof_channel.history(limit=10)]
        for existing_message in existing_messages:
            if existing_message.author.id == bot.user.id and "has exceeded the daily limit" in existing_message.content:
                return
        await hof_channel.send(f"⚠️ Guild {message.guild.name} has exceeded the daily limit {daily_post_limit} for hall of fame posts. ⚠️")
        return

    # Gets the adjusted reaction count corrected for not accounting the author
    corrected_reactions = await reaction_count(message)
    if corrected_reactions < reaction_threshold:
        if hide_hof_post_below_threshold and message_collection.find_one({"guild_id": int(message.guild.id), "channel_id": int(channel_id),
                                                                          "message_id": int(message_id)}):
            await remove_embed(message_id, message_collection, bot, target_channel_id, message.guild.id, channel_id)
            if ("video_link_message_id" in message_collection.find_one({"guild_id": int(message.guild.id), "channel_id": int(channel_id),
                                                                       "message_id": int(message_id)})
                                                                        and message.attachments):
                video_link_message = message_collection.find_one({"message_id": int(message_id)})["video_link_message_id"]
                if video_link_message is not None:
                    target_channel = bot.get_channel(target_channel_id)
                    video_link_message = await target_channel.fetch_message(int(video_link_message))
                    await video_link_message.edit(content="** **", embed=None)
        return

    if message_collection.find_one({"guild_id": int(message.guild.id), "message_id": int(message.id)}):
        message_update = message_collection.find_one({"guild_id": int(message.guild.id), "channel_id": int(channel_id), "message_id": int(message.id)})
        message_to_update = await bot.get_channel(target_channel_id).fetch_message(message_update["hall_of_fame_message_id"])
        if len(message_to_update.embeds) > 0:
            message_collection.update_one({"guild_id": int(message.guild.id), "channel_id": int(channel_id), "message_id": int(message.id)},
                                          {"$set": {"reaction_count": await reaction_count(message)}})
            await update_reaction_counter(message, message_collection, bot, target_channel_id, reaction_threshold)
            return
        else:
            await message_to_update.edit(embed=await create_embed(message, reaction_threshold))
            if "video_link_message_id" in message_update and message.attachments:
                message_attachment = message.attachments[0]
                video_link_message = message_update["video_link_message_id"]
                target_channel = bot.get_channel(target_channel_id)
                video_link_message = await target_channel.fetch_message(video_link_message)
                await video_link_message.edit(content=message_attachment.url, embed=None)
            return
    await post_hall_of_fame_message(message, bot, message_collection, target_channel_id, reaction_threshold)


async def update_reaction_counter(message: discord.Message, collection, bot: discord.Client, target_channel_id: int,
                                  reaction_threshold: int):
    """
    Update the reaction counter of a message in the Hall of Fame
    :param message:
    :param collection:
    :param bot:
    :param target_channel_id:
    :param reaction_threshold:
    :return:
    """
    message_sent = collection.find_one({"guild_id": int(message.guild.id), "channel_id": int(message.channel.id), "message_id": int(message.id)})
    if not message_sent["hall_of_fame_message_id"]:
        return
    hall_of_fame_message_id = message_sent["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)

    if not hall_of_fame_message.embeds:
        # Post the message in the Hall of Fame channel if it was removed
        await hall_of_fame_message.edit(embed=await create_embed(message, reaction_threshold))
        return

    embed = hall_of_fame_message.embeds[0]
    corrected_reactions = await reaction_count(message)

    # embed.set_field_at(index=0, name=f"{corrected_reactions} Reactions ", value=most_reacted_emoji(message.reactions)[0].emoji, inline=True)
    for i, field in enumerate(embed.fields):
        if field.name.endswith("Reactions"):
            embed.set_field_at(
                index=i,
                name=f"{corrected_reactions} Reactions ",
                value=most_reacted_emoji(message.reactions)[0].emoji,
                inline=True
            )
            break

    await hall_of_fame_message.edit(embed=embed)


async def remove_embed(message_id: int, collection, bot: discord.Client, target_channel_id: int, guild_id: int, channel_id: int):
    """
    Remove the embed of a message in the Hall of Fame
    :param message_id:
    :param collection:
    :param bot:
    :param target_channel_id:
    :param guild_id:
    :param channel_id:
    :return:
    """
    message = collection.find_one({"guild_id": int(guild_id), "channel_id": int(channel_id), "message_id": int(message_id)})
    if "hall_of_fame_message_id" not in message:
        return
    hall_of_fame_message_id = message["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)
    await hall_of_fame_message.edit(content="** **", embed=None)


async def update_leaderboard(message_collection, bot: discord.Client, server_config, target_channel_id: int,
                             reaction_threshold: int, leaderboard_length: int = 20):
    """
    Update the leaderboard of the Hall of Fame channel with the top 20 most reacted messages
    :param message_collection:
    :param bot:
    :param server_config:
    :param target_channel_id:
    :param reaction_threshold:
    :param leaderboard_length:
    :return:
    """
    server_message_collection = message_collection.find({"guild_id": int(server_config['guild_id'])}).sort(
        "reaction_count", -1).limit(30)
    most_reacted_messages = list(server_message_collection)

    msg_id_array = server_config.get("leaderboard_message_ids", [])

    # Update the reaction count of the top 30 most reacted messages
    for i in range(min(len(most_reacted_messages), message_collection.count_documents({"guild_id": int(server_config['guild_id'])}) - 1)):
        message = most_reacted_messages[i]
        channel = bot.get_channel(message["channel_id"])
        message = await channel.fetch_message(message["message_id"])
        message_collection.update_one({"message_id": int(message.id), "guild_id": int(server_config['guild_id']),
                                       "channel_id": int(message.channel.id)},
                                      {"$set": {"reaction_count": await reaction_count(message)}})

    total_documents = message_collection.count_documents({"guild_id": int(server_config['guild_id'])})

    # Update the embeds of the top 20 most reacted messages
    if msg_id_array:
        for i in range(min(leaderboard_length, total_documents - 1)):
            hall_of_fame_channel = bot.get_channel(target_channel_id)
            hall_of_fame_message = await hall_of_fame_channel.fetch_message(msg_id_array[i])
            original_channel = bot.get_channel(most_reacted_messages[i]["channel_id"])
            original_message = await original_channel.fetch_message(most_reacted_messages[i]["message_id"])

            await hall_of_fame_message.edit(embed=await create_embed(original_message, reaction_threshold))
            await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**")
            if original_message.attachments:
                await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**\n{original_message.attachments[0].url}")


async def check_all_server_messages(guild_id: int, sweep_limit, sweep_limited: bool, bot: discord.Client,
                                    collection, reaction_threshold: int, post_due_date: int, target_channel_id: int,
                                    allow_messages_in_hof_channel: bool, interaction: discord.Interaction = None):
    """
    Check all messages in a server for Hall of Fame eligibility
    :param guild_id:
    :param sweep_limit: Int/None
    :param sweep_limited:
    :param bot:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :param allow_messages_in_hof_channel:
    :param interaction: The interaction object to respond to
    :return:
    """
    guild = bot.get_guild(guild_id)

    status_message = "Checking all messages in server, this may take a while due to the amount of messages and rate limits"
    messages_to_post = []

    # Write a response to the interaction to indicate that the sweep is in progress
    await interaction.response.send_message(status_message, ephemeral=False)

    for channel in guild.channels:
        if not channel.permissions_for(guild.me).read_messages:
            continue
        try:
            await interaction.edit_original_response(content=
                                                     status_message+
                                                     f"\n\nChecking channel {channel.name} ({channel.id})"+
                                                     f"\nTotal HOF messages waiting to post: {len(messages_to_post)}")
            if not isinstance(channel, discord.TextChannel):
                continue # Ignore if the current channel is not a text channel
            if channel.id == target_channel_id and not allow_messages_in_hof_channel:
                continue
            async for message in channel.history(limit=sweep_limit):
                try:
                    if message.author.bot:
                        continue  # Ignore messages from bots
                    if (datetime.datetime.now(timezone.utc) - message.created_at).days > post_due_date and sweep_limit is not None:
                        break # If the message is older than the due date, no need to check further
                    message_reactions = await reaction_count(message)

                    if message_reactions >= reaction_threshold:
                        if collection.find_one({"message_id": int(message.id)}):
                            await update_reaction_counter(message, collection, bot, target_channel_id, reaction_threshold)
                            if sweep_limited:
                                break  # if message is already in the database, no need to check further
                            else:
                                continue # if a total channel sweep is needed
                        messages_to_post.append(message)
                    elif message_reactions >= reaction_threshold-3:
                        if collection.find_one({"message_id": int(message.id)}):
                            await remove_embed(message.id, collection, bot, target_channel_id, guild_id, channel.id)
                except Exception as e:
                    await logging(bot, f"An error occurred: {e}", guild_id)
        except Exception as e:
            await logging(bot, f"An error occurred: {e}", guild_id)

    messages_to_post.sort(key=lambda msg: msg.created_at)
    for message in messages_to_post:
        await post_hall_of_fame_message(message, bot, collection, target_channel_id, reaction_threshold)


async def post_hall_of_fame_message(message: discord.Message, bot: discord.Client, collection, target_channel_id: int,
                                    reaction_threshold: int):
    """
    Post a message in the Hall of Fame channel
    :param message:
    :param bot:
    :param collection:
    :param target_channel_id:
    :param reaction_threshold:
    :return:
    """
    target_channel = bot.get_channel(target_channel_id)
    video_link = check_video_extension(message)
    video_message = None

    if video_link:
        video_message = await target_channel.send(video_link)

    embed = await create_embed(message, reaction_threshold)
    hall_of_fame_message = await target_channel.send(embed=embed)

    try:
        result = collection.insert_one({"message_id": int(message.id),
                                        "channel_id": int(message.channel.id),
                                        "guild_id": int(message.guild.id),
                                        "hall_of_fame_message_id": int(hall_of_fame_message.id),
                                        "reaction_count": int(await reaction_count(message)),
                                        "video_link_message_id": int(video_message.id) if video_link else None,
                                        "created_at": datetime.datetime.now(timezone.utc),
                                        "author_id": int(message.author.id)})
        if not result.acknowledged:
            raise Exception(f"Failed to insert message {message.id} into database")
    except Exception as e:
        await hall_of_fame_message.delete()
        if video_message:
            await video_message.delete()
        await logging(bot, e, message.guild.id, log_type=Log_type.CRITICAL)


async def set_footer(embed: discord.Embed):
    """
    Set the footer of an embed
    :param embed: The embed to set the footer for
    :return: None
    """
    if random.random() > 0.05 or embed.image:
        return embed

    embed.add_field(name="Enjoying the bot? Vote for it on top.gg", value="https://top.gg/bot/1177041673352663070/vote", inline=True)
    return embed


async def create_embed(message: discord.Message, reaction_threshold: int):
    """
    Create an embed for a message in the Hall of Fame channel
    :param message: The message to create an embed for
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :return: The embed for the message
    """
    # handle 1024 character limit on embed description
    message.content = message.content[:1021] + "..." if len(message.content) > 1024 else message.content
    reference_message = None
    if message.reference:
        reference_message = await message.channel.fetch_message(message.reference.message_id)
        reference_message.content = reference_message.content[:1021] + "..." if len(reference_message.content) > 1024 else reference_message.content

    # Check if the message is a sticker and has a reference
    if message.reference and message.stickers:
        sticker = message.stickers[0]
        embed = discord.Embed(
            title=f"Sticker from {message.author.name} replying to {reference_message.author.name}'s message",
            description=message.content,
            color=discord.Color.gold()
        )
        embed.set_image(url=sticker.url)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

        embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)

        corrected_reactions = await reaction_count(message)
        embed.add_field(name=f"{corrected_reactions} Reactions", value=most_reacted_emoji(message.reactions)[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        embed = await set_footer(embed)
        return embed

    # Check if the message is a sticker
    elif message.stickers:
        sticker = message.stickers[0]
        embed = discord.Embed(
            title=f"Sticker from {message.author.name} has surpassed {reaction_threshold} reactions",
            description=message.content,
            color=discord.Color.gold()
        )
        embed.set_image(url=sticker.url)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)
        corrected_reactions = await reaction_count(message)
        embed.add_field(name=f"{corrected_reactions} Reactions", value=most_reacted_emoji(message.reactions)[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        embed = await set_footer(embed)
        return embed

    # Check if the message is a reply to another message
    elif message.reference and not message.attachments:
        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=discord.Color.gold()
        )
        top_reaction = most_reacted_emoji(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

        corrected_reactions = await reaction_count(message)
        if reference_message.attachments:
            embed.add_field(name=f"{corrected_reactions} Reactions", value=top_reaction[0].emoji, inline=True)
            embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

            # Author of the original message
            embed.add_field(name=f"{message.author.name}'s reply:", value=message.content, inline=False)

            # Replied message
            embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)
            embed.set_image(url=reference_message.attachments[0].url)
        else:
            # Author of the replied message
            embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)
            # Author of the original message
            embed.add_field(name=f"{message.author.name}'s reply:", value=message.content, inline=False)

            embed.add_field(name=f"{corrected_reactions} Reactions", value=top_reaction[0].emoji, inline=True)
            embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        embed = await set_footer(embed)
        return embed

    # Include the reference message in the embed if the message has both a reference and attachments
    elif message.reference and message.attachments:
        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=discord.Color.gold()
        )

        top_reaction = most_reacted_emoji(message.reactions)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

        corrected_reactions = await reaction_count(message)

        embed.add_field(name=f"{corrected_reactions} Reactions", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        # Original message
        embed.add_field(name=f"{reference_message.author.name}'s message:", value=reference_message.content, inline=False)

        # Reply message
        embed.add_field(name=f"{message.author.name}'s reply:", value=message.content, inline=False)

        attachment = message.attachments[0]
        if attachment.content_type and attachment.content_type.startswith('image'):
            embed.set_image(url=attachment.url)
        else:
            embed.add_field(name="Attachment", value=f"{attachment.url}", inline=False)

        embed = await set_footer(embed)
        return embed
    else:
        embed = discord.Embed(
            title=f"Message in <#{message.channel.id}> has surpassed {reaction_threshold} reactions",
            description=message.content,
            color=discord.Color.gold()
        )
        top_reaction = most_reacted_emoji(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        corrected_reactions = await reaction_count(message)
        embed.add_field(name=f"{corrected_reactions} Reactions", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        embed = await set_footer(embed)
        return embed


def check_video_extension(message):
    """
    Checks if the message contains a video attachment
    :param message: The payload of the event
    :return: The URL of the video attachment if it exists, otherwise None
    """
    if not message.attachments:
        return None
    url = message.attachments[0].url

    for extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        if extension in url:
            video_url = url.split(extension)[0] + extension
            return video_url
    return None


async def create_database_context(bot, server, db_client, custom_channel: discord.TextChannel = None):
    """
    Create a database context for the server
    :param bot: The Discord bot
    :param server: The server object
    :param db_client: The MongoDB client
    :param custom_channel: Optional custom channel for the Hall of Fame channel
    :return: The database context
    """
    db_server_configs = db_client["server_configs"]

    reaction_threshold_default = (
        1 if server.member_count < 3 else
        2 if server.member_count < 5 else
        3 if server.member_count < 10 else
        4 if server.member_count < 20 else
        5 if server.member_count < 40 else
        6 if server.member_count < 50 else
        7
    )

    # Check if the server is already in the database, if so delete the database
    if db_server_configs.find_one({"guild_id": int(server.id)}):
        await logging(bot, f"Server {server.name} already exists in the database, dropping it to recreate", server.id)
        delete_database_context(server.id, db_client)

    hall_of_fame_channel = custom_channel or await server.create_text_channel("hall-of-fame")

    if server.me.guild_permissions.manage_channels:
        await hall_of_fame_channel.edit(
            topic="Patch notes for Hall Of Fame: https://discord.gg/GmFtfySetp",
            reason="Creating Hall of Fame channel"
        )
        await hall_of_fame_channel.set_permissions(server.me, read_messages=True, send_messages=True)
        await hall_of_fame_channel.set_permissions(server.default_role, read_messages=True, send_messages=False)

    leader_board_messages = []

    db_server_configs.insert_one({
        "guild_id": int(server.id),
        "hall_of_fame_channel_id": hall_of_fame_channel.id,
        "reaction_threshold": reaction_threshold_default,
        "post_due_date": 1000,
        "leaderboard_message_ids": leader_board_messages,
        "sweep_limit": 1000,
        "sweep_limited": False,
        "include_author_in_reaction_calculation": True,
        "allow_messages_in_hof_channel": False,
        "custom_emoji_check_logic": False,
        "whitelisted_emojis": [],
        "joined_date": datetime.datetime.now(timezone.utc),
        "leaderboard_setup": False,
        "ignore_bot_messages": False,
        "server_member_count": server.member_count,
        "reaction_count_calculation_method": "most_reactions_on_emoji",
        "hide_hof_post_below_threshold": True
    })

    await hall_of_fame_channel.send(
        f"🎉 **Welcome to the Hall of Fame!** 🎉\n"
        f"When a message receives **{reaction_threshold_default} or more (default threshold) of the same reaction**, it’s automatically **reposted here** to celebrate its popularity.\n\n"
        f"🔧 **Customize your setup:**\n"
        f"   • Change the reaction threshold with </set_reaction_threshold:1367582528675774595>\n"
        f"   • View your current settings with </get_server_config:1358208382473076852>\n\n"
        f"✨ **Want to only track specific emojis?**\n"
        f"   Enable emoji filtering with </custom_emoji_check_logic:1358208382473076848>\n\n"
        f"🧠 **Want to adjust how reactions are counted? (e.g. all votes on a message, not just the highest reaction)**\n"
        f"   Use </calculation_method:1378150000600678440> to change the reaction count calculation method.\n\n"
    )

    new_server_class = Server_class.Server(
        hall_of_fame_channel_id=hall_of_fame_channel.id,
        guild_id=server.id,
        reaction_threshold=reaction_threshold_default,
        sweep_limit=1000,
        sweep_limited=False,
        post_due_date=1000,
        include_author_in_reaction_calculation=True,
        allow_messages_in_hof_channel=False,
        custom_emoji_check_logic=False,
        whitelisted_emojis=[],
        leaderboard_setup=False,
        ignore_bot_messages=False,
        reaction_count_calculation_method="most_reactions_on_emoji",
        hide_hof_post_below_threshold=True)
    return new_server_class


def delete_database_context(server_id: int, db_client):
    """
    Delete the database context for the server
    :param server_id: The ID of the server
    :param db_client: The MongoDB client
    :return: None
    """
    db_client["server_configs"].delete_one({"guild_id": int(server_id)})

    db_hof_messages = db_client["hall_of_fame_messages"].find({"guild_id": int(server_id)})
    for message in db_hof_messages:
        db_client["hall_of_fame_messages"].delete_one({"message_id": message["message_id"], "guild_id": int(server_id)})

    db_server_users = db_client["server_users"].find({"guild_id": int(server_id)})
    for user in db_server_users:
        db_client["server_users"].delete_one({"user_id": user["user_id"], "guild_id": int(server_id)})


async def get_server_classes(db_client):
    """
    Get all server classes from the database
    :param db_client: The MongoDB client
    :return: A list of server classes
    """
    client_documents = db_client["server_configs"]
    server_classes = {}

    for document in client_documents.find():
        server_classes[document["guild_id"]] = Server_class.Server(
            hall_of_fame_channel_id=document["hall_of_fame_channel_id"],
            guild_id=document["guild_id"],
            reaction_threshold=document["reaction_threshold"],
            sweep_limit=document["sweep_limit"],
            sweep_limited=document["sweep_limited"],
            post_due_date=document["post_due_date"],
            allow_messages_in_hof_channel=document["allow_messages_in_hof_channel"],
            include_author_in_reaction_calculation=document["include_author_in_reaction_calculation"],
            custom_emoji_check_logic=document["custom_emoji_check_logic"],
            whitelisted_emojis=document["whitelisted_emojis"],
            leaderboard_setup=document["leaderboard_setup"],
            ignore_bot_messages=document["ignore_bot_messages"],
            reaction_count_calculation_method=document["reaction_count_calculation_method"],
            hide_hof_post_below_threshold=document["hide_hof_post_below_threshold"])
    return server_classes


async def send_server_owner_error_message(owner, e, bot):
    """
    Send an error message to the server owner
    :param owner: The owner of the server
    :param e: The error message
    :param bot: The Discord bot
    :return: None
    """
    if owner:
        try:
            # Fetch the message history of the owner
            messages = []
            async for message in owner.history(limit=1):
                messages.append(message)
            # Check if the specific message has already been sent
            message_already_sent = any("Failed to setup" in msg.content for msg in messages)
            if not message_already_sent:
                await logging(bot, f"Sending error message {e} to server owner {owner.name}")
                await owner.send(f"{e}")
            else:
                await logging(bot, f"Error message already sent to server owner {owner.name}")
        except Exception as history_error:
            await logging(bot, f"Failed to send error message to server owner {owner.name}: {history_error}")


async def logging(bot: discord.Client, message, server_id=None, new_value=None, log_type=Log_type.ERROR):
    """
    Log an error message to the error channel
    :param bot:
    :param message:
    :param server_id: The ID of the server
    :param new_value: The new value of the server configuration
    :param log_type: The type of log message
    :return:
    """
    log_channels = {
        Log_type.ERROR: 1344070396575617085 if bot.application_id == 1177041673352663070 else 1383834395726577765,
        Log_type.SYSTEM: 1373699890718441482 if bot.application_id == 1177041673352663070 else 1383834858870145214,
        Log_type.COMMAND: 1436699144163954759 if bot.application_id == 1177041673352663070 else 1436699968571183106,
        Log_type.CRITICAL: 1439692415454675045 if bot.application_id == 1177041673352663070 else 1439692461176787074
    }

    target_guild = bot.get_guild(1180006529575960616)
    date_formatted_message = f"{datetime.datetime.now()}: {message}"

    if new_value:
        date_formatted_message += f"\n[Value: {new_value}]"
    if server_id:
        date_formatted_message += f"\n[Server ID: {server_id}]"

    channel_id = log_channels.get(log_type)
    if channel_id:
        channel = target_guild.get_channel(channel_id)
        message_prefix = "<@230698327589650432> " if log_type == Log_type.CRITICAL else ""
        await channel.send(f"{message_prefix}```diff\n{date_formatted_message}\n```")


async def create_feedback_form(interaction: discord.Interaction, bot):
    """
    Create a feedback form for the user and send the feedback to the feedback channel
    :param interaction:
    :param bot:
    :return:
    """
    class FeedbackModal(discord.ui.Modal, title="Feedback Form"):
        fb_title = discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="Give your feedback here",
            required=True,
            label="Title"
        )
        message = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="Give your feedback here",
            required=True,
            max_length=500,
            label="Message"
        )

        async def on_submit(self, feedback_interaction) -> None:
            target_guild = bot.get_guild(1180006529575960616)
            target_channel = target_guild.get_channel(1345558910836412456)
            embed = discord.Embed(
                title="New feedback",
                color=discord.Color.gold()
            )
            embed.add_field(name=self.fb_title.label, value=self.fb_title.value, inline=False)
            embed.add_field(name=self.message.label, value=self.message.value, inline=False)
            embed.set_author(name=feedback_interaction.user.name, icon_url=feedback_interaction.user.avatar.url if feedback_interaction.user.avatar else None)
            embed.add_field(name="Guild", value=feedback_interaction.guild.id, inline=True)
            embed.add_field(name="UserId", value=feedback_interaction.user.id, inline=True)
            await target_channel.send(embed=embed)
            await feedback_interaction.response.send_message(f"Thanks for your feedback, {feedback_interaction.user.mention}")
            await asyncio.sleep(5)
            await feedback_interaction.delete_original_response()

    await interaction.response.send_modal(FeedbackModal())


async def create_custom_profile_picture_and_cover_form(interaction: discord.Interaction, bot, default_profile_url="", default_cover_url=""):
    """
    Create a custom profile picture and cover form for the user and send the feedback to the feedback channel
    :param interaction:
    :param bot:
    :param default_profile_url: The default profile picture URL
    :param default_cover_url: The default cover image URL
    :return:
    """
    class CustomProfilePictureAndCoverModal(discord.ui.Modal, title="Custom Bot Profile For Server"):
        profile_picture_url_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="Enter the URL of the profile picture for the bot",
            required=False,
            label="Custom Profile Picture URL",
            default=default_profile_url
        )
        cover_url_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="Enter the URL of the cover image for the bot",
            required=False,
            label="Custom Cover Image URL",
            default=default_cover_url
        )

        async def on_submit(self, custom_profile_interaction) -> None:
            target_guild = bot.get_guild(1180006529575960616)
            target_channel = target_guild.get_channel(1439704492928012360)
            embed = discord.Embed(
                title="New Custom Profile Picture and Cover Request",
                color=discord.Color.gold()
            )
            embed.add_field(name=self.profile_picture_url_input.label, value=self.profile_picture_url_input.value, inline=False)
            embed.add_field(name=self.cover_url_input.label, value=self.cover_url_input.value, inline=False)
            embed.set_author(name=custom_profile_interaction.user.name, icon_url=custom_profile_interaction.user.avatar.url if custom_profile_interaction.user.avatar else None)
            embed.add_field(name="Guild", value=custom_profile_interaction.guild.id, inline=True)
            embed.add_field(name="UserId", value=custom_profile_interaction.user.id, inline=True)
            await target_channel.send(embed=embed)
            await custom_profile_interaction.response.send_message(f"Your request has been sent, {custom_profile_interaction.user.mention}. "
                                                                   f"Processing times can vary and it may not be possible to fulfill all requests.")
    await interaction.response.send_modal(CustomProfilePictureAndCoverModal())


async def update_user_database(bot: discord.Client, db_client):
    """
    Update the user database with the latest information
    :param bot: The Discord bot
    :param db_client: The MongoDB client
    :return: None
    """
    await logging(bot, f"Updating user database...")
    for guild in bot.guilds:
        if not db_client['server_configs'].find_one({"guild_id": int(guild.id)}):
            continue
        hall_of_fame_messages_document = db_client["hall_of_fame_messages"]
        messages = list(hall_of_fame_messages_document.find({"guild_id": int(guild.id)}))

        users_collection = db_client['server_users']
        users_stats = {}

        for message in messages:
            try:
                if not message.get('author_id') or not message.get('created_at'):
                    continue
                user_id = message['author_id']
                if user_id not in users_stats:
                    users_stats[user_id] = {
                        "total_hall_of_fame_messages": 0,
                        "this_month_hall_of_fame_messages": 0,
                        "total_hall_of_fame_message_reactions": 0,
                        "this_month_hall_of_fame_message_reactions": 0
                    }
                users_stats[user_id]["total_hall_of_fame_messages"] += 1
                users_stats[user_id]["total_hall_of_fame_message_reactions"] += message.get('reaction_count', 0)
                if message['created_at'].replace(tzinfo=timezone.utc) >= (datetime.datetime.now(timezone.utc) - datetime.timedelta(days=30)):
                    users_stats[user_id]["this_month_hall_of_fame_messages"] += 1
                    users_stats[user_id]["this_month_hall_of_fame_message_reactions"] += message.get('reaction_count', 0)
            except KeyError as e:
                await logging(bot, f"KeyError in message {message['message_id']} in guild {guild.id}: {e}", guild.id)

        # create a rank for each user based on total and monthly for each field
        for user in users_stats:
            users_stats[user]["total_message_rank"] = 0
            users_stats[user]["monthly_message_rank"] = 0
            users_stats[user]["total_reaction_rank"] = 0
            users_stats[user]["monthly_reaction_rank"] = 0

        sorted_total_messages = sorted(users_stats.items(), key=lambda x: x[1]["total_hall_of_fame_messages"], reverse=True)
        sorted_monthly_messages = sorted(users_stats.items(), key=lambda x: x[1]["this_month_hall_of_fame_messages"], reverse=True)
        sorted_total_reactions = sorted(users_stats.items(), key=lambda x: x[1]["total_hall_of_fame_message_reactions"], reverse=True)
        sorted_monthly_reactions = sorted(users_stats.items(), key=lambda x: x[1]["this_month_hall_of_fame_message_reactions"], reverse=True)

        for rank, (user_id, stats) in enumerate(sorted_total_messages, start=1):
            users_stats[user_id]["total_message_rank"] = rank
        for rank, (user_id, stats) in enumerate(sorted_monthly_messages, start=1):
            users_stats[user_id]["monthly_message_rank"] = rank
        for rank, (user_id, stats) in enumerate(sorted_total_reactions, start=1):
            users_stats[user_id]["total_reaction_rank"] += rank
        for rank, (user_id, stats) in enumerate(sorted_monthly_reactions, start=1):
            users_stats[user_id]["monthly_reaction_rank"] += rank

        for user_id, stats in users_stats.items():
            try:
                users_collection.update_one(
                    {"user_id": user_id, "guild_id": int(guild.id)},
                    {"$set": {
                        "user_id": user_id,
                        "guild_id": int(guild.id),
                        "total_hall_of_fame_messages": stats["total_hall_of_fame_messages"],
                        "this_month_hall_of_fame_messages": stats["this_month_hall_of_fame_messages"],
                        "total_hall_of_fame_message_reactions": stats["total_hall_of_fame_message_reactions"],
                        "this_month_hall_of_fame_message_reactions": stats["this_month_hall_of_fame_message_reactions"],
                        "total_message_rank": stats["total_message_rank"],
                        "monthly_message_rank": stats["monthly_message_rank"],
                        "total_reaction_rank": stats["total_reaction_rank"],
                        "monthly_reaction_rank": stats["monthly_reaction_rank"]
                    }},
                    upsert=True)
            except Exception as e:
                await logging(bot, f"Failed to update user {user_id} in database: {e}", guild.id)
    await logging(bot, f"Finished updating user database...")


async def fix_write_hall_of_fame_channel_permissions(bot, db_client):
    """
    Fix the permissions for the Hall of Fame channel in all servers
    :return:
    """
    for guild in bot.guilds:
        try:
            if str(guild.id) not in db_client.list_database_names():
                continue
            server_db = db_client[str(guild.id)]
            hall_of_fame_channel_id = server_db["server_config"].find_one({"guild_id": guild.id})["hall_of_fame_channel_id"]
            hall_of_fame_channel = bot.get_channel(hall_of_fame_channel_id)
            await hall_of_fame_channel.set_permissions(guild.me, read_messages=True, send_messages=True)
        except Exception as e:
            await logging(bot, f"Failed to fix permissions for Hall of Fame channel in guild {guild.id}: {e}", guild.id)


async def post_server_perms(bot, server):
    """
    Log the permissions of the bot in the server when it joins
    :param bot:
    :param server:
    :return:
    """
    await logging(bot, f"Joined server {server.name} (ID {server.id}) with permissions:\n"
                             f"Can manage roles: {server.me.guild_permissions.manage_roles}\n"
                             f"Can manage channels: {server.me.guild_permissions.manage_channels}\n"
                             f"Can send messages: {server.me.guild_permissions.send_messages}\n"
                             f"Can send messages in threads: {server.me.guild_permissions.send_messages_in_threads},\n"
                             f"Can manage messages: {server.me.guild_permissions.manage_messages}\n"
                             f"Can embed links: {server.me.guild_permissions.embed_links}\n"
                             f"Can attach files: {server.me.guild_permissions.attach_files}\n"
                             f"Can read message history: {server.me.guild_permissions.read_message_history}\n"
                             f"Can add reactions: {server.me.guild_permissions.add_reactions}\n"
                             f"Can use external emojis: {server.me.guild_permissions.use_external_emojis}\n"
                             f"Can view channels: {server.me.guild_permissions.view_channel}\n"
                             f"Server member count: {server.member_count}")
