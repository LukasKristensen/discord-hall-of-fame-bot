"""
Why one message is or is not on the board, for the Why isn't this on the board? message command.

It goes through the same steps as utils.validate_message, in the same order, and shares its rules
through utils.rule_blocking_post, so a member is told what the bot actually does with the message.
Unlike validate_message it only reads: it never posts, edits or logs a member.
"""
import datetime
from dataclasses import dataclass

import discord

import commands
import setup_check
import utils
from enums import command_refs
from message_reactions import reaction_count
from repositories import hall_of_fame_message_repo, opt_out_repo
from translations import messages

# What the answer is, kept apart from the text so the log can say it without the message
IS_BOARD = "is_board"
CANNOT_READ = "cannot_read"
ALREADY_POSTED = "already_posted"
HIDDEN = "hidden"
NO_BOARD = "no_board"
CANNOT_POST = "cannot_post"
DAILY_LIMIT = "daily_limit"
MESSAGE_GONE = "message_gone"
POSTED_ELSEWHERE = "posted_elsewhere"
BELOW_THRESHOLD = "below_threshold"
CANNOT_FEATURE = "cannot_feature"
QUALIFIES = "qualifies"

# The most whitelisted emojis listed in an answer, which stays short enough to read at a glance
whitelist_listed_limit = 10


@dataclass
class Verdict:
    reason: str
    text: str


def post_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def rule_text(rule: str, server_config) -> str:
    if rule == utils.RULE_TOO_OLD:
        return messages.WHY_TOO_OLD.format(days=server_config.post_due_date, command=command_refs.SET_POST_DUE_DATE)
    if rule == utils.RULE_BOT_MESSAGE:
        return messages.WHY_BOT_MESSAGE.format(command=command_refs.IGNORE_BOT_MESSAGES)
    return messages.WHY_NO_MEDIA.format(command=command_refs.REQUIRE_IMAGE_OR_VIDEO)


def below_threshold_text(count: int, server_config) -> str:
    """How far the message is from the threshold, and how the server counts, since that is the usual surprise"""
    method = commands.calculation_method_labels.get(server_config.reaction_count_calculation_method,
                                                    str(server_config.reaction_count_calculation_method))
    lines = [messages.WHY_BELOW_THRESHOLD.format(count=count, threshold=server_config.reaction_threshold),
             messages.WHY_METHOD.format(method=method.lower())]
    if not server_config.include_author_in_reaction_calculation:
        lines.append(messages.WHY_AUTHOR_NOT_COUNTED)
    whitelist = server_config.whitelisted_emojis or []
    if server_config.custom_emoji_check_logic and whitelist:
        emojis = " ".join(str(emoji) for emoji in whitelist[:whitelist_listed_limit])
        if len(whitelist) > whitelist_listed_limit:
            emojis += messages.CHECK_AND_MORE.format(count=len(whitelist) - whitelist_listed_limit)
        lines.append(messages.WHY_WHITELIST.format(emojis=emojis))
    return "\n".join(lines)


async def lookup(connect, read):
    """Run one database read on a connection borrowed just for it"""
    async with connect() as connection:
        return read(connection)


async def explain(message: discord.Message, asked_by_id: int, bot: discord.Client, connect, server_config,
                  now: datetime.datetime = None) -> Verdict:
    """
    Work out why a message is or is not on the board
    :param message: The message the member asked about, as the interaction carries it
    :param asked_by_id: Who asked, since only the author is told that they asked not to be featured
    :param bot: The Discord bot
    :param connect: Returns an async context manager that lends a database connection. One is borrowed per
        lookup rather than held, since the fetch and the reaction counting are Discord requests
    :param server_config: The in memory configuration of the server
    :param now: The current time, for tests
    :return: The reason and the answer to show the member
    """
    guild = message.guild
    board_id = server_config.hall_of_fame_channel_id
    if message.channel.id == board_id:
        return Verdict(IS_BOARD, messages.WHY_IS_BOARD)

    # The interaction carries the message even from a channel the bot cannot read, which is exactly the
    # case validate_message gives up on without a word
    channel = bot.get_channel(message.channel.id)
    permissions = channel.permissions_for(guild.me) if channel is not None else None
    if permissions is None or not (permissions.read_messages and permissions.read_message_history):
        return Verdict(CANNOT_READ, messages.WHY_CANNOT_READ.format(channel=message.channel.mention,
                                                                    command=command_refs.TROUBLESHOOT))

    # Fetched again, as validate_message does, so the reactions are the current ones
    try:
        source_message = await channel.fetch_message(message.id)
    except (discord.NotFound, discord.Forbidden):
        # Deleted since the member opened the menu: an ordinary event, not an error to report
        return Verdict(MESSAGE_GONE, messages.WHY_MESSAGE_GONE)
    db_message = await lookup(connect, lambda connection: hall_of_fame_message_repo.find_hall_of_fame_message(
        connection, guild.id, channel.id, message.id))
    reaction_config = server_config.reaction_config()
    rule = utils.rule_blocking_post(source_message, db_message, server_config, now)
    board = bot.get_channel(board_id)

    if db_message:
        return await explain_stored_post(source_message, db_message, board, rule, connect, server_config)

    if rule is not None:
        return Verdict(rule, rule_text(rule, server_config))

    if board is None:
        return Verdict(NO_BOARD, messages.WHY_NO_BOARD.format(command=command_refs.SET_HALL_OF_FAME_CHANNEL))
    missing = setup_check.missing_board_permissions(board.permissions_for(guild.me))
    if missing:
        return Verdict(CANNOT_POST, messages.WHY_CANNOT_POST.format(missing=", ".join(missing), channel=board.mention,
                                                                    command=command_refs.TROUBLESHOOT))

    if await at_daily_limit(connect, guild.id):
        return Verdict(DAILY_LIMIT, messages.WHY_DAILY_LIMIT.format(limit=utils.daily_post_limit))

    # The server's config is given, so counting reads nothing from the database
    count = await reaction_count(source_message, None, reaction_config)
    if count < server_config.reaction_threshold:
        return Verdict(BELOW_THRESHOLD, below_threshold_text(count, server_config))

    # Last, so that an opted-out member's message is explained like any other until this is the only reason
    if await lookup(connect, lambda connection: opt_out_repo.is_opted_out(connection, source_message.author.id)):
        if source_message.author.id == asked_by_id:
            return Verdict(CANNOT_FEATURE, messages.WHY_AUTHOR_OPTED_OUT.format(command=command_refs.MY_DATA))
        return Verdict(CANNOT_FEATURE, messages.WHY_CANNOT_FEATURE)

    return Verdict(QUALIFIES, messages.WHY_QUALIFIES)


async def post_is_shown(board, post_id) -> bool | None:
    """
    Whether a stored post shows on the board now, read from the post itself
    :return: True when it shows, False when it was hidden, None when it cannot be found in this board
    """
    if board is None or not post_id:
        return None
    try:
        post = await board.fetch_message(int(post_id))
    except discord.HTTPException:
        # Not in this board: it was moved since, or the post was deleted
        return None
    return bool(post.embeds)


async def at_daily_limit(connect, guild_id: int) -> bool:
    return await lookup(connect, lambda connection: hall_of_fame_message_repo.guild_message_count_today(
        connection, guild_id)) >= utils.daily_post_limit


async def explain_stored_post(source_message, db_message, board, rule, connect, server_config) -> Verdict:
    """
    A message that was posted before. The answer comes from what the board shows, since validate_message
    returns on a blocking rule or the daily limit before it hides or restores a post, so the reaction
    count alone does not say which state the post is in
    """
    guild = source_message.guild
    post_id = db_message.get("hall_of_fame_message_id")
    shown = await post_is_shown(board, post_id)
    if shown is None:
        # A link built from the board the server has now would lead nowhere
        return Verdict(POSTED_ELSEWHERE, messages.WHY_POSTED_ELSEWHERE.format(
            board=board.mention if board is not None else f"<#{server_config.hall_of_fame_channel_id}>"))
    if shown:
        return Verdict(ALREADY_POSTED, messages.WHY_ALREADY_POSTED.format(
            link=post_link(guild.id, board.id, post_id)))

    # Hidden. It only comes back when nothing stops validate_message before it gets that far
    if rule is not None:
        return Verdict(rule, rule_text(rule, server_config))
    if await at_daily_limit(connect, guild.id):
        return Verdict(DAILY_LIMIT, messages.WHY_DAILY_LIMIT.format(limit=utils.daily_post_limit))
    count = await reaction_count(source_message, None, server_config.reaction_config())
    if count < server_config.reaction_threshold:
        return Verdict(HIDDEN, messages.WHY_HIDDEN.format(count=count, threshold=server_config.reaction_threshold))
    # Enough again: the next reaction brings it back, as it does for a message that qualifies
    return Verdict(QUALIFIES, messages.WHY_QUALIFIES)
