import discord
import datetime
from datetime import timezone
import asyncio
from contextlib import contextmanager
from message_reactions import filter_whitelisted_reactions, most_reacted_emoji, reaction_count
from classes import server_class
from enums import command_refs, log_type, calculation_method_type
from repositories import (server_config_repo, hall_of_fame_message_repo, server_user_repo, hof_wrapped_repo,
                          hof_wrapped_guild_status_repo, opt_out_repo, permission_warning_repo)
from caches import ExpiringSet
from constants import version
from translations import messages
import setup_check
from board_post import (EXPLICIT_CONTENT, GORE_CONTENT, SELF_HARM_CONTENT, NO_MENTIONS, POST_REACTIONS_ID,
                        content_scan_flags, create_post_view, featured_body, fetch_reply_context, hidden_post_view,
                        is_components_v2, linked_image_url, post_media_limit, post_shows, posted_reactions_line,
                        reactions_line, reply_context, truncate_content, walk_components)

daily_post_limit = 100
duplicate_log_window_seconds = 600
recently_logged_messages = ExpiringSet(ttl_seconds=duplicate_log_window_seconds)
# Guild ID to the day its reaching the daily post limit was last handled, so it is logged and announced once a day
daily_limit_handled_on = {}
# Guild IDs whose missing Hall of Fame channel has been logged, so each server is reported once per boot
missing_channels_logged = set()
# Discord's error code for having edited too many messages older than an hour in one channel
OLD_MESSAGE_EDIT_LIMIT_CODE = 30046
# How old a message has to be for its edits to count toward that limit
old_message_age = datetime.timedelta(hours=1)
old_message_edit_pause = datetime.timedelta(minutes=15)
# Guild ID to when the board's posts older than old_message_age may be edited again, after Discord
# refused an edit with OLD_MESSAGE_EDIT_LIMIT_CODE. Newer posts are not limited, so they keep updating.
# The stored counts keep updating meanwhile, and the next reaction after the pause brings the post up to date
old_message_edits_paused_until = {}
# The most posts credited to one member, across every server. It keeps what the bot stores about any one
# member small enough that /my_data can always send them all of it, which data protection law entitles
# them to: 10,000 posts is a file of about 2.5 MB. Posts past it still reach the server's board, but are
# stored without an author, so they add to no leaderboard, profile or Wrapped. Even one member writing
# every post a server's daily limit allows would need 100 days to reach it, so a member who does is also
# worth a look for farmed reactions
member_post_limit = 10_000
# Members whose reaching member_post_limit has been logged, so each is reported once per boot
members_at_post_limit_logged = set()


# The server's rules about which messages qualify, as rule_blocking_post names them
RULE_TOO_OLD = "too_old"
RULE_BOT_MESSAGE = "bot_message"
RULE_NO_MEDIA = "no_media"
RULE_AGE_RESTRICTED = "age_restricted"
RULE_FLAGGED_MEDIA = "flagged_media"
# Rules that keep a message off the board for safety rather than by the server's choice. A post already on
# the board that breaks one is hidden, and comes back once the rule stops applying
SAFETY_RULES = (RULE_AGE_RESTRICTED, RULE_FLAGGED_MEDIA)

# Discord's content scanning results on media in components on media in components, which have bits of their own, paired with the ones above
COMPONENT_SCAN_BITS = ((1 << 0, EXPLICIT_CONTENT), (1 << 1, GORE_CONTENT), (1 << 2, SELF_HARM_CONTENT))


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


def component_scan_flags(raw_components) -> int:
    """
    The content scanning results on the media of a Components V2 message, read from the components as
    Discord sent them, since discord.py does not read them yet. They use bits of their own, which are
    turned into the attachment ones
    :param raw_components: The message's components as Discord sent them
    :return: The EXPLICIT_CONTENT, GORE_CONTENT and SELF_HARM_CONTENT bits that are set
    """
    flags = 0
    pending = list(raw_components or [])
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            scan = item.get("content_scan_metadata")
            if isinstance(scan, dict):
                for component_bit, attachment_bit in COMPONENT_SCAN_BITS:
                    if (scan.get("flags") or 0) & component_bit:
                        flags |= attachment_bit
            pending.extend(item.values())
    return flags


async def fetch_raw_components(bot, channel_id: int, message_id: int):
    """
    A message's components as Discord sends them, where a Components V2 post carries the scanning results of
    its media. One request, made once per new post
    :return: The raw components, or None when they cannot be read
    """
    try:
        data = await bot.http.get_message(channel_id, message_id)
    except (discord.HTTPException, AttributeError):
        return None
    return data.get("components") if isinstance(data, dict) else None


def has_flagged_media(message, board, raw_components=None) -> bool:
    """
    Whether a message carries media Discord flagged that may not go on this board. Gore and self-harm are
    never reposted, since a repost puts them in front of members who did not choose to see them. Explicit
    media may go where Discord allows it: a board that is age-restricted itself
    :param message: The message, or a post on the board
    :param board: The board channel, None when it is missing
    :param raw_components: The message's components as Discord sent them, for a Components V2 post
    """
    flags = content_scan_flags(message) | component_scan_flags(raw_components)
    if flags & (GORE_CONTENT | SELF_HARM_CONTENT):
        return True
    return bool(flags & EXPLICIT_CONTENT) and not setup_check.is_age_restricted(board)


def rule_blocking_post(source_message: discord.Message, db_message, server_config: server_class.Server,
                       now: datetime.datetime = None, board=None) -> str | None:
    """
    The first of the server's rules about which messages qualify that a message breaks. Shared by
    validate_message and the Why isn't this on the board? command, so the explanation a member gets is
    the rule the bot actually applies
    :param source_message: The message that was reacted to
    :param db_message: Its stored Hall of Fame post, or None when it has none
    :param server_config: The in memory configuration of the server
    :param now: The current time, for tests
    :param board: The board channel, whose own age restriction decides what may be posted there
    :return: One of the RULE_ names, or None when the message breaks none of them
    """
    now = now or datetime.datetime.now(timezone.utc)
    # The safety rules come first, so a post already on the board that breaks one is hidden even when
    # another rule applies too. Discord keeps age-restricted content inside age-restricted channels
    if setup_check.is_age_restricted(source_message.channel) and not setup_check.is_age_restricted(board):
        return RULE_AGE_RESTRICTED
    # A forward shows the message it forwards, so its media is what is judged, while the author, channel
    # and age stay the forwarding message's
    body, _ = featured_body(source_message)
    if has_flagged_media(body, board):
        return RULE_FLAGGED_MEDIA
    # A post already on the board keeps being updated however old the message gets
    if (now - source_message.created_at).days > server_config.post_due_date and not db_message:
        return RULE_TOO_OLD
    if source_message.author.bot and server_config.ignore_bot_messages:
        return RULE_BOT_MESSAGE
    if server_config.require_image_or_video and not has_image_or_video(body):
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

    # The board's own posts, and messages written there, are never featured. Without this, reactions on a
    # post would repost the bot's own post once they reached the threshold
    if channel_id == target_channel_id:
        return

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
    target_channel = bot.get_channel(target_channel_id)

    rule = rule_blocking_post(source_message, db_message, server_config, board=target_channel)
    if rule is not None:
        if rule in SAFETY_RULES and db_message and target_channel is not None:
            # Posted before the rule existed, or Discord flagged its media since. Hidden like a post below
            # the threshold, so it is restored below once the rule stops applying, such as when the board
            # is made age-restricted too
            await hide_post(db_message, bot, target_channel, source_message)
        return

    if target_channel is None:
        await report_missing_hall_of_fame_channel(bot, guild_id, target_channel_id)
        return

    if hall_of_fame_message_repo.guild_message_count_today(connection, guild_id) >= daily_post_limit:
        # Every reaction lands here while the server is at its limit, so it is handled once a day. The
        # UTC day, since database sessions run in UTC and the limit counts from midnight UTC
        today = datetime.datetime.now(timezone.utc).date()
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
            await hide_post(db_message, bot, target_channel, source_message)
        return

    if db_message:
        try:
            message_to_update = await target_channel.fetch_message(db_message["hall_of_fame_message_id"])
        except discord.NotFound:
            # Not on this board: the board was moved since it was posted, or a moderator deleted the post. It
            # is not posted again, but its count is still stored, since the leaderboards and profiles read it.
            # The error used to end the reaction quietly, so these counts stopped for good
            hall_of_fame_message_repo.update_field_for_message(connection, guild_id, channel_id, message_id,
                                                              "reaction_count", corrected_reactions)
            return
        if post_shows(message_to_update):
            hall_of_fame_message_repo.update_field_for_message(connection, guild_id, channel_id, message_id, "reaction_count", corrected_reactions)
            await update_reaction_counter(db_message, bot, target_channel_id, reaction_threshold, connection,
                                          source_message, corrected_reactions, reaction_config)
            return
        else:
            # The post was hidden and is now back over the threshold, so it is restored with its current
            # count, which the leaderboards and profiles read from the database
            hall_of_fame_message_repo.update_field_for_message(connection, guild_id, channel_id, message_id, "reaction_count", corrected_reactions)
            await show_post(message_to_update, source_message, reaction_threshold, connection, reaction_config,
                            corrected_reactions)
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

    if not post_shows(hall_of_fame_message):
        # Post the message in the Hall of Fame channel if it was removed
        await show_post(hall_of_fame_message, discord_message, reaction_threshold, connection, config, corrected_reactions)
        return

    guild_id = discord_message.guild.id
    now = datetime.datetime.now(timezone.utc)
    paused_until = old_message_edits_paused_until.get(guild_id)
    if (paused_until is not None and now < paused_until
            and now - hall_of_fame_message.created_at >= old_message_age):
        return

    if corrected_reactions is None:
        corrected_reactions = await reaction_count(discord_message, connection, config)
    if is_components_v2(hall_of_fame_message):
        await update_post_view(hall_of_fame_message, discord_message, connection, config, corrected_reactions, now)
        return

    embed = hall_of_fame_message.embeds[0]
    top_reaction = most_reacted_emoji(discord_message.reactions, guild_id, connection, config)
    reactions_field_value = format_reactions_field_value(corrected_reactions, top_reaction)

    for i, field in enumerate(embed.fields):
        field_name = (field.name or "").strip()
        if field_name == "Reactions" or field_name.endswith("Reactions"):
            if field_name == "Reactions" and field.value == reactions_field_value:
                # Many reactions leave the count as it was, such as one that is not counted or a second
                # emoji from the same member. Editing anyway spends Discord's limit on edits to old
                # messages, which busy boards ran out of
                return
            embed.set_field_at(
                index=i,
                name="Reactions",
                value=reactions_field_value,
                inline=True
            )
            break

    await edit_old_post(hall_of_fame_message, guild_id, now, embed=embed)


async def update_post_view(post, message: discord.Message, connection, config: dict, counted: int,
                           now: datetime.datetime):
    """
    Bring a Components V2 post's counts up to date. The new reactions line is compared with the one shown
    first, so a reaction that changes nothing costs no edit and no fetch of the message replied to
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, message.guild.id)
    if posted_reactions_line(post) == reactions_line(message, config, counted):
        return
    await edit_old_post(post, message.guild.id, now, view=await create_post_view(message, connection, config, counted),
                        allowed_mentions=NO_MENTIONS)


async def edit_old_post(post, guild_id: int, now: datetime.datetime, **changes):
    """
    Edit a board post, pausing the server's edits to old posts when Discord says too many were made
    :param changes: What to edit, as message.edit takes it
    """
    try:
        await post.edit(**changes)
    except discord.HTTPException as error:
        if error.code != OLD_MESSAGE_EDIT_LIMIT_CODE:
            raise
        # Every further edit to an old post would be refused too, and each refusal was logged as an error
        old_message_edits_paused_until[guild_id] = now + old_message_edit_pause


async def hide_post(db_message, bot: discord.Client, target_channel, source_message: discord.Message):
    """
    Hide a post on the board, keeping the message so it can be restored, and blank the video link posted
    with it
    :param db_message: The stored post
    :param bot: The Discord bot
    :param target_channel: The board
    :param source_message: The message the post is of
    """
    await remove_embed(db_message, bot, target_channel.id)
    # The column is present and null for every post that is not a video
    video_link_message_id = db_message.get("video_link_message_id")
    if video_link_message_id is not None and source_message.attachments:
        video_link_message = await target_channel.fetch_message(int(video_link_message_id))
        await video_link_message.edit(content="** **", embed=None)


async def take_down_flagged_post(post: discord.Message, board, bot: discord.Client, guild_id: int,
                                 raw_components=None) -> bool:
    """
    Blank one of the bot's own messages on the board when Discord's content scanning flagged its media, such
    as the image of the message a post replies to. Scanning can finish after a message is sent, so Discord
    asks apps that repost media to check their messages again when they are updated, not only when sent
    :param post: A post or video link the bot sent to the board
    :param board: The board channel
    :param bot: The Discord bot
    :param guild_id: The server, for the log
    :param raw_components: The post's components as Discord sent them, where a Components V2 post carries the
        scanning results of its media. discord.py does not read those yet
    :return: True when the post was taken down
    """
    if not has_flagged_media(post, board, raw_components):
        return False
    try:
        await blank_post(post)
    except discord.NotFound:
        # Deleted meanwhile, which takes it down just as well
        return False
    await logging(bot, "Took down a board post whose media Discord's content scanning flagged", guild_id,
                  log_level=log_type.SYSTEM, validate_for_duplicates=True)
    return True


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
    await blank_post(hall_of_fame_message)


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

    guild_id = int(server_config.guild_id)
    places = min(20, len(msg_id_array))
    # Only the messages the leaderboard shows are fetched and counted, and each only once. Counting can
    # cost a request per member who reacted, and recounting ten messages that were never shown, then
    # fetching and counting the shown ones a second time for their embeds, took large servers past the
    # daily task's time limit every day
    most_reacted_messages = list(hall_of_fame_message_repo.find_top_messages_by_reaction_count(
        connection, guild_id, limit=places))[:places]
    reaction_config = server_config.reaction_config()

    for i, top_message in enumerate(most_reacted_messages):
        original_channel = bot.get_channel(int(top_message["channel_id"]))
        if not original_channel:
            # The channel was deleted or hidden from the bot since the message was featured.
            # Its place is left as it was, rather than losing the rest of the leaderboard with it
            continue
        try:
            hall_of_fame_message = await hall_of_fame_channel.fetch_message(int(msg_id_array[i]))
        except discord.NotFound:
            # Someone deleted this place's message. The other places are still updated
            continue
        except discord.Forbidden:
            # The bot cannot read its own board, so no place can be updated. The daily permission check
            # tells the server what is missing
            return
        try:
            original_message = await original_channel.fetch_message(int(top_message["message_id"]))
        except (discord.NotFound, discord.Forbidden):
            # Deleted since it was featured, or in a channel the bot can no longer read. Like a deleted
            # channel, this used to stop the whole update, so the same servers failed every day
            continue

        corrected_reactions = await reaction_count(original_message, connection, reaction_config)
        hall_of_fame_message_repo.update_field_for_message(connection, guild_id, original_message.channel.id,
                                                          original_message.id, "reaction_count", corrected_reactions)

        leaderboard_content = f"**HallOfFame#{i+1}**"
        if original_message.attachments:
            leaderboard_content += f"\n{original_message.attachments[0].url}"

        # Edited in one request, as editing the same message several times triples the rate limit cost
        try:
            await hall_of_fame_message.edit(
                content=leaderboard_content,
                embed=await create_embed(original_message, server_config.reaction_threshold, connection,
                                         reaction_config, corrected_reactions))
        except discord.Forbidden:
            return
        except discord.HTTPException as error:
            if error.code != OLD_MESSAGE_EDIT_LIMIT_CODE:
                raise
            # Every place is an old message, so the rest would be refused too. Tried again tomorrow
            return


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
    view = await create_post_view(message, connection, config)
    hall_of_fame_message = await target_channel.send(view=view, allowed_mentions=NO_MENTIONS)

    opted_out_meanwhile = False
    try:
        count = int(await reaction_count(message, connection, config))
        # Checked again, since sending the repost gave the member time to ask not to be featured. It is the
        # last thing before storing, with no await in between: the bot runs as one process, so nothing can
        # handle an opt-out between this check and the store
        if opt_out_repo.is_opted_out(connection, message.author.id):
            opted_out_meanwhile = True
        else:
            # Videos play inside the post, so new posts have no video link message
            stored_author = hall_of_fame_message_repo.insert_hall_of_fame_message(
                connection, int(message.id), int(message.channel.id), int(message.guild.id),
                int(hall_of_fame_message.id), count, int(message.author.id), datetime.datetime.now(timezone.utc),
                None, author_post_limit=member_post_limit)
    except Exception as e:
        await hall_of_fame_message.delete()
        await logging(bot, e, message.guild.id, log_level=log_type.CRITICAL)
        return

    if opted_out_meanwhile:
        # They asked not to be reposted, so the repost sent a moment before goes, and nothing is stored
        await hall_of_fame_message.delete()
        return

    # Nobody credited although the member had not opted out: they are at member_post_limit, which the store
    # checks under the author's lock so two posts at once cannot both slip under it
    at_post_limit = stored_author == hall_of_fame_message_repo.NO_AUTHOR_ID

    # Checked once stored, so a post taken down here can still be restored. A Components V2 post carries its
    # media's scanning results only in its raw components, which discord.py does not keep, so they are read
    # back. Results that arrive later come through events.on_raw_message_edit
    raw_components = await fetch_raw_components(bot, target_channel.id, hall_of_fame_message.id)
    await take_down_flagged_post(hall_of_fame_message, target_channel, bot, message.guild.id, raw_components)

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


async def create_embed(message: discord.Message, reaction_threshold: int, connection, config: dict = None,
                       corrected_reactions: int = None) -> discord.Embed:
    """
    Create an embed for a message in the Hall of Fame channel
    :param message: The message to create an embed for
    :param reaction_threshold: The minimum number of reactions for a message to be posted in the Hall of Fame
    :param connection: MySQL connection
    :param config: The reaction related server configuration, fetched when not supplied
    :param corrected_reactions: The already calculated reaction count, recalculated when not supplied
    :return: The embed for the message
    """
    embed = await build_post_embed(message, connection, config, corrected_reactions)
    return add_post_footer(embed, message.guild)


async def build_post_embed(message: discord.Message, connection, config: dict = None,
                           corrected_reactions: int = None) -> discord.Embed:
    """
    The content of a Hall of Fame post, laid out for the kind of message it is
    :param message: The message to create an embed for
    :param connection: MySQL connection
    :param config: The reaction related server configuration, fetched when not supplied
    :param corrected_reactions: The already calculated reaction count, recalculated when not supplied
    :return: The embed for the message, without the footer
    """
    # handle 1024 character limit on embed description
    content = truncate_content(message.content)
    reference_message = await fetch_reply_context(message, connection)
    reference_content = truncate_content(reference_message.content) if reference_message else ""
    if corrected_reactions is None:
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
            image_url = linked_image_url(message)
            if image_url:
                embed.set_image(url=image_url)

        embed.add_field(name="Reactions", value=reactions_field_value, inline=True)
        embed.add_field(name="Jump to Message", value=message.jump_url, inline=False)
        return embed


async def blank_post(post):
    """Hide a board post in place, so it can be restored with the same message"""
    if is_components_v2(post):
        await post.edit(view=hidden_post_view(), allowed_mentions=NO_MENTIONS)
    else:
        await post.edit(content="** **", embed=None)


async def show_post(post, message: discord.Message, reaction_threshold: int, connection, config: dict = None,
                    corrected_reactions: int = None):
    """Show a hidden board post again, in the format it was first posted in"""
    if is_components_v2(post):
        await post.edit(view=await create_post_view(message, connection, config, corrected_reactions),
                        allowed_mentions=NO_MENTIONS)
    else:
        await post.edit(embed=await create_embed(message, reaction_threshold, connection, config))


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
    # The note on join is about what stops posts, which the settings form cannot fix
    return commands.build_check_setup_view(with_settings=False)


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
        # Read again, since set_permissions does not update the object create_text_channel returned, and
        # a stale one could report a permission the bot has just granted itself as missing
        hall_of_fame_channel = await bot.fetch_channel(hall_of_fame_channel.id)
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
        # on_guild_join stores a bare row before setting a server up, which made every join log this
        # as an error. Only a row with a board is a configuration from an earlier visit
        if server_config_repo.get_parameter_value(connection, server.id, "hall_of_fame_channel_id") is not None:
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
    permission_warning_repo.delete_permission_warnings(connection, [server_id])


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


# The short field of the feedback form is a title, and the long one goes into a single embed field, which
# Discord caps at 1024 characters
feedback_title_max_length = 150
feedback_message_max_length = 1000
# The developer's copy is coloured by topic, so a bug report stands out in the channel. Other topics are gold
feedback_topic_colors = {"bug": discord.Color.red(), "idea": discord.Color.green(), "question": discord.Color.blue()}
# The most screenshots one piece of feedback can carry
feedback_max_screenshots = 3


class ImageUpload(discord.ui.FileUpload):
    """
    A file upload in a form that offers only images. Discord can filter the picker by file type since
    5 August 2026, which discord.py 2.7 has no option for, so the filter is added to what is sent
    """

    def to_component_dict(self):
        payload = super().to_component_dict()
        payload["file_types"] = ["image"]
        return payload


def feedback_screenshots(attachments, size_limit: int) -> tuple[list, int]:
    """
    The uploads that can go to the feedback channel. Discord's filter only checks the file name, so the
    content type is checked too. They are sent in one message, so an upload that would take them past what
    the bot may upload there is left out
    :param attachments: What the member uploaded in the form
    :param size_limit: The most bytes the bot can upload in the feedback channel
    :return: The screenshots to forward, and how many uploads were left out
    """
    kept, total = [], 0
    for attachment in attachments:
        if (len(kept) < feedback_max_screenshots and (attachment.content_type or "").startswith("image/")
                and total + attachment.size <= size_limit):
            kept.append(attachment)
            total += attachment.size
    return kept, len(attachments) - len(kept)


def build_feedback_embed(user, guild_id, topic: str, title_field: tuple[str, str],
                         message_field: tuple[str, str], may_contact: bool = False, screenshots: int = 0,
                         left_out: int = 0) -> discord.Embed:
    """
    The developer's copy of a piece of feedback, only ever posted in the private feedback channel
    :param user: The member who sent it
    :param guild_id: The server it was sent from, None in a DM or a server that has the bot through a user
        install only
    :param topic: The topic picked on /feedback, a key of messages.FEEDBACK_TOPICS
    :param title_field: The short field's label and what the member wrote in it
    :param message_field: The long field's label and what the member wrote in it
    :param may_contact: Whether the member ticked that the developer may message them about it
    :param screenshots: How many screenshots are attached to the message the embed is sent in
    :param left_out: How many uploads were left out, for not being images or being too large
    :return: The embed
    """
    embed = discord.Embed(title=f"New feedback: {messages.FEEDBACK_TOPICS.get(topic, topic)}",
                          color=feedback_topic_colors.get(topic, discord.Color.gold()))
    for label, value in (title_field, message_field):
        embed.add_field(name=label, value=value, inline=False)
    embed.set_author(name=user.name, icon_url=user.avatar.url if user.avatar else None)
    embed.add_field(name="Guild", value=guild_id or "None (user install)", inline=True)
    embed.add_field(name="UserId", value=user.id, inline=True)
    embed.add_field(name="May contact", value="Yes" if may_contact else "No", inline=True)
    if screenshots or left_out:
        value = f"{screenshots} attached" + (f", {left_out} left out" if left_out else "")
        embed.add_field(name="Screenshots", value=value, inline=True)
    # The version the member was on, so a bug report can be checked against what was fixed since
    embed.set_footer(text=f"Hall of Fame {version.VERSION}")
    return embed


# noinspection PyTypeChecker
async def create_feedback_form(interaction: discord.Interaction, bot, topic: str = "other", on_sent=None,
                               refusal=None, on_unsent=None):
    """
    Create a feedback form for the user and send the feedback to the feedback channel
    :param interaction:
    :param bot:
    :param topic: What the feedback is about, a key of messages.FEEDBACK_TOPICS. It decides what the form asks for
    :param on_sent: Called with the member's user ID as the feedback is sent, before the send's await, so
        two forms submitted at the same moment cannot both get past the daily limit
    :param on_unsent: Called with the member's user ID when sending failed, to take back on_sent
    :param refusal: Called with the member's user ID when the form is submitted. Returns what to answer
        instead of sending it, such as the daily limit being reached while other forms were open, or None
    :return:
    """
    form_title, title_label, title_placeholder, message_label, message_placeholder = messages.FEEDBACK_FORMS.get(
        topic, messages.FEEDBACK_FORMS["other"])

    class FeedbackModal(discord.ui.Modal):
        def __init__(self):
            super().__init__(title=form_title)
            self.fb_title = discord.ui.TextInput(
                style=discord.TextStyle.short,
                placeholder=title_placeholder,
                required=True,
                max_length=feedback_title_max_length
            )
            self.message = discord.ui.TextInput(
                style=discord.TextStyle.paragraph,
                placeholder=message_placeholder,
                required=True,
                max_length=feedback_message_max_length
            )
            # Each question sits on a Label around its input. Discord does not allow a label on the input
            # itself inside one, and discord.py 2.6 deprecated reading it there
            self.fb_title_label = discord.ui.Label(text=title_label, component=self.fb_title)
            self.message_label = discord.ui.Label(text=message_label, component=self.message)
            self.screenshots = ImageUpload(required=False, max_values=feedback_max_screenshots)
            self.screenshots_label = discord.ui.Label(text=messages.FEEDBACK_SCREENSHOTS_LABEL,
                                                      description=messages.FEEDBACK_SCREENSHOTS_DESCRIPTION,
                                                      component=self.screenshots)
            self.may_contact = discord.ui.Checkbox()
            self.may_contact_label = discord.ui.Label(text=messages.FEEDBACK_CONTACT_LABEL, component=self.may_contact)
            self.add_item(self.fb_title_label)
            self.add_item(self.message_label)
            self.add_item(self.screenshots_label)
            self.add_item(self.may_contact_label)

        async def on_submit(self, feedback_interaction) -> None:
            refused = refusal(feedback_interaction.user.id) if refusal is not None else None
            if refused:
                await feedback_interaction.response.send_message(refused, ephemeral=True)
                return
            target_guild = bot.get_guild(1180006529575960616)
            target_channel = target_guild.get_channel(1345558910836412456)
            screenshots, left_out = feedback_screenshots(self.screenshots.values, target_guild.filesize_limit)
            embed = build_feedback_embed(feedback_interaction.user, feedback_interaction.guild_id, topic,
                                         (self.fb_title_label.text, self.fb_title.value),
                                         (self.message_label.text, self.message.value),
                                         may_contact=self.may_contact.value, screenshots=len(screenshots),
                                         left_out=left_out)
            if on_sent is not None:
                on_sent(feedback_interaction.user.id)
            try:
                if screenshots:
                    # Downloading them can take longer than the three seconds Discord waits for an answer
                    await feedback_interaction.response.defer(ephemeral=True, thinking=True)
                # Uploaded again rather than linked, since the links Discord gives a form expire
                files = [await screenshot.to_file() for screenshot in screenshots]
                await target_channel.send(embed=embed, files=files)
            except Exception:
                # A form that failed does not count toward the member's daily limit
                if on_unsent is not None:
                    on_unsent(feedback_interaction.user.id)
                raise
            answer = (messages.FEEDBACK_SENT_SOME_LEFT_OUT.format(count=left_out, max=feedback_max_screenshots)
                      if left_out else messages.FEEDBACK_SENT)
            if screenshots:
                await feedback_interaction.followup.send(answer, ephemeral=True)
            else:
                await feedback_interaction.response.send_message(answer, ephemeral=True)

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
        profile_picture_url_input = discord.ui.Label(text="Custom Profile Picture URL", component=discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="Enter the URL of the profile picture for the bot",
            required=False,
            default=default_profile_url
        ))
        cover_url_input = discord.ui.Label(text="Custom Cover Image URL", component=discord.ui.TextInput(
            style=discord.TextStyle.short,
            placeholder="Enter the URL of the cover image for the bot",
            required=False,
            default=default_cover_url
        ))

        async def on_submit(self, custom_profile_interaction) -> None:
            target_guild = bot.get_guild(1180006529575960616)
            target_channel = target_guild.get_channel(1439704492928012360)
            embed = discord.Embed(
                title="New Custom Profile Picture and Cover Request",
                color=discord.Color.gold()
            )
            embed.add_field(name=self.profile_picture_url_input.text, value=self.profile_picture_url_input.component.value, inline=False)
            embed.add_field(name=self.cover_url_input.text, value=self.cover_url_input.component.value, inline=False)
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
