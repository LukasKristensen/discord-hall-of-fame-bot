import random
import discord
import datetime
from datetime import timezone
import asyncio
from message_reactions import most_reactions, reaction_count_without_author
import server_class
import main

async def validate_message(message: discord.RawReactionActionEvent, bot: discord.Client, collection,
                           reaction_threshold: int, post_due_date: int, target_channel_id: int, allow_messages_in_hof_channel: bool):
    """
    Check if the message is valid for posting based on the reaction count, date and origin of the message
    :param message: The message to validate
    :param bot: The Discord bot
    :param collection: The MongoDB collection to store the message in
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :param post_due_date: The number of days after which a message is no longer eligible for the Hall of Fame
    :param target_channel_id: The ID of the Hall of Fame channel
    :param allow_messages_in_hof_channel: Whether messages are allowed in the Hall of Fame channel
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
    if (channel_id == target_channel_id and not allow_messages_in_hof_channel) or message.author.bot :
        return

    # Gets the adjusted reaction count corrected for not accounting the author
    corrected_reactions = await reaction_count_without_author(message)
    if corrected_reactions < reaction_threshold:
        if collection.find_one({"message_id": int(message_id)}):
            await remove_embed(message_id, collection, bot, target_channel_id)
        return

    if collection.find_one({"message_id": int(message.id)}):
        message_update = collection.find_one({"message_id": int(message.id)})
        message_to_update = await bot.get_channel(target_channel_id).fetch_message(message_update["hall_of_fame_message_id"])
        if len(message_to_update.embeds) > 0:
            collection.update_one({"message_id": int(message.id)},
                                  {"$set": {"reaction_count": await reaction_count_without_author(message)}})
            await update_reaction_counter(message, collection, bot, target_channel_id, reaction_threshold)
            return
        else:
            await message_to_update.edit(embed=await create_embed(message, reaction_threshold))
            return

    await post_hall_of_fame_message(message, bot, collection, target_channel_id, reaction_threshold)

async def update_reaction_counter(message: discord.Message, collection, bot: discord.Client, target_channel_id: int, reaction_threshold: int):
    """
    Update the reaction counter of a message in the Hall of Fame
    :param message:
    :param collection:
    :param bot:
    :param target_channel_id:
    :param reaction_threshold:
    :return:
    """
    message_sent = collection.find_one({"message_id": int(message.id)})
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

async def check_all_server_messages(guild_id: int, sweep_limit, sweep_limited: bool, bot: discord.Client,
                                    collection, reaction_threshold: int, post_due_date: int, target_channel_id: int, allow_messages_in_hof_channel: bool):
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
    :return:
    """
    guild = bot.get_guild(guild_id)
    print(f"Checking all messages in server {guild.name} ({guild_id})")

    for channel in guild.channels:
        if not channel.permissions_for(guild.me).read_messages:
            continue
        try:
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
                    message_reactions = await reaction_count_without_author(message)

                    if message_reactions >= reaction_threshold:
                        if collection.find_one({"message_id": int(message.id)}):
                            await update_reaction_counter(message, collection, bot, target_channel_id, reaction_threshold)
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
    if main.total_message_count > 0:
        main.total_message_count += 1
        await bot.change_presence(activity=discord.CustomActivity(name=f'{main.total_message_count} Hall of Fame messages', type=5))


async def set_footer(embed: discord.Embed):
    """
    Set the footer of an embed
    :param embed: The embed to set the footer for
    :return: None
    """
    if random.random() > 0.15 or embed.image:
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
    # Check if the message is a reply to another message
    if message.reference and not message.attachments:
        reference_message = await message.channel.fetch_message(message.reference.message_id)


        print("message.author:", message.author)
        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=message.author.color
        )
        top_reaction = most_reactions(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

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

        embed = await set_footer(embed)
        return embed

    # Include the reference message in the embed if the message has both a reference and attachments
    elif message.reference and message.attachments:
        reference_message = await message.channel.fetch_message(message.reference.message_id)

        embed = discord.Embed(
            title=f"{message.author.name} replied to {reference_message.author.name}'s message",
            color=message.author.color
        )

        top_reaction = most_reactions(message.reactions)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

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

        embed = await set_footer(embed)
        return embed

    else:
        embed = discord.Embed(
            title=f"Message in <#{message.channel.id}> has surpassed {reaction_threshold} reactions",
            description=message.content,
            color=message.author.color
        )
        top_reaction = most_reactions(message.reactions)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        corrected_reactions = await reaction_count_without_author(message)
        embed.add_field(name=f"{corrected_reactions} Reactions ", value=top_reaction[0].emoji, inline=True)
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

async def create_database_context(server, db_client, leader_board_length: int = 10, reaction_threshold_default: int=7):
    """
    Create a database context for the server
    :param server: The server object
    :param db_client: The MongoDB client
    :param leader_board_length: The number of messages to display in the leaderboard
    :param reaction_threshold_default: The default reaction threshold for a message to be posted in the Hall of Fame
    :return: The database context
    """
    database = db_client[str(server.id)]

    new_server_config = database['server_config']

    # Create a new channel for the Hall of Fame
    hall_of_fame_channel = await server.create_text_channel("hall-of-fame")
    await hall_of_fame_channel.edit(
        topic="Leaderboard in pinned messages - Patch notes: https://discord.gg/GmFtfySetp",
        reason="Creating Hall of Fame channel"
    )

    await hall_of_fame_channel.send(
        f"🎉 **Hall of Fame Channel Created!** 🎉\n\n"
        f"🔹 **All Hall of Fame Messages**:\n"
        f"   • All messages that meet the reaction threshold will be posted in this channel.\n\n"
        f"🔹 **Temporary Leaderboard Messages in pinned messages**:\n"
        f"   • The top {leader_board_length} most reacted messages will be displayed on the leaderboard.\n"
        f"   • ⚠️ *Please do not delete these messages as they are required for future use.*\n"
    )

    # Set the permissions for the Hall of Fame channel to only allow the bot to write messages
    if server.me.guild_permissions.administrator:
        await hall_of_fame_channel.set_permissions(server.default_role, read_messages=True, send_messages=False)

    await hall_of_fame_channel.send("**Leaderboard:**")
    leader_board_messages = []
    for i in range(leader_board_length):
        message = await hall_of_fame_channel.send(f"**HallOfFame#{i+1}**")
        leader_board_messages.append(message.id)

    # pin the leaderboard messages in reverse order
    for i in range(leader_board_length):
        await hall_of_fame_channel.get_partial_message(leader_board_messages[-1-i]).pin()

        async for pin_notification in hall_of_fame_channel.history(limit=1):
            if pin_notification.type == discord.MessageType.pins_add:
                await pin_notification.delete()
                break

    new_server_config.insert_one({
        "guild_id": server.id,
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
        "joined_date": datetime.datetime.now(timezone.utc)
    })
    database.create_collection('hall_of_fame_messages')

    print(f"Database context created for server {server.id}")
    await hall_of_fame_channel.send(
        f"🎉 **Welcome to the Hall of Fame!** 🎉\n\n"
        f"🔹 **Reaction Threshold**: {reaction_threshold_default} reactions (default)\n"
        f"🔹 **How it works**:\n"
        f"   • The threshold is based on the highest count of a single reaction on a message.\n"
        f"   • Use `/reaction_threshold_configure` to customize the threshold.\n"
        f"   • Use `/get_server_config` to view the current server configuration.\n\n"
        f"✨ **Want to only track specific emojis?**\n"
        f"   • Use `/custom_emoji_check_logic` to enable custom emoji tracking.\n"
    )

    new_server_class = server_class.Server(
        hall_of_fame_channel_id= hall_of_fame_channel.id,
        guild_id=server.id,
        reaction_threshold=reaction_threshold_default,
        sweep_limit=1000,
        sweep_limited=False,
        post_due_date=28,
        include_author_in_reaction_calculation=True,
        allow_messages_in_hof_channel=False,
        custom_emoji_check_logic=False,
        whitelisted_emojis=[])
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

def get_server_classes(db_client, bot):
    """
    Get all server classes from the database
    :param db_client: The MongoDB client
    :param bot: The Discord bot
    :return: A list of server classes
    """
    all_database_names = db_client.list_database_names()
    db_clients = []
    for database_name in all_database_names:
        if database_name.isnumeric() and bot.get_guild(int(database_name)):
            db_clients.append(db_client[database_name])
        else:
            error_logging(bot, f"Database {database_name} does not exist or is not a server database")

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
            post_due_date=server_config["post_due_date"],
            allow_messages_in_hof_channel=server_config["allow_messages_in_hof_channel"],
            include_author_in_reaction_calculation=server_config["include_author_in_reaction_calculation"],
            custom_emoji_check_logic=server_config["include_author_in_reaction_calculation"],
            whitelisted_emojis=server_config["whitelisted_emojis"])
    return server_classes


async def send_server_owner_error_message(owner, e):
    """
    Send an error message to the server owner
    :param owner: The owner of the server
    :param e: The error message
    :return: None
    """
    if owner:
        try:
            # Fetch the message history of the owner
            messages = []
            async for message in owner.history(limit=100):
                messages.append(message)
            # Check if the specific message has already been sent
            message_already_sent = any("Failed to set up the bot for your server" in msg.content for msg in messages)
            if not message_already_sent:
                print(f"Sending error message to server owner {owner.name}")
                await owner.send(f"Failed to set up the bot for your server: {e}")
            else:
                print("Error message already sent to server owner")
        except Exception as history_error:
            print(f"Failed to fetch the message history of the server owner: {history_error}")

async def error_logging(bot, message, server_id = None, new_value = None):
    """
    Log an error message to the error channel
    :param bot:
    :param message:
    :param server_id: The ID of the server
    :return:
    """
    target_guild = bot.get_guild(1180006529575960616)
    target_channel = target_guild.get_channel(1344070396575617085)
    logging_message = f"{datetime.datetime.now()}: {message}."

    if server_id:
        total_guild_hall_of_fame_messages = main.db_client[str(server_id)]['hall_of_fame_messages'].count_documents({})
        logging_message += f"\n[Server ID: {server_id}] [Total Hall of Fame messages: {total_guild_hall_of_fame_messages}]"
    if new_value:
        logging_message += f"\n[New value: {new_value}]"
    await target_channel.send(f"```diff\n{logging_message}\n```")

async def create_feedback_form(interaction, bot):
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
                color=discord.Color.yellow()
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
