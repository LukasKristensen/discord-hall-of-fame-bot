"""
The setup check behind /check_setup, the button on the welcome message and the report on join.

A board that never posts looks the same as a server where nobody reacts enough, so the admin rarely
finds out what is wrong. Each check here names one thing that stops posts, and how to fix it.

Everything except the post activity is worked out from Discord's cached permissions, so it costs no
API calls and the join report needs no database.
"""
import datetime
from dataclasses import dataclass
from datetime import timezone

import discord

from enums import calculation_method_type, command_refs
from translations import messages

OK = "ok"
WARN = "warn"
FAIL = "fail"
INFO = "info"

LEVEL_ICONS = {OK: "✅", WARN: "⚠️", FAIL: "❌", INFO: "ℹ️"}

# Channel kinds members react in. Threads follow their parent channel, so they are not counted apart
REACTABLE_CHANNEL_TYPES = {
    discord.ChannelType.text,
    discord.ChannelType.news,
    discord.ChannelType.voice,
    discord.ChannelType.stage_voice,
    discord.ChannelType.forum,
}

# A role with any of these runs the server rather than takes part in it, so a channel only it can see
# is a staff channel the bot is left out of on purpose
STAFF_PERMISSIONS = ("administrator", "manage_guild", "manage_channels", "manage_roles", "manage_messages",
                     "kick_members", "ban_members", "moderate_members")

# Above this many role and channel pairs the role analysis is skipped, so a huge server cannot hold
# the event loop. Channels are then judged by @everyone alone
MAX_ROLE_CHECKS = 20_000

MAX_LISTED_CHANNELS = 10
# A server this old without a single post most likely has a threshold nobody reaches
QUIET_AFTER_DAYS = 7
STALE_AFTER_DAYS = 30


@dataclass
class Finding:
    level: str
    title: str
    detail: str


@dataclass
class ChannelVisibility:
    readable: list
    # Regular members can see these, the bot cannot. Almost always a mistake
    blocked: list
    # Only staff, or nobody, can see these. Usually on purpose
    private: list
    suggested_role: discord.Role | None = None
    suggested_role_opens: int = 0

    @property
    def total(self) -> int:
        return len(self.readable) + len(self.blocked) + len(self.private)


def bot_can_read(channel, bot_member) -> bool:
    # Without Read Message History the reaction arrives, but the message it is on cannot be fetched
    permissions = channel.permissions_for(bot_member)
    return permissions.view_channel and permissions.read_message_history


def is_member_role(role, guild) -> bool:
    """A role regular members hold: not @everyone, not a bot's own role, and not a staff role."""
    if role.id == guild.id or role.managed:
        return False
    return not any(getattr(role.permissions, name, False) for name in STAFF_PERMISSIONS)


def role_can_read(channel, role) -> bool:
    permissions = channel.permissions_for(role)
    return permissions.view_channel and permissions.read_message_history


def channel_visibility(guild, board_channel_id: int | None) -> ChannelVisibility:
    """
    Sort every channel members can react in by whether the bot can read it
    :param guild: The server
    :param board_channel_id: The board, which is left out as nothing there is featured
    :return: The channels the bot reads, the ones members see but it does not, and private ones
    """
    channels = [channel for channel in getattr(guild, "channels", [])
                if channel.type in REACTABLE_CHANNEL_TYPES and channel.id != board_channel_id]
    readable, unreadable = [], []
    for channel in channels:
        (readable if bot_can_read(channel, guild.me) else unreadable).append(channel)

    member_roles = [role for role in getattr(guild, "roles", []) if is_member_role(role, guild)]
    check_roles = len(unreadable) * len(member_roles) <= MAX_ROLE_CHECKS

    blocked, private = [], []
    opened_by_role = {}
    for channel in unreadable:
        roles_that_read = [role for role in member_roles if role_can_read(channel, role)] if check_roles else []
        for role in roles_that_read:
            opened_by_role[role] = opened_by_role.get(role, 0) + 1
        if channel.permissions_for(guild.default_role).view_channel or roles_that_read:
            blocked.append(channel)
        else:
            private.append(channel)

    visibility = ChannelVisibility(readable=readable, blocked=blocked, private=private)
    if opened_by_role:
        # The role that opens the most channels, and among equals the highest one, as that is
        # usually the general member role rather than a niche one
        role, opens = max(opened_by_role.items(), key=lambda item: (item[1], item[0].position))
        visibility.suggested_role, visibility.suggested_role_opens = role, opens
    return visibility


def list_channels(channels) -> str:
    """Channel mentions, cut short so a large server stays within an embed field."""
    shown = " ".join(channel.mention for channel in channels[:MAX_LISTED_CHANNELS])
    hidden = len(channels) - MAX_LISTED_CHANNELS
    return shown + (messages.CHECK_AND_MORE.format(count=hidden) if hidden > 0 else "")


def board_findings(board_channel, bot_member, allow_messages_in_hof_channel: bool) -> list[Finding]:
    if board_channel is None:
        return [Finding(FAIL, messages.CHECK_BOARD_MISSING_TITLE,
                        messages.CHECK_BOARD_MISSING.format(command=command_refs.SET_HALL_OF_FAME_CHANNEL))]

    permissions = board_channel.permissions_for(bot_member)
    required = [
        ("View Channel", permissions.view_channel),
        ("Send Messages", permissions.send_messages),
        ("Read Message History", permissions.read_message_history),
        ("Embed Links", permissions.embed_links),
    ]
    missing = [name for name, granted in required if not granted]
    if missing:
        return [Finding(FAIL, messages.CHECK_BOARD_PERMISSIONS_TITLE,
                        messages.CHECK_BOARD_PERMISSIONS.format(channel=board_channel.mention,
                                                                missing=", ".join(missing)))]

    findings = [Finding(OK, messages.CHECK_BOARD_OK_TITLE,
                        messages.CHECK_BOARD_OK.format(channel=board_channel.mention))]
    if not allow_messages_in_hof_channel and not permissions.manage_messages:
        findings.append(Finding(WARN, messages.CHECK_BOARD_CLEANUP_TITLE,
                                messages.CHECK_BOARD_CLEANUP.format(channel=board_channel.mention,
                                                                    command=command_refs.ALLOW_MESSAGES_IN_HOF_CHANNEL)))
    return findings


def reads_too_few(visibility: ChannelVisibility) -> bool:
    """
    Whether the bot is shut out of most channels. A few staff channels are normal, but a bot that reads
    fewer than half is more likely missing access by accident, even when no regular role sees them
    either, such as on a new server where only the owner has been let in
    """
    return len(visibility.readable) * 2 < visibility.total


def channel_findings(visibility: ChannelVisibility) -> list[Finding]:
    title = messages.CHECK_CHANNELS_TITLE.format(readable=len(visibility.readable), total=visibility.total)
    too_few = reads_too_few(visibility)
    lines = []
    if visibility.blocked:
        lines.append(messages.CHECK_CHANNELS_BLOCKED.format(channels=list_channels(visibility.blocked)))
        if visibility.suggested_role is not None:
            lines.append(messages.CHECK_CHANNELS_ROLE_FIX.format(role=visibility.suggested_role.mention,
                                                                 opens=visibility.suggested_role_opens,
                                                                 total=len(visibility.blocked)))
        else:
            lines.append(messages.CHECK_CHANNELS_FIX)
    if visibility.private:
        # Named, as the answer is only shown to the admin who asked
        template = messages.CHECK_CHANNELS_MOSTLY_CLOSED if too_few else messages.CHECK_CHANNELS_PRIVATE
        lines.append(template.format(count=len(visibility.private), channels=list_channels(visibility.private)))
    if not lines:
        lines.append(messages.CHECK_CHANNELS_ALL)
    return [Finding(WARN if visibility.blocked or too_few else OK, title, "\n".join(lines))]


def rule_findings(server_config, member_count: int | None) -> list[Finding]:
    findings = []
    if server_config.custom_emoji_check_logic and not server_config.whitelisted_emojis:
        findings.append(Finding(FAIL, messages.CHECK_EMPTY_WHITELIST_TITLE,
                                messages.CHECK_EMPTY_WHITELIST.format(whitelist=command_refs.WHITELIST_EMOJI,
                                                                      logic=command_refs.CUSTOM_EMOJI_CHECK_LOGIC)))
    # Total reactions can pass the member count, as one member can add several emojis
    counts_people = server_config.reaction_count_calculation_method != calculation_method_type.TOTAL_REACTIONS
    # Without the author's own reaction, every member but the author is the most a message can get
    counts_author = server_config.include_author_in_reaction_calculation
    reachable = member_count if counts_author else (member_count or 0) - 1
    if counts_people and member_count and server_config.reaction_threshold > reachable:
        template = (messages.CHECK_THRESHOLD_UNREACHABLE if counts_author
                    else messages.CHECK_THRESHOLD_UNREACHABLE_WITHOUT_AUTHOR)
        findings.append(Finding(WARN, messages.CHECK_THRESHOLD_UNREACHABLE_TITLE, template.format(
            threshold=server_config.reaction_threshold, members=member_count,
            command=command_refs.SET_REACTION_THRESHOLD, include=command_refs.INCLUDE_AUTHORS_REACTION)))
    return findings


def activity_findings(activity: dict, threshold: int, joined_at, daily_post_limit: int,
                      now: datetime.datetime = None) -> list[Finding]:
    """
    :param activity: total, latest and today, as hall_of_fame_message_repo.get_post_activity returns
    :param threshold: The server's reaction threshold
    :param joined_at: When the bot joined the server, None when unknown
    :param daily_post_limit: Posts a server may have in a day
    :param now: The current time, for tests
    """
    now = now or datetime.datetime.now(timezone.utc)
    findings = []
    if activity["today"] >= daily_post_limit:
        findings.append(Finding(WARN, messages.CHECK_DAILY_LIMIT_TITLE,
                                messages.CHECK_DAILY_LIMIT.format(limit=daily_post_limit)))

    latest = activity["latest"]
    if latest is None:
        days_installed = (now - joined_at).days if joined_at else 0
        if days_installed >= QUIET_AFTER_DAYS:
            findings.append(Finding(WARN, messages.CHECK_NO_POSTS_TITLE,
                                    messages.CHECK_NO_POSTS.format(days=days_installed, threshold=threshold,
                                                                   command=command_refs.SET_REACTION_THRESHOLD)))
        else:
            findings.append(Finding(INFO, messages.CHECK_NO_POSTS_YET_TITLE, messages.CHECK_NO_POSTS_YET))
        return findings

    if latest.tzinfo is None:
        # Stored as UTC without a zone
        latest = latest.replace(tzinfo=timezone.utc)
    level = WARN if (now - latest).days >= STALE_AFTER_DAYS else INFO
    detail = messages.CHECK_LAST_POST.format(when=f"<t:{int(latest.timestamp())}:R>", total=activity["total"])
    if level == WARN:
        detail += "\n" + messages.CHECK_LAST_POST_STALE.format(command=command_refs.SET_REACTION_THRESHOLD)
    findings.append(Finding(level, messages.CHECK_LAST_POST_TITLE, detail))
    return findings


def join_findings(guild, board_channel, allow_messages_in_hof_channel: bool) -> list[Finding]:
    """What can already be wrong the moment the bot joins: the board and the channels it cannot read."""
    return (board_findings(board_channel, guild.me, allow_messages_in_hof_channel)
            + channel_findings(channel_visibility(guild, getattr(board_channel, "id", None))))


def check_server(guild, board_channel, server_config, activity: dict, daily_post_limit: int,
                 now: datetime.datetime = None) -> list[Finding]:
    joined_at = getattr(guild.me, "joined_at", None)
    return (join_findings(guild, board_channel, server_config.allow_messages_in_hof_channel)
            + rule_findings(server_config, guild.member_count)
            + activity_findings(activity, server_config.reaction_threshold, joined_at, daily_post_limit, now))


def problems(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.level in (WARN, FAIL)]


def build_embed(findings: list[Finding]) -> discord.Embed:
    found = problems(findings)
    failing = any(finding.level == FAIL for finding in found)
    embed = discord.Embed(
        title=messages.CHECK_TITLE,
        description=(messages.CHECK_SUMMARY_PROBLEMS.format(count=len(found), plural="" if len(found) == 1 else "s")
                     if found else messages.CHECK_SUMMARY_OK),
        color=discord.Color.red() if failing else discord.Color.orange() if found else discord.Color.green()
    )
    for finding in findings:
        # An embed field holds 1024 characters, and the channel list is the only part that can grow
        embed.add_field(name=f"{LEVEL_ICONS[finding.level]} {finding.title}", value=finding.detail[:1024],
                        inline=False)
    embed.set_footer(text=messages.CHECK_FOOTER)
    return embed
