import discord
import datetime
from datetime import timezone
import asyncio
from contextlib import contextmanager
from message_reactions import most_reacted_emoji, reaction_count
from classes import server_class
from enums import command_refs, log_type, calculation_method_type
from repositories import (server_config_repo, hall_of_fame_message_repo, server_user_repo, hof_wrapped_repo,
                          hof_wrapped_guild_status_repo, opt_out_repo)
from caches import ExpiringSet
from translations import messages
import setup_check

daily_post_limit = 100
duplicate_log_window_seconds = 600
recently_logged_messages = ExpiringSet(ttl_seconds=duplicate_log_window_seconds)
# Guild ID to the day its reaching the daily post limit was last handled, so it is logged and announced once a day
daily_limit_handled_on = {}
# Guild IDs whose missing Hall of Fame channel has been logged, so each server is reported once per boot
missing_channels_logged = set()
# The most posts credited to one member, across every server. It keeps what the bot stores about any one
# member small enough that /my_data can always send them all of it, which data protection law entitles
# them to: 10,000 posts is a file of about 2.5 MB. Posts past it still reach the server's board, but are
# stored without an author, so they add to no leaderboard, profile or Wrapped. Even one member writing
# every post a server's daily limit allows would need 100 days to reach it, so a member who does is also
# worth a look for farmed reactions
member_post_limit = 10_000
# Members whose reaching member_post_limit has been logged, so each is reported once per boot
members_at_post_limit_logged = set()


def author_to_store(connection, author_id: int) -> tuple[int, bool]:
    """
    Who a new post is credited to: the member, or nobody when they asked not to be featured or already
    have member_post_limit posts credited to them. Checked when a post is stored rather than on every
    reaction, and counted from the author index, so it costs one lookup per new post
    :param connection: The database connection
    :param author_id: The member who wrote the message
    :return: The author ID to store, and whether the member is at the post limit
    """
    if opt_out_repo.is_opted_out(connection, author_id):
        return hall_of_fame_message_repo.NO_AUTHOR_ID, False
    if hall_of_fame_message_repo.count_messages_by_author(connection, author_id) >= member_post_limit:
        return hall_of_fame_message_repo.NO_AUTHOR_ID, True
    return author_id, False


# The server's rules about which messages qualify, as rule_blocking_post names them
RULE_TOO_OLD = "too_old"
RULE_BOT_MESSAGE = "bot_message"
RULE_NO_MEDIA = "no_media"


def has_image_or_video(message: discord.Message) -> bool:
    """
    Whether a message carries an image or a video, as an attachment or in an embed such as a link preview
    :param message: The message to look at
    :return: True when it has at least one image or video
    """
    for attachment in message.attachments or []:
        content_type = getattr(attachment, 'content_type', '')
        if content_type and (content_type.startswith('image/') or content_type.startswith('video/')):
            return True
    for embed in message.embeds or []:
        if embed.type in ['image', 'video'] or embed.image or embed.video:
            return True
    return False


def rule_blocking_post(source_message: discord.Message, db_message, server_config: server_class.Server,
                       now: datetime.datetime = None) -> str | None:
    """
    The first of the server's rules about which messages qualify that a message breaks. Shared by
    validate_message and the Why isn't this on the board? command, so the explanation a member gets is
    the rule the bot actually applies
    :param source_message: The message that was reacted to
    :param db_message: Its stored Hall of Fame post, or None when it has none
    :param server_config: The in memory configuration of the server
    :param now: The current time, for tests
    :return: One of the RULE_ names, or None when the message breaks none of them
    """
    now = now or datetime.datetime.now(timezone.utc)
    # A post already on the board keeps being updated however old the message gets
    if (now - source_message.created_at).days > server_config.post_due_date and not db_message:
        return RULE_TOO_OLD
    if source_message.author.bot and server_config.ignore_bot_messages:
        return RULE_BOT_MESSAGE
    if server_config.require_image_or_video and not has_image_or_video(source_message):
        return RULE_NO_MEDIA
    return None


async def validate_message(reaction_event: discord.RawReactionActionEvent, bot: discord.Client, connection,
                           server_config: server_class.Server):
    """
    Check if the message is valid for posting based on the reaction count, date and origin of the message
    :param reaction_event: The raw reaction event that triggered the check
    :param bot: The Discord bot
    :param connection: The database connection
    :param server_config: The in memory configuration of the server the reaction happened in
    :return: None
    """
    channel_id: int = reaction_event.channel_id
    message_id: int = reaction_event.message_id
    guild_id: int = reaction_event.guild_id

    reaction_threshold = server_config.reaction_threshold
    target_channel_id = server_config.hall_of_fame_channel_id
    hide_hof_post_below_threshold = server_config.hide_hof_post_below_threshold

    channel = bot.get_channel(channel_id)
    if channel is None:
        # The channel is not cached, which happens when the bot cannot see it anymore
        return
    if not channel.permissions_for(channel.guild.me).read_messages:
        await logging(bot, f"Bot does not have read message permissions in channel {channel.id} of guild {channel.guild.id}", channel.guild.id)
        return

    # The event only carries ids, so the message itself is fetched under a name that says what it is
    source_message = await channel.fetch_message(message_id)
    db_message = hall_of_fame_message_repo.find_hall_of_fame_message(connection, guild_id, channel_id, message_id)

    if rule_blocking_post(source_message, db_message, server_config) is not None:
        return

    target_channel = bot.get_channel(target_channel_id)
    if target_channel is None:
        await report_missing_hall_of_fame_channel(bot, guild_id, target_channel_id)
        return

    if hall_of_fame_message_repo.guild_message_count_today(connection, guild_id) >= daily_post_limit:
        # Every reaction lands here while the server is at its limit, so it is handled once a day
        today = datetime.date.today()
        if daily_limit_handled_on.get(guild_id) == today:
            return
        daily_limit_handled_on[guild_id] = today

        await logging(bot, f"Guild {guild_id} has exceeded the daily limit for hall of fame posts.", source_message.guild.id,
                      log_level=log_type.CRITICAL, validate_for_duplicates=True, ping_developer=False)
        await target_channel.send(
            f"⚠️ **Hall of Fame limit reached**\n"
            f"Server **{source_message.guild.name}** has hit the daily limit of **{daily_post_limit} posts**.\n"
            f"No more messages will be added until tomorrow."
        )
        return

    # Served from the in memory server config, so counting reactions costs no database round trips
    reaction_config = server_config.reaction_config()

    # Gets the adjusted reaction count corrected for not accounting the author
    corrected_reactions = await reaction_count(source_message, connection, reaction_config)
    if corrected_reactions < reaction_threshold:
        if hide_hof_post_below_threshold and db_message:
            await remove_embed(db_message, bot, target_channel_id)
            if "video_link_message_id" in db_message and source_message.attachments:
                video_link_message = db_message["video_link_message_id"]
                if video_link_message is not None:
                    video_link_message = await target_channel.fetch_message(int(video_link_message))
                    await video_link_message.edit(content="** **", embed=None)
        return

    if db_message:
        message_to_update = await target_channel.fetch_message(db_message["hall_of_fame_message_id"])
        if len(message_to_update.embeds) > 0:
            hall_of_fame_message_repo.update_field_for_message(connection, guild_id, channel_id, message_id, "reaction_count", corrected_reactions)
            await update_reaction_counter(db_message, bot, target_channel_id, reaction_threshold, connection,
                                          source_message, corrected_reactions, reaction_config)
            return
        else:
            # The post was hidden and is now back over the threshold, so it is restored with its current
            # count, which the leaderboards and profiles read from the database
            hall_of_fame_message_repo.update_field_for_message(connection, guild_id, channel_id, message_id, "reaction_count", corrected_reactions)
            await message_to_update.edit(embed=await create_embed(source_message, reaction_threshold, connection, reaction_config))
            # The column is present and null for every post that is not a video, so the id itself
            # is what decides whether there is a link message to restore
            video_link_message_id = db_message.get("video_link_message_id")
            if video_link_message_id is not None and source_message.attachments:
                message_attachment = source_message.attachments[0]
                video_link_message = await target_channel.fetch_message(int(video_link_message_id))
                await video_link_message.edit(content=message_attachment.url, embed=None)
            return
    await post_hall_of_fame_message(source_message, bot, connection, target_channel_id, reaction_threshold, reaction_config)


async def update_reaction_counter(db_message, bot: discord.Client, target_channel_id: int, reaction_threshold: int,
                                  connection, discord_message: discord.Message, corrected_reactions: int = None,
                                  config: dict = None):
    """
    Update the reaction counter of a message in the Hall of Fame
    :param db_message:
    :param bot:
    :param target_channel_id:
    :param reaction_threshold:
    :param connection:
    :param discord_message:
    :param corrected_reactions: The already calculated reaction count, recalculated when not supplied
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    if not db_message["hall_of_fame_message_id"]:
        return
    hall_of_fame_message_id = db_message["hall_of_fame_message_id"]

    target_channel = bot.get_channel(target_channel_id)
    if target_channel is None:
        return
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)

    if not hall_of_fame_message.embeds:
        # Post the message in the Hall of Fame channel if it was removed
        await hall_of_fame_message.edit(embed=await create_embed(discord_message, reaction_threshold, connection, config))
        return

    embed = hall_of_fame_message.embeds[0]
    if corrected_reactions is None:
        corrected_reactions = await reaction_count(discord_message, connection, config)
    top_reaction = most_reacted_emoji(discord_message.reactions, discord_message.guild.id, connection, config)
    reactions_field_value = format_reactions_field_value(corrected_reactions, top_reaction)

    for i, field in enumerate(embed.fields):
        field_name = (field.name or "").strip()
        if field_name == "Reactions" or field_name.endswith("Reactions"):
            embed.set_field_at(
                index=i,
                name="Reactions",
                value=reactions_field_value,
                inline=True
            )
            break

    await hall_of_fame_message.edit(embed=embed)


async def remove_embed(message, bot: discord.Client, target_channel_id: int):
    """
    Remove the embed of a message in the Hall of Fame
    :param message:
    :param bot:
    :param target_channel_id:
    :return:
    """
    if "hall_of_fame_message_id" not in message:
        return
    hall_of_fame_message_id = message["hall_of_fame_message_id"]
    target_channel = bot.get_channel(target_channel_id)
    if target_channel is None:
        return
    hall_of_fame_message = await target_channel.fetch_message(hall_of_fame_message_id)
    await hall_of_fame_message.edit(content="** **", embed=None)


async def update_leaderboard(connection, bot: discord.Client, server_config: server_class.Server):
    """
    Update the leaderboard of the Hall of Fame channel with the top 20 most reacted messages
    :param connection:
    :param bot:
    :param server_config:
    :return:
    """
    msg_id_array = server_config.leaderboard_message_ids
    if not msg_id_array:
        return

    hall_of_fame_channel = bot.get_channel(int(server_config.hall_of_fame_channel_id))
    if not hall_of_fame_channel:
        return

    server_messages = hall_of_fame_message_repo.find_top_messages_by_reaction_count(connection, int(server_config.guild_id), limit=30)
    most_reacted_messages = list(server_messages)
    reaction_config = server_config.reaction_config()

    # Update the reaction count of the top 30 most reacted messages
    for i in range(min(len(most_reacted_messages), 30)):
        message = most_reacted_messages[i]
        channel = bot.get_channel(int(message["channel_id"]))
        if not channel:
            continue
        message = await channel.fetch_message(int(message["message_id"]))
        hall_of_fame_message_repo.update_field_for_message(connection, int(server_config.guild_id), message.channel.id, message.id,
                                                          "reaction_count", await reaction_count(message, connection, reaction_config))

    # Update the top 20 messages in the leaderboard
    for i in range(min(20, len(most_reacted_messages), len(msg_id_array))):
        original_channel = bot.get_channel(int(most_reacted_messages[i]["channel_id"]))
        if not original_channel:
            # The channel was deleted or hidden from the bot since the message was featured.
            # Its place is left as it was, rather than losing the rest of the leaderboard with it
            continue
        hall_of_fame_message = await hall_of_fame_channel.fetch_message(int(msg_id_array[i]))
        original_message = await original_channel.fetch_message(int(most_reacted_messages[i]["message_id"]))

        leaderboard_content = f"**HallOfFame#{i+1}**"
        if original_message.attachments:
            leaderboard_content += f"\n{original_message.attachments[0].url}"

        # Edited in one request, as editing the same message several times triples the rate limit cost
        await hall_of_fame_message.edit(
            content=leaderboard_content,
            embed=await create_embed(original_message, server_config.reaction_threshold, connection, reaction_config))


async def report_missing_hall_of_fame_channel(bot: discord.Client, guild_id: int, channel_id: int):
    """
    Log that a server's Hall of Fame channel cannot be found, once per boot for each server
    Every reaction in such a server and the daily task all end up here, and the duplicate guard only
    lasts ten minutes, so without this the same servers fill the error channel all day
    :param bot: The Discord bot
    :param guild_id: The ID of the server
    :param channel_id: The ID of the Hall of Fame channel that could not be found
    :return: None
    """
    if guild_id in missing_channels_logged:
        return
    missing_channels_logged.add(guild_id)

    await logging(bot, f"Could not find the Hall of Fame channel {channel_id}", guild_id)


async def post_hall_of_fame_message(message: discord.Message, bot: discord.Client, connection, target_channel_id: int,
                                    reaction_threshold: int, config: dict = None):
    """
    Post a message in the Hall of Fame channel
    :param message:
    :param bot:
    :param connection:
    :param target_channel_id:
    :param reaction_threshold:
    :param config: The reaction related server configuration, fetched when not supplied
    :return:
    """
    # A member who asked not to be featured is left off every board. Their message stays where they
    # wrote it, but the bot neither reposts nor stores it. Checked here rather than on every reaction,
    # so it only costs a lookup when a message is about to be posted
    if opt_out_repo.is_opted_out(connection, message.author.id):
        return
    target_channel = bot.get_channel(target_channel_id)
    if target_channel is None:
        await report_missing_hall_of_fame_channel(bot, message.guild.id, target_channel_id)
        return
    video_link = check_video_extension(message)
    video_message = None

    if video_link:
        video_message = await target_channel.send(video_link)

    embed = await create_embed(message, reaction_threshold, connection, config)
    hall_of_fame_message = await target_channel.send(embed=embed)

    try:
        # The opt-out is checked again here, since sending the repost gave the member time to ask not to
        # be featured. The post is on the board by now, so it is kept there, credited to nobody
        author_id, at_post_limit = author_to_store(connection, int(message.author.id))
        hall_of_fame_message_repo.insert_hall_of_fame_message(connection,
                                                              int(message.id),
                                                              int(message.channel.id),
                                                              int(message.guild.id),
                                                              int(hall_of_fame_message.id),
                                                              int(await reaction_count(message, connection, config)),
                                                              author_id,
                                                              datetime.datetime.now(timezone.utc),
                                                              int(video_message.id) if video_link else None)
    except Exception as e:
        await hall_of_fame_message.delete()
        if video_message:
            await video_message.delete()
        await logging(bot, e, message.guild.id, log_level=log_type.CRITICAL)
        return

    if at_post_limit and message.author.id not in members_at_post_limit_logged:
        members_at_post_limit_logged.add(message.author.id)
        # The ID is needed to look into it, and the log channel is private to the developer
        await logging(bot, f"Member {message.author.id} has {member_post_limit} credited posts, the most allowed, so "
                           f"new posts of theirs are stored without an author. Worth checking for farmed reactions",
                      message.guild.id, log_level=log_type.CRITICAL, ping_developer=False)


def format_reactions_field_value(count: int, top_reaction) -> str:
    """
    User-facing reactions label.
    Examples:
      - "12 😂"
      - "12 reactions" (if no emoji)
    """
    emoji = str(top_reaction).strip() if top_reaction else ""
    return f"{count} {emoji}" if emoji else f"{count} reactions"


def truncate_content(content: str) -> str:
    """
    Truncate message content so that it fits within the 1024 character limit of an embed field
    :param content: The content of a message
    :return: The truncated content
    """
    if not content:
        return ""
    return content[:1021] + "..." if len(content) > 1024 else content


def embed_field_value(content: str) -> str:
    """
    Discord rejects embed fields with an empty value, so messages without text fall back to a zero width space
    :param content: The content of a message
    :return: A value that is safe to use for an embed field
    """
    return content if content else "​"


def add_post_footer(embed: discord.Embed, guild) -> discord.Embed:
    """
    Brand a Hall of Fame post, so members who see the board know which bot made it and how to get it
    :param embed: The post embed
    :param guild: The server the post is made in, whose bot member supplies the logo
    :return: The same embed, with the footer set
    """
    bot_member = getattr(guild, "me", None)
    # The global avatar rather than a server's custom bot profile, so the brand looks the same everywhere
    avatar = getattr(bot_member, "avatar", None)
    embed.set_footer(text=messages.POST_FOOTER, icon_url=avatar.url if avatar else None)
    return embed


async def create_embed(message: discord.Message, reaction_threshold: int, connection, config: dict = None) -> discord.Embed:
    """
    Create an embed for a message in the Hall of Fame channel
    :param message: The message to create an embed for
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :param connection: MySQL connection
    :param config: The reaction related server configuration, fetched when not supplied
    :return: The embed for the message
    """
    embed = await build_post_embed(message, connection, config)
    return add_post_footer(embed, message.guild)


async def build_post_embed(message: discord.Message, connection, config: dict = None) -> discord.Embed:
    """
    The content of a Hall of Fame post, laid out for the kind of message it is
    :param message: The message to create an embed for
    :param connection: MySQL connection
    :param config: The reaction related server configuration, fetched when not supplied
    :return: The embed for the message, without the footer
    """
    # handle 1024 character limit on embed description
    content = truncate_content(message.content)
    reference_message = None
    if message.reference and message.reference.message_id:
        try:
            reference_message = await message.channel.fetch_message(message.reference.message_id)
        except discord.HTTPException:
            # The message that was replied to is gone, so the reply is embedded on its own
            reference_message = None
    # A member who asked not to be featured is left off the board in replies too: their name, words and
    # image would otherwise go up with the reply. The reply is embedded on its own instead
    if reference_message is not None and opt_out_repo.is_opted_out(connection, reference_message.author.id):
        reference_message = None
    reference_content = truncate_content(reference_message.content) if reference_message else ""
    corrected_reactions = await reaction_count(message, connection, config)
    top_reaction = most_reacted_emoji(message.reactions, message.guild.id, connection, config)
    reactions_field_value = format_reactions_field_value(corrected_reactions, top_reaction)

    # Check if the message is a sticker and has a reference
    if reference_message and message.stickers:
        sticker = message.stickers[0]
        embed = discord.Embed(
            description=content,
            color=discord.Color.gold()
        )
        embed.set_image(url=sticker.url)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

        embed.add_field(name=f"{reference_message.author.name}'s message:", value=embed_field_value(reference_content), inline=False)

        embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        return embed

    # Check if the message is a sticker
    elif message.stickers:
        sticker = message.stickers[0]
        embed = discord.Embed(
            description=content,
            color=discord.Color.gold()
        )
        embed.set_image(url=sticker.url)
        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        return embed

    # Check if the message is a reply to another message
    elif reference_message and not message.attachments:
        embed = discord.Embed(
            color=discord.Color.gold()
        )

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

        if reference_message.attachments:

            # Author of the original message
            embed.add_field(name=f"{message.author.name}'s reply:", value=embed_field_value(content), inline=False)

            # Replied message
            embed.add_field(name=f"{reference_message.author.name}'s message:", value=embed_field_value(reference_content), inline=False)
            embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
            embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
            embed.set_image(url=reference_message.attachments[0].url)
        else:
            # Author of the replied message
            embed.add_field(name=f"{reference_message.author.name}'s message:", value=embed_field_value(reference_content), inline=False)
            # Author of the original message
            embed.add_field(name=f"{message.author.name}'s reply:", value=embed_field_value(content), inline=False)

            embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
            embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        return embed

    # Include the reference message in the embed if the message has both a reference and attachment with an image content type
    elif reference_message and message.attachments and message.attachments[0].content_type and message.attachments[0].content_type.startswith('image'):
        embed = discord.Embed(
            color=discord.Color.gold()
        )

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)

        # Original message
        embed.add_field(name=f"{reference_message.author.name}'s message:", value=embed_field_value(reference_content), inline=False)

        # Reply message
        embed.add_field(name=f"{message.author.name}'s reply:", value=embed_field_value(content), inline=False)
        embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        
        attachment = message.attachments[0]
        embed.set_image(url=attachment.url)
        return embed

    # Include the reference message in the embed if the message has both a reference and attachment but the attachment is not an image (e.g. video, file, etc.)
    elif reference_message and message.attachments:
        embed = discord.Embed(
            color=discord.Color.gold()
        )

        # Original message
        embed.add_field(name=f"{reference_message.author.name}'s message:", value=embed_field_value(reference_content), inline=False)

        # Reply message
        embed.add_field(name=f"{message.author.name}'s reply:", value=embed_field_value(content), inline=False)
        attachment = message.attachments[0]
        embed.add_field(name="Attachment", value=f"{attachment.url}", inline=False)

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)
        embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        return embed
    else:
        embed = discord.Embed(
            description=content,
            color=discord.Color.gold()
        )

        embed.set_author(name=message.author.name, icon_url=message.author.avatar.url if message.author.avatar else None)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        else:
            # Check for embedded images if there are no attachments
            for message_embed in message.embeds:
                if message_embed.type == 'image' and message_embed.url:
                    embed.set_image(url=message_embed.url)
                    break
                # Sometimes images from links are in the thumbnail or image attribute of a generic embed type
                elif message_embed.image:
                    embed.set_image(url=message_embed.image.url)
                    break
                elif message_embed.thumbnail:
                    embed.set_image(url=message_embed.thumbnail.url)
                    break

        embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
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


def board_topic_is_ours(topic) -> bool:
    """
    Whether the bot may set the topic of a board channel: it has none, or it is one the bot set itself
    :param topic: The channel's current topic
    :return: True when no admin has written the topic
    """
    return not topic or topic in messages.LEGACY_HOF_CHANNEL_TOPICS


async def refresh_board_topic(channel, permissions) -> bool:
    """
    Move a board still showing a topic from an earlier version to the current one. A topic an admin
    wrote, or removed, is left alone
    :param channel: The Hall of Fame channel
    :param permissions: The bot's permissions in that channel
    :return: True when the topic was changed
    """
    if channel.topic not in messages.LEGACY_HOF_CHANNEL_TOPICS or not permissions.manage_channels:
        return False
    await channel.edit(topic=messages.HOF_CHANNEL_TOPIC, reason="Updating the Hall of Fame channel topic")
    return True


def check_setup_view():
    # Imported here, as commands imports this module
    import commands
    return commands.build_check_setup_view()


def welcome_view():
    # Imported here, as commands imports this module
    import commands
    return commands.build_welcome_view()


async def report_setup_problems_on_join(bot, server, hall_of_fame_channel):
    """
    Right after the welcome message, point out anything that already stops posts, most often channels
    the bot cannot read because they sit behind a role it was never given. Silent when all is well
    :param bot: The Discord bot
    :param server: The server just joined
    :param hall_of_fame_channel: The board
    """
    try:
        # A new board starts with chat off
        findings = setup_check.join_findings(server, hall_of_fame_channel, allow_messages_in_hof_channel=False)
        if not setup_check.problems(findings):
            return
        # Only a pointer: the board is public, and the findings name channels and roles that are for admins
        await hall_of_fame_channel.send(messages.CHECK_JOIN_NUDGE.format(command=command_refs.TROUBLESHOOT),
                                        view=check_setup_view())
        await logging(bot, f"Setup problems on join: "
                           f"{', '.join(finding.title for finding in setup_check.problems(findings))}",
                      server.id, log_level=log_type.SYSTEM)
    except Exception as e:
        # The server is set up either way, so a failed report must not undo the join
        await logging(bot, f"Failed to report setup problems on join: {e}", server.id)


async def create_database_context(bot, server, connection, custom_channel=None) -> server_class.Server:
    """
    Create a database context for the server
    :param bot: The Discord bot
    :param server: The server object
    :param connection: MySQL connection
    :param custom_channel: Optional custom channel for the Hall of Fame channel
    :return: The database context
    """
    # server_member_count = sum(1 for member in server.members if not member.bot) // todo: enable when members intent
    server_member_count = server.member_count

    reaction_threshold_default = (
        1 if server_member_count < 3 else
        2 if server_member_count < 5 else
        3 if server_member_count < 10 else
        4 if server_member_count < 20 else
        5 if server_member_count < 40 else
        6 if server_member_count < 50 else
        7
    )

    if server_config_repo.check_if_guild_exists(connection, server.id):
        await logging(bot, "Server already exists in the database, dropping it to recreate", server.id)
        server_config_repo.delete_server_config(connection, server.id)

    hall_of_fame_channel = custom_channel or await server.create_text_channel("hall-of-fame")

    if server.me.guild_permissions.manage_channels:
        # A channel picked with /set_hall_of_fame_channel keeps the topic its admins gave it
        if board_topic_is_ours(hall_of_fame_channel.topic):
            await hall_of_fame_channel.edit(topic=messages.HOF_CHANNEL_TOPIC, reason="Creating Hall of Fame channel")
        await hall_of_fame_channel.set_permissions(server.me, read_messages=True, send_messages=True)
        await hall_of_fame_channel.set_permissions(server.default_role, read_messages=True, send_messages=False)

    leader_board_messages = []

    server_config_repo.insert_server_with_parameters(connection, server.id, hall_of_fame_channel.id,
                                                reaction_threshold_default, 1000, leader_board_messages,
                                                1000, False, True, False, False,
                                                [], datetime.datetime.now(timezone.utc), False, False,
                                                server_member_count, calculation_method_type.MOST_REACTIONS_ON_EMOJI, True, False,
                                                True)

    await hall_of_fame_channel.send(
        messages.HOF_WELCOME.format(threshold=reaction_threshold_default),
        view=welcome_view()
    )
    await report_setup_problems_on_join(bot, server, hall_of_fame_channel)

    new_server_class = server_class.Server(
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
        leaderboard_message_ids=[],
        ignore_bot_messages=False,
        reaction_count_calculation_method=calculation_method_type.MOST_REACTIONS_ON_EMOJI,
        hide_hof_post_below_threshold=True,
        server_member_count=server_member_count,
        require_image_or_video=False,
        count_in_global_profiles=True
    )
    return new_server_class


def delete_database_context(server_id: int, connection):
    """
    Delete the database context for the server
    :param server_id: The ID of the server
    :param connection: MySQL connection
    :return: None
    """
    hall_of_fame_message_repo.delete_hall_of_fame_messages_for_guild(connection, server_id)
    server_user_repo.delete_server_users(connection, server_id)
    server_config_repo.delete_server_config(connection, server_id)
    hof_wrapped_repo.delete_hof_wrapped_for_guild(connection, server_id)
    # Left behind, a guild that rejoins stays marked as done for the year and never gets its wrapped again
    hof_wrapped_guild_status_repo.delete_progress_for_guild(connection, server_id)


async def logging(bot: discord.Client, message, server_id=None, new_value=None, log_level=log_type.ERROR,
                  validate_for_duplicates=False, ping_developer=True):
    """
    Log an error message to the error channel
    :param bot:
    :param message:
    :param server_id: The ID of the server
    :param new_value: The new value of the server configuration
    :param log_level: The type of log message
    :param validate_for_duplicates: Whether to check for duplicate logging messages
    :param ping_developer: Whether a critical message mentions the developer. Turned off for critical
        events that recur on their own, such as a server reaching its daily post limit, which belong
        in the critical channel but would otherwise ping on every repeat
    :return:
    """
    log_channels = {
        log_type.ERROR: 1344070396575617085 if bot.application_id == 1177041673352663070 else 1383834395726577765,
        log_type.SYSTEM: 1373699890718441482 if bot.application_id == 1177041673352663070 else 1383834858870145214,
        log_type.COMMAND: 1436699144163954759 if bot.application_id == 1177041673352663070 else 1436699968571183106,
        log_type.CRITICAL: 1439692415454675045 if bot.application_id == 1177041673352663070 else 1439692461176787074
    }

    target_guild = bot.get_guild(1180006529575960616)
    date_formatted_message = f"{datetime.datetime.now()}: {message}"

    if new_value is not None:
        date_formatted_message += f"\n[Value: {new_value}]"
    if server_id:
        date_formatted_message += f"\n[Server ID: {server_id}]"

    channel_id = log_channels.get(log_level)
    if channel_id:
        channel = target_guild.get_channel(channel_id)

        # Checked in memory rather than by reading the channel history, which cost an API call per
        # log line and grew worst during the incidents that produce the most logging
        if validate_for_duplicates and not recently_logged_messages.add_if_absent(f"{log_level}:{server_id}:{message}"):
            return  # Do not send duplicate error message

        message_prefix = "<@230698327589650432> " if log_level == log_type.CRITICAL and ping_developer else ""
        await channel.send(f"{message_prefix}```diff\n{date_formatted_message}\n```")


# noinspection PyTypeChecker
async def create_feedback_form(interaction: discord.Interaction, bot, on_sent=None, refusal=None):
    """
    Create a feedback form for the user and send the feedback to the feedback channel
    :param interaction:
    :param bot:
    :param on_sent: Called with the member's user ID once the feedback reached the channel, so a form
        that is closed or fails does not count toward the member's daily limit
    :param refusal: Called with the member's user ID when the form is submitted. Returns what to answer
        instead of sending it, such as the daily limit being reached while other forms were open, or None
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
            refused = refusal(feedback_interaction.user.id) if refusal is not None else None
            if refused:
                await feedback_interaction.response.send_message(refused, ephemeral=True)
                return
            target_guild = bot.get_guild(1180006529575960616)
            target_channel = target_guild.get_channel(1345558910836412456)
            embed = discord.Embed(
                title="New feedback",
                color=discord.Color.gold()
            )
            embed.add_field(name=self.fb_title.label, value=self.fb_title.value, inline=False)
            embed.add_field(name=self.message.label, value=self.message.value, inline=False)
            embed.set_author(name=feedback_interaction.user.name, icon_url=feedback_interaction.user.avatar.url if feedback_interaction.user.avatar else None)
            # None in a DM or a server that only has the bot through a user install
            embed.add_field(name="Guild", value=feedback_interaction.guild_id or "None (user install)", inline=True)
            embed.add_field(name="UserId", value=feedback_interaction.user.id, inline=True)
            await target_channel.send(embed=embed)
            if on_sent is not None:
                on_sent(feedback_interaction.user.id)
            await feedback_interaction.response.send_message(f"Thanks for your feedback, {feedback_interaction.user.mention}")
            await asyncio.sleep(5)
            await feedback_interaction.delete_original_response()

    # noinspection PyUnresolvedReferences
    await interaction.response.send_modal(FeedbackModal())


# noinspection PyTypeChecker
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
    # noinspection PyUnresolvedReferences
    await interaction.response.send_modal(CustomProfilePictureAndCoverModal())


monthly_stats_window_days = 30

# How many guilds are rebuilt before the sweep hands control back to the event loop
user_stats_guilds_per_yield = 25

# The longest one guild's stats rebuild may run before the database cancels it
user_stats_statement_timeout_ms = 20_000


@contextmanager
def statement_timeout(connection, milliseconds: int):
    """
    Have the database cancel any statement on this connection that runs longer than the limit.

    psycopg2 blocks the event loop while a query runs, so an asyncio timeout cannot fire during a
    stalled one; only the database can stop it. The limit is set for the session rather than with
    SET LOCAL, because the repositories commit as they go and SET LOCAL would be dropped at the first
    commit. Connections are reused, so it is always reset afterwards, after rolling back a
    transaction the failure may have left aborted.
    :param connection: A connection that runs nothing else while the block is open
    :param milliseconds: The longest a single statement may run
    """
    _execute_and_commit(connection, "SET statement_timeout = %s", (milliseconds,))
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        _execute_and_commit(connection, "RESET statement_timeout")


def _execute_and_commit(connection, sql, params=None):
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
    finally:
        cursor.close()
    connection.commit()


def monthly_window_start(now=None):
    """
    The point the monthly hall of fame counters reach back to.

    Returned naive in UTC, because created_at is a TIMESTAMP without a time zone holding UTC wall
    time, and comparing it against an aware value would be resolved using the database session's
    time zone rather than UTC.
    :param now: The current time, taken from the clock when not supplied
    :return: A naive UTC timestamp
    """
    now = now if now is not None else datetime.datetime.now(timezone.utc)
    return (now - datetime.timedelta(days=monthly_stats_window_days)).replace(tzinfo=None)


async def update_user_database(bot: discord.Client, connection):
    """
    Recompute the hall of fame totals and ranks for every guild the bot is in.

    Every guild is measured against the same window, taken once here, so that the monthly counters
    are comparable across servers and a guild is not judged against a window a few seconds newer
    than its neighbour. The rebuild itself is one statement per guild and is left serial: it runs
    on a single database connection, so doing several at once would win nothing. What it does do
    is hand the event loop back between batches, since a run of synchronous rebuilds would
    otherwise hold the loop for the whole sweep and leave reactions queueing behind it.
    :param bot: The Discord bot
    :param connection: The database connection
    :return: None
    """
    await logging(bot, f"Updating user database...")
    window_start = monthly_window_start()

    rebuilt = 0
    failed = 0
    # Each rebuild blocks the event loop while it runs, so the database cancels any one that stalls
    # rather than letting it freeze reactions and commands. A cancelled rebuild fails like any other
    # and the sweep carries on with the next guild
    with statement_timeout(connection, user_stats_statement_timeout_ms):
        for position, guild in enumerate(bot.guilds, start=1):
            try:
                server_user_repo.rebuild_user_stats_for_guild(connection, guild.id, window_start)
                rebuilt += 1
            except Exception as e:
                failed += 1
                # A failed statement aborts the transaction, and every guild after it shares this
                # connection, so it is reset here rather than failing the rest of the sweep
                connection.rollback()
                await logging(bot, f"Failed to update user stats for guild {guild.id}: {e}", guild.id)
            if position % user_stats_guilds_per_yield == 0:
                await asyncio.sleep(0)
    await logging(bot, f"Finished updating user database: {rebuilt} rebuilt, {failed} failed")


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
    await logging(bot, f"Joined a server with permissions:\n"
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
                             f"Server member count: {server.member_count}", server.id, log_level=log_type.SYSTEM)


async def send_message_to_highest_prio_channel(bot: discord.Client, guild: discord.Guild, message_content: str) -> bool:
    """
    Send a message to the highest priority channel in the guild where the bot has permission to send messages.
    Callers keep track of what they already said themselves, as reading channel history to find out costs an
    API call per server
    :param bot: The Discord bot
    :param guild: The guild to send the message to
    :param message_content: The content of the message to send
    :return: True when the message was posted
    """
    for alt_channel in sorted(guild.text_channels, key=lambda c: c.position):
        alt_permissions = alt_channel.permissions_for(guild.me)
        if alt_permissions.send_messages and alt_permissions.view_channel:
            try:
                await alt_channel.send(message_content)
                await logging(bot, f"Sent the missing permissions message to channel {alt_channel.id}", guild.id)
                return True
            except Exception as e:
                await logging(bot, f"Failed to send the missing permissions message to channel {alt_channel.id}: {e}",
                              guild.id)
    return False
