import discord
import datetime
from datetime import timezone
from message_reactions import most_reactions, reaction_count_without_author
import server_class

async def validate_message(message: discord.RawReactionActionEvent, bot: discord.Client, collection,
                           reaction_threshold: int, post_due_date: int, target_channel_id: int):
    """
    Check if the message is valid for posting based on the reaction count, date and origin of the message
    :param message: The message to validate
    :param bot: The Discord bot
    :param collection: The MongoDB collection to store the message in
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :param post_due_date: The number of days after which a message is no longer eligible for the Hall of Fame
    :param target_channel_id: The ID of the Hall of Fame channel
    :return: None
    """
    channel_id: int = message.channel_id
    message_id: int = message.message_id

    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(message_id)

    # Checks if the post is older than the due date and has not been added to the database
    if (datetime.datetime.now(timezone.utc) - message.created_at).days > post_due_date and not collection.find_one({"message_id": int(message.id)}):
        return

    # Checks if the post is from the HOF channel or is from a bot
    if channel_id == target_channel_id or message.author.bot:
        return

    # Gets the adjusted reaction count corrected for not accounting the author
    corrected_reactions = await reaction_count_without_author(message)
    if corrected_reactions < reaction_threshold:
        if collection.find_one({"message_id": int(message_id)}):
            await remove_embed(message_id, collection, bot, target_channel_id)
        return

    if collection.find_one({"message_id": int(message.id)}):
        collection.update_one({"message_id": int(message.id)},
                              {"$set": {"reaction_count": await reaction_count_without_author(message)}})
        await update_reaction_counter(message, collection, bot, target_channel_id)
        return
    await post_hall_of_fame_message(message, bot, collection, target_channel_id, reaction_threshold)

async def update_reaction_counter(message: discord.Message, collection, bot: discord.Client, target_channel_id: int):
    """
    Update the reaction counter of a message in the Hall of Fame
    :param message:
    :param collection:
    :param bot:
    :param target_channel_id:
    :return:
    """
    message_sent = collection.find_one({"message_id": int(message.id)})
    if not message_sent["hall_of_fame_message_id"]:
        return
    hall_of_fame_message_id = message_sent["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)

    embed = hall_of_fame_message.embeds[0]
    corrected_reactions = await reaction_count_without_author(message)

    embed.set_field_at(index=0, name=f"{corrected_reactions} Reactions ", value=most_reactions(message.reactions)[0].emoji, inline=True)
    await hall_of_fame_message.edit(embed=embed)

async def remove_embed(message_id: int, collection, bot: discord.Client, target_channel_id: int):
    """
    Remove the embed of a message in the Hall of Fame
    :param message_id:
    :param collection:
    :param bot:
    :param target_channel_id:
    :return:
    """
    message = collection.find_one({"message_id": int(message_id)})
    if "hall_of_fame_message_id" not in message:
        return
    hall_of_fame_message_id = message["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)
    await hall_of_fame_message.edit(content="** **", embed=None)

async def update_leaderboard(collection, bot: discord.Client, server_config, target_channel_id: int, reaction_threshold: int, leaderboard_length: int = 20):
    """
    Update the leaderboard of the Hall of Fame channel with the top 20 most reacted messages
    :param collection:
    :param bot:
    :param server_config:
    :param target_channel_id:
    :param reaction_threshold:
    :param leaderboard_length:
    :return:
    """
    most_reacted_messages = list(collection.find().sort("reaction_count", -1).limit(30))
    msg_id_array = server_config.find_one({"leaderboard_message_ids": {"$exists": True}})

    # Update the reaction count of the top 30 most reacted messages
    for i in range(min(len(most_reacted_messages), collection.count_documents({})-1)):
        message = most_reacted_messages[i]
        channel = bot.get_channel(message["channel_id"])
        message = await channel.fetch_message(message["message_id"])
        collection.update_one({"message_id": int(message.id)},
                              {"$set": {"reaction_count": await reaction_count_without_author(message)}})

    # Updated all the reaction counts
    most_reacted_messages = list(collection.find().sort("reaction_count", -1).limit(20))

    # Update the embeds of the top 20 most reacted messages
    if msg_id_array:
        for i in range(min(leaderboard_length, collection.count_documents({})-1)):
            hall_of_fame_channel = bot.get_channel(target_channel_id)
            hall_of_fame_message = await hall_of_fame_channel.fetch_message(msg_id_array["leaderboard_message_ids"][i])
            original_channel = bot.get_channel(most_reacted_messages[i]["channel_id"])
            original_message = await original_channel.fetch_message(most_reacted_messages[i]["message_id"])

            await hall_of_fame_message.edit(embed=await create_embed(original_message, reaction_threshold))
            await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**")
            if original_message.attachments:
                await hall_of_fame_message.edit(content=f"**HallOfFame#{i+1}**\n{original_message.attachments[0].url}")

async def check_all_server_messages(guild_id: int, sweep_limit: int, sweep_limited: bool, bot: discord.Client,
                                    collection, reaction_threshold: int, post_due_date: int, target_channel_id: int):
    """
    Check all messages in a server for Hall of Fame eligibility
    :param guild_id:
    :param sweep_limit:
    :param sweep_limited:
    :param bot:
    :param collection:
    :param reaction_threshold:
    :param post_due_date:
    :param target_channel_id:
    :return:
    """
    guild = bot.get_guild(guild_id)

    for channel in guild.channels:
        if not isinstance(channel, discord.TextChannel):
            continue # Ignore if the current channel is not a text channel
        if channel.id == target_channel_id:
            continue
        async for message in channel.history(limit=sweep_limit):
            try:
                if message.author.bot:
                    continue  # Ignore messages from bots
                if (datetime.datetime.now(timezone.utc) - message.created_at).days > post_due_date:
                    break # If the message is older than the due date, no need to check further
                message_reactions = await reaction_count_without_author(message)

                if message_reactions >= reaction_threshold:
                    if collection.find_one({"message_id": int(message.id)}):
                        await update_reaction_counter(message, collection, bot, target_channel_id)
                        if sweep_limited:
                            break  # if message is already in the database, no need to check further
                        else:
                            continue # if a total channel sweep is needed
                    await post_hall_of_fame_message(message, bot, collection, target_channel_id, reaction_threshold)
                elif message_reactions >= reaction_threshold-3:
                    if collection.find_one({"message_id": int(message.id)}):
                        await remove_embed(message.id, collection, bot, target_channel_id)
            except Exception as e:
                print(f'An error occurred: {e}')

async def post_hall_of_fame_message(message: discord.Message, bot: discord.Client, collection, target_channel_id: int, reaction_threshold: int):
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

    if video_link:
        await target_channel.send(video_link)

    embed = await create_embed(message, reaction_threshold)
    hall_of_fame_message = await target_channel.send(embed=embed)

    collection.insert_one({"message_id": int(message.id),
                           "channel_id": int(message.channel.id),
                           "guild_id": int(message.guild.id),
                           "hall_of_fame_message_id": int(hall_of_fame_message.id),
                           "reaction_count": int(await reaction_count_without_author(message))})

async def create_embed(message: discord.Message, reaction_threshold: int):
    """
    Create an embed for a message in the Hall of Fame channel
    :param message: The message to create an embed for
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :return: The embed for the message
    """
    # Check if the message is a reply to another message
    if message.reference and not message.attachments:
        reference_message = await message.channel.fetch_message(message.reference.message_id)

        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=message.author.color
        )
        top_reaction = most_reactions(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)

        corrected_reactions = await reaction_count_without_author(message)
        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)

        if reference_message.attachments:
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
        return embed

    # Include the reference message in the embed if the message has both a reference and attachments
    elif message.reference and message.attachments:
        reference_message = await message.channel.fetch_message(message.reference.message_id)

        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=message.author.color
        )

        top_reaction = most_reactions(message.reactions)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)

        corrected_reactions = await reaction_count_without_author(message)

        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
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
        return embed

    else:
        embed = discord.Embed(
            title=f"Message in <#{message.channel.id}> has surpassed {reaction_threshold} reactions",
            description=message.content,
            color=message.author.color
        )
        top_reaction = most_reactions(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        corrected_reactions = await reaction_count_without_author(message)
        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
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

async def create_database_context(server, db_client, leader_board_length: int = 10):
    """
    Create a database context for the server
    :param server: The server object
    :param db_client: The MongoDB client
    :return: The database context
    """
    database = db_client[str(server.id)]

    hall_of_fame_messages = database['hall_of_fame_messages']
    hall_of_fame_messages.insert_one({"message_id": 1, "channel_id": 1, "guild_id": 1, "hall_of_fame_message_id": 1, "reaction_count": 1})

    new_server_config = database['server_config']

    # Create a new channel for the Hall of Fame
    hall_of_fame_channel = await server.create_text_channel("hall-of-fame")

    await hall_of_fame_channel.send(
        f"Hall of Fame channel created.\nCreating {leader_board_length} temporary messages for the leaderboard\n"+
        "(do not delete these messages, they are for future use)\n"+
        "Use the command /reaction_threshold_configure to set the reaction threshold for posting a message in the Hall of Fame channel.")

    # Set the permissions for the Hall of Fame channel to only allow the bot to read messages
    if server.me.guild_permissions.administrator:
        await hall_of_fame_channel.set_permissions(server.default_role, read_messages=True, send_messages=False)

    leader_board_messages = []
    for i in range(leader_board_length):
        message = await hall_of_fame_channel.send(f"**HallOfFame#{i+1}**")
        leader_board_messages.append(message.id)

    new_server_config.insert_one({
        "guild_id": server.id,
        "hall_of_fame_channel_id": hall_of_fame_channel.id,
        "reaction_threshold": 7,
        "post_due_date": 28,
        "leaderboard_message_ids": leader_board_messages,
        "sweep_limit": 1000,
        "sweep_limited": False
    })
    print(f"Database context created for server {server.id}")

    new_server_class = server_class.Server(
        hall_of_fame_channel_id= hall_of_fame_channel.id,
        guild_id=server.id,
        reaction_threshold=7,
        sweep_limit=1000,
        sweep_limited=False,
        post_due_date=28)
    return new_server_class


def delete_database_context(server_id: int, db_client):
    """
    Delete the database context for the server
    :param server_id: The ID of the server
    :param db_client: The MongoDB client
    :return: None
    """
    print(f"Deleting database context for server {server_id}")
    db_client.drop_database(str(server_id))

def get_server_classes(db_client):
    """
    Get all server classes from the database
    :param db_client: The MongoDB client
    :return: A list of server classes
    """
    all_database_names = db_client.list_database_names()
    db_clients = []
    for database_name in all_database_names:
        if database_name.isnumeric():
            db_clients.append(db_client[database_name])

    server_classes = {}
    for db in db_clients:
        server_config = db['server_config']
        server_config = server_config.find_one({})
        server_classes[server_config["guild_id"]] = server_class.Server(
            hall_of_fame_channel_id= server_config["hall_of_fame_channel_id"],
            guild_id=server_config["guild_id"],
            reaction_threshold=server_config["reaction_threshold"],
            sweep_limit=server_config["sweep_limit"],
            sweep_limited=server_config["sweep_limited"],
            post_due_date=server_config["post_due_date"])
    return server_classes