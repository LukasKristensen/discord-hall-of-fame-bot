import datetime
import json
from datetime import timezone
import discord
import utils
from constants import version
from enums import command_refs, calculation_method_type
from repositories import server_config_repo, server_user_repo, hall_of_fame_message_repo
from caches import ExpiringSet
from translations import messages

INVITE_LINK = (messages.INVITE_BUTTON, messages.INVITE_URL)
VOTE_LINK = (messages.VOTE_BUTTON, messages.VOTE_URL)
SUPPORT_SERVER_LINK = (messages.SUPPORT_SERVER_BUTTON, messages.SUPPORT_SERVER_URL)


def build_link_buttons(*links: tuple[str, str]) -> discord.ui.View:
    """
    A row of link buttons, one per (label, url) pair, in the order given.

    Link buttons open the URL in Discord itself and never call back to the bot, so the view has no
    timeout and the buttons keep working after a restart. Must be built inside a running event loop.
    :param links: (label, url) pairs
    :return: The view to send with the reply
    """
    view = discord.ui.View(timeout=None)
    for label, url in links:
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=label, url=url))
    return view


USER_INSTALL_LINK = (messages.USER_INSTALL_BUTTON, messages.USER_INSTALL_URL)


def build_invite_view() -> discord.ui.View:
    return build_link_buttons(INVITE_LINK, USER_INSTALL_LINK, SUPPORT_SERVER_LINK)


def build_vote_view() -> discord.ui.View:
    return build_link_buttons(VOTE_LINK)


def build_help_view() -> discord.ui.View:
    return build_link_buttons(INVITE_LINK, VOTE_LINK, SUPPORT_SERVER_LINK)


def build_server_wrapped_view() -> discord.ui.View:
    # Wrapped week is when the most members see the bot at once, so the post asks for an install and a vote
    return build_link_buttons(INVITE_LINK, VOTE_LINK)


CHECK_SETUP_CUSTOM_ID = "hof:check_setup"
# Set by main at startup to the coroutine that answers a press of Troubleshoot
setup_check_handler = None


class SetupCheckView(discord.ui.View):
    """
    The Troubleshoot button, then the given links, under the welcome message and /get_server_config.

    The welcome message stays in the board for good, so the button has a fixed custom_id and main
    registers this view with bot.add_view on startup. That keeps it working after a restart, where a
    plain view would answer "This interaction failed". Link buttons need no callback, so they can sit
    in a persistent view as they are.
    """

    def __init__(self, *links: tuple[str, str]):
        super().__init__(timeout=None)
        button = discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.TROUBLESHOOT_BUTTON,
                                   custom_id=CHECK_SETUP_CUSTOM_ID)
        button.callback = self.check_setup
        self.add_item(button)
        for label, url in links:
            self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=label, url=url))

    @staticmethod
    async def check_setup(interaction: discord.Interaction):
        if setup_check_handler is not None:
            await setup_check_handler(interaction)


def build_check_setup_view() -> discord.ui.View:
    # The same button as on the welcome message, so the view main registers answers it too
    return SetupCheckView()


def build_welcome_view() -> discord.ui.View:
    # The server has just installed the bot, so there is nothing to invite it to yet
    return SetupCheckView(SUPPORT_SERVER_LINK, VOTE_LINK)


def build_help_embed() -> discord.Embed:
    """
    The card /help answers with: every command, grouped by who uses it and what it changes.

    One field per group rather than one per command, so the whole list fits on a screen and a member
    looking for the leaderboard does not have to scroll past a dozen settings to find it. The groups
    follow the ones /get_server_config shows, so a setting is found under the same heading in both.
    :return: The embed to send
    """
    embed = discord.Embed(
        title="📖 Hall of Fame Commands",
        description=f"React to a message, and once it passes the threshold it is reposted to the hall "
                    f"of fame channel. To get started, pick a channel with "
                    f"{command_refs.SET_HALL_OF_FAME_CHANNEL} and a threshold with "
                    f"{command_refs.SET_REACTION_THRESHOLD}.",
        color=discord.Color.gold()
    )

    embed.add_field(
        name="🏆 For everyone",
        value=f"{command_refs.LEADERBOARD} the server's top members\n"
              f"{command_refs.USER_PROFILE} a member's standing, with totals across every server\n"
              f"{command_refs.HOF_WRAPPED} your year in review\n"
              f"{command_refs.SERVER_HOF_WRAPPED} the server's year in review\n"
              f"**{messages.WHY_MENU_NAME}** right-click or long-press a message, then Apps",
        inline=False)

    embed.add_field(
        name="🔒 Your data",
        value=f"{command_refs.MY_DATA} see, download or delete what is stored about you, and hide your "
              f"totals across servers",
        inline=False)

    embed.add_field(
        name="⚙️ Board · Manage Server",
        value=f"{command_refs.SET_HALL_OF_FAME_CHANNEL} the channel posts go to\n"
              f"{command_refs.SET_REACTION_THRESHOLD} reactions needed\n"
              f"{command_refs.CALCULATION_METHOD} how reactions are counted\n"
              f"{command_refs.GET_SERVER_CONFIG} every current setting\n"
              f"{command_refs.TROUBLESHOOT} health check: find what stops posts, and how to fix it",
        inline=False)

    embed.add_field(
        name="🎯 What qualifies · Manage Server",
        value=f"{command_refs.SET_POST_DUE_DATE} how old a post can be\n"
              f"{command_refs.INCLUDE_AUTHORS_REACTION} count the author's own reaction\n"
              f"{command_refs.IGNORE_BOT_MESSAGES} skip messages from bots\n"
              f"{command_refs.REQUIRE_IMAGE_OR_VIDEO} only posts with an image or video",
        inline=False)

    embed.add_field(
        name="📋 Board behaviour · Manage Server",
        value=f"{command_refs.ALLOW_MESSAGES_IN_HOF_CHANNEL} let members chat in the board channel\n"
              f"{command_refs.HIDE_HOF_POST_BELOW_THRESHOLD} hide posts that drop below the threshold\n"
              f"{command_refs.COUNT_IN_GLOBAL_PROFILES} count posts here toward totals across servers",
        inline=False)

    embed.add_field(
        name="😀 Emoji whitelist · Manage Server",
        value=f"{command_refs.CUSTOM_EMOJI_CHECK_LOGIC} count every emoji or only whitelisted ones\n"
              f"{command_refs.WHITELIST_EMOJI} · {command_refs.UNWHITELIST_EMOJI} · "
              f"{command_refs.CLEAR_WHITELIST}",
        inline=False)

    embed.add_field(
        name="🔗 Links",
        value=f"[Support server]({messages.SUPPORT_SERVER_URL}) · "
              f"[Add to a server]({messages.INVITE_URL}) · "
              f"[Add to your account]({messages.USER_INSTALL_URL}) · "
              f"[Vote]({messages.VOTE_URL}) · "
              f"[Source]({messages.SOURCE_URL})\n"
              f"Found a bug or have an idea? {command_refs.FEEDBACK}\n"
              f"Not working? Run {command_refs.TROUBLESHOOT}.",
        inline=False)

    embed.set_footer(text=f"Hall of Fame {version.VERSION} · {version.DATE}")
    return embed


async def get_help(interaction: discord.Interaction):
    """
    Command to get a list of commands
    :param interaction:
    :return:
    """
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(embed=build_help_embed(), view=build_help_view())


async def set_reaction_threshold(interaction: discord.Interaction, reaction_threshold: int, connection,
                                 method_label: str, server_config):
    """
    Command to set the reaction threshold for posting a message in the Hall of Fame
    :param interaction:
    :param reaction_threshold:
    :param connection:
    :param method_label: How the server counts reactions, so the reply says what the number means
    :param server_config: The server's cached configuration, updated along with the database
    :return:
    """
    server_config_repo.update_server_config_param(interaction.guild.id, 'reaction_threshold', reaction_threshold, connection)
    # Updated before the reply is awaited, so a reaction handled meanwhile, or a reply that fails, does
    # not leave the cache on the old threshold while the database already holds the new one
    server_config.reaction_threshold = reaction_threshold
    # noinspection PyUnresolvedReferences
    await interaction.response.send_message(
        messages.SETTING_CHANGED.format(label="Reaction threshold", value=reaction_threshold) + "\n"
        + messages.REACTION_THRESHOLD_NOTE.format(threshold=reaction_threshold,
                                                  plural="" if reaction_threshold == 1 else "s",
                                                  method=method_label)
        + f" Change how reactions are counted with {command_refs.CALCULATION_METHOD}.")


async def user_server_profile(interaction, user, user_stats, connection, month_emoji: str, all_time_emoji: str,
                              global_profile: dict = None):
    """
    Command to get the Hall of Fame profile for a user in a specific server
    :param interaction:
    :param user:
    :param user_stats:
    :param connection:
    :param month_emoji:
    :param all_time_emoji:
    :param global_profile: The member's totals across every server, or None when hidden or not wanted
    :return: None. The command was deferred, so the card goes out as its followup
    """
    user_has_most_this_month_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "this_month_hall_of_fame_messages")
    user_with_most_all_time_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "total_hall_of_fame_messages")

    show_global = global_profile_adds_something(global_profile)
    embed = discord.Embed(
        title=f"📊 {user.name}'s Hall of Fame Profile",
        description=f"Stats for **{interaction.guild.name}**"
                    + (" and every server with Hall of Fame." if show_global else "."),
        color=discord.Color.gold()
    )
    if user_has_most_this_month_hall_of_fame_messages and user_stats:
        embed.add_field(name=f"{month_emoji} **Monthly Hall of Fame Champion**",
                        value=f"**{user.name}** is the champion of this month's Hall of Fame with **{user_stats.get('this_month_hall_of_fame_messages', 0)}** messages!",
                        inline=False)
    if user_with_most_all_time_hall_of_fame_messages and user_stats:
        embed.add_field(name=f"{all_time_emoji} **All-Time Hall of Fame Champion**",
                        value=f"**{user.name}** is the all-time champion with **{user_stats.get('total_hall_of_fame_messages', 0)}** messages!",
                        inline=False)

    # Side by side columns: this month and all time in this server, then every server. Inline fields
    # sit next to each other on desktop and stack on a phone
    stats = user_stats or {}
    embed.add_field(name="🏆 This month", inline=True, value=_stat_column(
        stats.get("this_month_hall_of_fame_messages", 0), stats.get("monthly_message_rank"),
        stats.get("this_month_hall_of_fame_message_reactions", 0), stats.get("monthly_reaction_rank")))
    embed.add_field(name="🌟 All time", inline=True, value=_stat_column(
        stats.get("total_hall_of_fame_messages", 0), stats.get("total_message_rank"),
        stats.get("total_hall_of_fame_message_reactions", 0), stats.get("total_reaction_rank")))
    if show_global:
        embed.add_field(name=messages.GLOBAL_PROFILE_HEADING, inline=True,
                        value=global_profile_column_value(global_profile))

    badges = earned_badges(hall_of_fame_message_repo.get_member_badge_facts(connection, interaction.guild.id, user.id),
                           global_profile)
    if badges:
        embed.add_field(name=messages.BADGES_HEADING, value=" · ".join(badges), inline=False)

    if user_stats:
        highlights = hall_of_fame_message_repo.get_member_highlights(connection, interaction.guild.id, user.id)
        gap = rank_gap_line(user_stats, lambda stat, rank_field, rank: server_user_repo.get_stat_at_rank(
            connection, interaction.guild.id, stat, rank_field, rank))
        value = highlights_value(interaction.guild.id, highlights, gap)
        if value:
            embed.add_field(name=messages.HIGHLIGHTS_HEADING, value=value, inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=messages.GLOBAL_STATS_FOOTER if show_global else messages.STATS_FOOTER)
    await interaction.followup.send(embed=embed)


def build_global_profile_embed(user, global_profile: dict) -> discord.Embed:
    """
    /user_profile used through a user install, in a DM or a server without Hall of Fame: the totals
    across servers of the member who asked, alone, as there is no server here to show standings, highlights or ranks for.

    Built from the same totals as the every-server column, so like it nothing on the card can name or
    point to a server. Only the badges that come from those totals can be earned here.
    :param user: The member who asked, the only one who can be looked up there
    :param global_profile: Their totals from global_profile_repo.get_global_profile, never hidden ones
    :return: The embed to send
    """
    embed = discord.Embed(
        title=f"📊 {user.name}'s Hall of Fame Profile",
        description=messages.PROFILE_EVERY_SERVER_DESCRIPTION.format(command=command_refs.USER_PROFILE),
        color=discord.Color.gold()
    )
    embed.add_field(name=messages.GLOBAL_PROFILE_HEADING, inline=True,
                    value=global_profile_column_value(global_profile))
    badges = earned_badges({}, global_profile)
    if badges:
        embed.add_field(name=messages.BADGES_HEADING, value=" · ".join(badges), inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=messages.GLOBAL_STATS_FOOTER)
    return embed


# Each badge shows only its highest tier reached, so the field stays one short line
POST_BADGE_TIERS = (500, 100, 50, 10)
STREAK_BADGE_MONTHS = 3
BIG_POST_REACTIONS = 100
BIG_MONTH_POSTS = 10
SERVERS_BADGE_MINIMUM = 5


def _longest_month_streak(posts_by_month) -> int:
    """The most calendar months in a row with at least one post, from (month start, posts) pairs"""
    longest = run = 0
    previous = None
    for month, _posts_in_month in posts_by_month:
        index = month.year * 12 + month.month
        run = run + 1 if previous is not None and index == previous + 1 else 1
        longest = max(longest, run)
        previous = index
    return longest


def earned_badges(facts: dict, global_profile: dict | None, now: datetime.datetime | None = None) -> list[str]:
    """
    The badges a member has earned, worked out from existing posts and totals, in the order shown.

    Most come from this server alone. The reaction and month badges also count other servers when the
    member's totals across servers are shown, and the servers badge only exists then. A member who hid
    those totals gets global_profile None, so nothing from another server reaches the card. A badge
    about other servers gives a count, never a name or a link.
    :param facts: From hall_of_fame_message_repo.get_member_badge_facts for this server
    :param global_profile: The totals from global_profile_repo.get_global_profile, or None when hidden
    :param now: The current time, taken from the clock when not supplied
    :return: The badge labels, empty when the member has earned none
    """
    now = now or datetime.datetime.now(timezone.utc)
    posts_by_month = facts.get("posts_by_month") or []
    posts_here = sum(posts for _month, posts in posts_by_month)
    everywhere = global_profile or {}

    badges = []
    if facts.get("champion_months"):
        badges.append(messages.BADGE_MONTHLY_CHAMPION)
    tier = next((tier for tier in POST_BADGE_TIERS if posts_here >= tier), None)
    if tier:
        badges.append(messages.BADGE_POSTS.format(posts=tier))
    streak = _longest_month_streak(posts_by_month)
    if streak >= STREAK_BADGE_MONTHS:
        badges.append(messages.BADGE_STREAK.format(months=streak))
    first = facts.get("first_featured")
    if first is not None:
        # Stored as naive UTC
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        if now - first >= datetime.timedelta(days=365):
            badges.append(messages.BADGE_VETERAN)
    if max(facts.get("biggest_post") or 0, everywhere.get("biggest_post", 0)) >= BIG_POST_REACTIONS:
        badges.append(messages.BADGE_BIG_POST)
    best_month_here = max((posts for _month, posts in posts_by_month), default=0)
    if max(best_month_here, everywhere.get("best_month", 0)) >= BIG_MONTH_POSTS:
        badges.append(messages.BADGE_BIG_MONTH)
    if everywhere.get("servers", 0) >= SERVERS_BADGE_MINIMUM:
        badges.append(messages.BADGE_SERVERS.format(servers=everywhere["servers"]))
    return badges


def _posts(count: int) -> str:
    return f"{count} post{'' if count == 1 else 's'}"


# The periods the gap to the next place is worked out for, in order of preference: this month is the
# race a member can still change, so it is used whenever they have a rank in it
RANK_GAP_PERIODS = (
    ("this month", "this_month_hall_of_fame_messages", "monthly_message_rank"),
    ("all time", "total_hall_of_fame_messages", "total_message_rank"),
)


def rank_gap_line(user_stats: dict, stat_at_rank) -> str | None:
    """
    How far a member is from the next place up, or how far ahead they are when first
    :param user_stats: The member's row in this server
    :param stat_at_rank: Looks up the count held at a rank: (stat_field, rank_field, rank) -> count or None
    :return: The line for the highlights, or None when there is nothing to compare with
    """
    for period, stat_field, rank_field in RANK_GAP_PERIODS:
        rank = user_stats.get(rank_field)
        if not rank:
            continue
        mine = user_stats.get(stat_field) or 0
        if rank > 1:
            ahead = stat_at_rank(stat_field, rank_field, rank - 1)
            if ahead is None:
                return None
            gap = ahead - mine
            if gap <= 0:
                return messages.HIGHLIGHT_LEVEL_WITH.format(rank=rank - 1, period=period)
            return messages.HIGHLIGHT_BEHIND.format(posts=_posts(gap), rank=rank - 1, period=period)
        behind = stat_at_rank(stat_field, rank_field, 2)
        if behind is None:
            return None
        lead = mine - behind
        if lead <= 0:
            return messages.HIGHLIGHT_SHARING_FIRST.format(period=period)
        return messages.HIGHLIGHT_LEADING.format(posts=_posts(lead), period=period)
    return None


def highlights_value(guild_id: int, highlights: dict, gap_line: str | None) -> str:
    """
    The highlights under the profile columns: best post with a link to it, when the member was last
    featured, and the gap to the next place. A line is left out when there is nothing for it
    :param guild_id: The guild, for the jump link
    :param highlights: From hall_of_fame_message_repo.get_member_highlights
    :param gap_line: From rank_gap_line
    :return: The field value, empty when every line was left out
    """
    lines = []
    best = highlights.get("best_post")
    if best:
        reactions = best["reaction_count"]
        url = f"https://discord.com/channels/{guild_id}/{best['channel_id']}/{best['message_id']}"
        lines.append(messages.HIGHLIGHT_BEST_POST.format(
            reactions=f"{reactions} reaction{'' if reactions == 1 else 's'}", url=url))
    last = highlights.get("last_featured")
    if last:
        # Stored as naive UTC. A Discord timestamp shows it relative and in the reader's own time zone
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        lines.append(messages.HIGHLIGHT_LAST_FEATURED.format(timestamp=f"<t:{int(last.timestamp())}:R>"))
    if gap_line:
        lines.append(gap_line)
    return "\n".join(lines)


def _stat_column(posts: int, posts_rank, reactions: int, reactions_rank) -> str:
    """
    One column of the profile card: posts and reactions, each with the member's rank in the server.
    A member with nothing featured in the period is stored without a rank, shown as a dash
    """
    def ranked(count: int, label: str, rank) -> str:
        return f"**{count or 0:,}** {label} · {f'#{rank}' if rank else '-'}"

    return f"{ranked(posts, 'posts', posts_rank)}\n{ranked(reactions, 'reactions', reactions_rank)}"


def global_profile_adds_something(global_profile: dict) -> bool:
    """
    Whether the totals across servers say more than the server profile above them: only when the
    member has counted posts in another server. With every counted post from this server, the section
    would only repeat the card
    :param global_profile: The totals from global_profile_repo.get_global_profile, read with this
        server's ID so other_servers leaves it out, or None when hidden
    """
    return bool(global_profile and global_profile["posts"] and global_profile["other_servers"])


def global_profile_column_value(profile: dict) -> str:
    """
    The every-server column of /user_profile: a member's totals across every server.

    Built from totals alone, so nothing in it can name or point to another server. That is what
    makes it safe to show in any server, and it must stay that way: no per-server rows, ranks or links.
    :param profile: The totals from global_profile_repo.get_global_profile
    :return: The field value
    """
    servers = profile["servers"]
    top_of_board = profile["top_of_board"]
    servers_line = f"**{servers}** server{'' if servers == 1 else 's'}"
    if top_of_board:
        servers_line += f" · #1 in {top_of_board}"
    return f"**{profile['posts']:,}** posts\n**{profile['reactions']:,}** reactions\n{servers_line}"


# The sections of the export that hold rows, and so can be split across files
EXPORT_SECTIONS = ("featured_posts", "server_statistics", "wrapped")
# The most the export puts in one Discord message once it has to be split. The whole file is always tried
# first, so Discord's own limit decides, which is higher in boosted servers. Only when Discord refuses it
# for its size is it split, into parts within this. Discord allows 10 MiB per upload without boosts, and
# has changed that before, so this leaves room. It is kept for all the files of a message together, which
# is safe whether Discord counts the limit per file or per message
EXPORT_MESSAGE_BYTES = 8 * 1024 * 1024
# Discord's error code for an upload over its size limit, sent with HTTP status 413
DISCORD_FILE_TOO_LARGE_CODE = 40005
# Discord allows 10 attachments per message
EXPORT_FILES_PER_MESSAGE = 10
# Followups only work for 15 minutes after the button press, and a member should not get a flood of
# messages. Past this, the export goes through the support server instead
EXPORT_MAX_MESSAGES = 10
# Discord allows only 5 followups per interaction when the bot is reached through a user install where it
# is not installed: a DM, or a server without Hall of Fame. One goes to the whole file tried first and one
# is kept for saying that sending failed, which leaves 3 for the parts
EXPORT_MAX_MESSAGES_USER_INSTALL = 3


def export_max_messages(interaction: discord.Interaction) -> int:
    """How many messages a split export may take on this button press"""
    return EXPORT_MAX_MESSAGES if interaction.is_guild_integration() else EXPORT_MAX_MESSAGES_USER_INSTALL


class ExportTooLarge(Exception):
    """The export cannot be sent through Discord, even split up"""


def is_file_too_large(error: discord.HTTPException) -> bool:
    """Whether Discord refused an upload for its size, rather than for an outage or anything else"""
    return error.status == 413 or getattr(error, "code", 0) == DISCORD_FILE_TOO_LARGE_CODE


def split_budget(refused_bytes: int) -> int:
    """
    How big each part may be once Discord refused the whole file: half of what it refused, so its limit
    is under the parts even when it is far below what was expected, and never more than EXPORT_MESSAGE_BYTES
    """
    return min(EXPORT_MESSAGE_BYTES, refused_bytes // 2)


def build_my_data_document(user_id: int, posts: list, standings: list, wrapped: list, profile_hidden: bool,
                           not_counted: bool = False) -> dict:
    """
    Every row stored about a member, ready to be written as JSON.

    Only ever sent privately to the member it describes, so unlike the totals on a profile it does include
    the server and message IDs, which are the member's own data.
    :param user_id: The member's user ID
    :param posts: Their featured posts, from hall_of_fame_message
    :param standings: Their per-server statistics, from server_user
    :param wrapped: Their Wrapped rows, from hof_wrapped
    :param profile_hidden: Whether they hid their totals across servers
    :param not_counted: Whether they asked not to be featured from now on
    :return: The document
    """
    export = {
        "user_id": str(user_id),
        "about": "Everything Hall of Fame stores about you. IDs are strings so no digits are lost. "
                 "Message text, images and usernames are not stored. Privacy policy: "
                 + messages.PRIVACY_POLICY_URL,
        "global_profile_hidden": profile_hidden,
        "not_counted": not_counted,
        "featured_posts": posts,
        "server_statistics": standings,
        "wrapped": wrapped,
    }

    def stringify_ids(rows):
        return [{key: str(value) if key.endswith("_id") and value is not None else value
                 for key, value in row.items()} for row in rows]

    for key in EXPORT_SECTIONS:
        export[key] = stringify_ids(export[key])
    return export


def encode_export(document: dict) -> bytes:
    # Datetimes, and anything else JSON has no type for, are written as text
    return json.dumps(document, indent=2, default=str, ensure_ascii=False).encode("utf-8")


def build_my_data_export(user_id: int, posts: list, standings: list, wrapped: list, profile_hidden: bool,
                         not_counted: bool = False) -> bytes:
    """The export as one file, the way it is sent whenever it fits"""
    return encode_export(build_my_data_document(user_id, posts, standings, wrapped, profile_hidden, not_counted))


def split_my_data_export(document: dict, max_bytes: int = None) -> list[bytes]:
    """
    The export as files no bigger than max_bytes. One file whenever it fits. Otherwise the rows are
    spread over parts that are each a complete JSON file with the same header and a slice of every
    section, so each part can be read on its own and together they hold every row exactly once.
    :param document: From build_my_data_document
    :param max_bytes: The most a single file may hold, EXPORT_MESSAGE_BYTES when not given
    :return: The files, in order
    :raises ExportTooLarge: When a single row is bigger than a file may be
    """
    max_bytes = max_bytes or EXPORT_MESSAGE_BYTES
    whole = encode_export(document)
    if len(whole) <= max_bytes:
        return [whole]

    header = {key: value for key, value in document.items() if key not in EXPORT_SECTIONS}
    # Room for the header and the part label, measured on an empty part with the longest label it can get
    empty = encode_export(dict(header, part="99999 of 99999", **{section: [] for section in EXPORT_SECTIONS}))
    budget = max_bytes - len(empty)

    def row_size(row):
        # Inside the file a row sits two levels deep, which indents each of its lines by four more spaces,
        # and it is followed by a comma and a line break
        encoded = encode_export(row)
        return len(encoded) + 4 * (encoded.count(b"\n") + 1) + 2

    slices = []
    current = {section: [] for section in EXPORT_SECTIONS}
    used = 0
    for section in EXPORT_SECTIONS:
        for row in document[section]:
            size = row_size(row)
            if size > budget:
                raise ExportTooLarge(f"one {section} row is {size} bytes")
            if used + size > budget:
                slices.append(current)
                current = {name: [] for name in EXPORT_SECTIONS}
                used = 0
            current[section].append(row)
            used += size
    slices.append(current)

    parts = []
    for number, rows in enumerate(slices, start=1):
        part = dict(header, part=f"{number} of {len(slices)}", **rows)
        encoded = encode_export(part)
        # The sizes above are worked out rather than measured, so each part is checked before it is sent
        if len(encoded) > max_bytes:
            raise ExportTooLarge(f"part {number} came out at {len(encoded)} bytes")
        parts.append(encoded)
    return parts


def batch_export_files(files: list[bytes], max_bytes: int = None, per_message: int = None) -> list[list[int]]:
    """
    Group the export's files into messages, each within Discord's attachment count and the size budget
    :param files: The files, each no bigger than max_bytes
    :param max_bytes: The most the files of one message may hold together, EXPORT_MESSAGE_BYTES when not given
    :param per_message: The most files one message may carry, EXPORT_FILES_PER_MESSAGE when not given
    :return: The indexes of the files in each message, in order
    """
    max_bytes = max_bytes or EXPORT_MESSAGE_BYTES
    per_message = per_message or EXPORT_FILES_PER_MESSAGE
    batches = []
    current, used = [], 0
    for index, data in enumerate(files):
        if current and (len(current) == per_message or used + len(data) > max_bytes):
            batches.append(current)
            current, used = [], 0
        current.append(index)
        used += len(data)
    if current:
        batches.append(current)
    return batches


class ConfirmDeleteView(discord.ui.View):
    """
    The confirm and cancel buttons /my_data shows after Delete my data. Deleting cannot be undone, so
    it only happens on a deliberate second click, and only the member who asked can make it. Whether
    to stop featuring the member is asked afterwards, by StopFeaturingView
    """

    def __init__(self, owner_id: int, on_confirm, timeout_seconds: float = 120):
        """
        :param owner_id: The member whose data would be deleted
        :param on_confirm: Coroutine function taking the button's interaction, which deletes and answers
        :param timeout_seconds: How long the buttons stay usable
        """
        super().__init__(timeout=timeout_seconds)
        self.owner_id = owner_id
        self.on_confirm = on_confirm
        self.original_interaction = None
        self.finished = False

        confirm = discord.ui.Button(style=discord.ButtonStyle.danger, label=messages.DELETE_MY_DATA_BUTTON)
        cancel = discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.CANCEL_BUTTON)
        confirm.callback = self.confirm
        cancel.callback = self.cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # The prompt is ephemeral, so nobody else should see it, but a click is checked all the same
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(messages.MY_DATA_NOT_YOURS, ephemeral=True)
            return False
        return True

    async def confirm(self, interaction: discord.Interaction):
        self.finished = True
        self.stop()
        await self.on_confirm(interaction)

    async def cancel(self, interaction: discord.Interaction):
        self.finished = True
        self.stop()
        await interaction.response.edit_message(content=messages.DELETE_MY_DATA_CANCELLED, view=None)

    async def on_timeout(self):
        if self.finished or self.original_interaction is None:
            return
        try:
            await self.original_interaction.edit_original_response(
                content=messages.DELETE_MY_DATA_EXPIRED.format(command=command_refs.MY_DATA), view=None)
        except discord.HTTPException:
            # The member dismissed the prompt, so there is nothing left to update
            pass


class StopFeaturingView(discord.ui.View):
    """
    The button under the message a deletion ends with, offering to stop featuring the member from now
    on: the same setting as on /my_data, offered where a member who just deleted their data is likeliest
    to want it, with what it keeps explained right above the button
    """

    def __init__(self, owner_id: int, on_stop, timeout_seconds: float = 120):
        """
        :param owner_id: The member who deleted their data
        :param on_stop: Coroutine function taking the button's interaction, which opts out and answers
        :param timeout_seconds: How long the button stays usable
        """
        super().__init__(timeout=timeout_seconds)
        self.owner_id = owner_id
        self.on_stop = on_stop
        self.original_interaction = None
        self.finished = False
        button = discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.STOP_FEATURING_BUTTON)
        button.callback = self.stop_featuring
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(messages.MY_DATA_NOT_YOURS, ephemeral=True)
            return False
        return True

    async def stop_featuring(self, interaction: discord.Interaction):
        self.finished = True
        self.stop()
        await self.on_stop(interaction)

    async def on_timeout(self):
        if self.finished or self.original_interaction is None:
            return
        try:
            # The deletion stands; only the offer goes, and /my_data makes it again after another deletion
            await self.original_interaction.edit_original_response(view=None)
        except discord.HTTPException:
            pass


def has_stored_rows(summary: dict) -> bool:
    """Whether posts, standings or Wrapped entries are stored about a member, leaving out their two choices"""
    return bool(summary["posts"] or summary["servers"] or summary["wrapped"])


def has_anything_stored(summary: dict) -> bool:
    """Whether anything at all is stored about a member, their choice to hide totals or not be featured included"""
    return bool(has_stored_rows(summary) or summary["hidden_since"] or summary["opted_out_since"])


def has_totals(summary: dict) -> bool:
    """
    Whether a member has totals across servers to show or hide: posts credited to them, or the chance
    of some, since they are featured. Not featuring a member leaves the posts they already have
    """
    return bool(summary["posts"] or not summary["opted_out_since"])


def discord_date(moment) -> str:
    """A date Discord shows in each reader's own language and time zone"""
    return f"<t:{int(moment.timestamp())}:D>"


def my_data_summary(summary: dict, note: str = None) -> str:
    """
    The private message /my_data answers with: what is stored, and the member's two choices
    :param summary: posts, servers and wrapped counts, and when the totals were hidden and the member
        asked not to be featured, None for either they did not do
    :param note: A line to lead with, such as the result of a button just pressed
    :return: The message
    """
    lines = [note] if note else []
    if has_stored_rows(summary):
        lines.append(messages.MY_DATA_STORED.format(
            posts=f"{summary['posts']:,}", posts_plural="" if summary["posts"] == 1 else "s",
            servers=f"{summary['servers']:,}", servers_plural="" if summary["servers"] == 1 else "s",
            wrapped=f"{summary['wrapped']:,}", wrapped_plural="y" if summary["wrapped"] == 1 else "ies"))
    elif summary["hidden_since"] or summary["opted_out_since"]:
        lines.append(messages.MY_DATA_NOTHING_STORED)
    else:
        lines.append(messages.MY_DATA_NOTHING_AT_ALL)
    if has_totals(summary):
        if summary["hidden_since"]:
            lines.append(messages.MY_DATA_TOTALS_HIDDEN.format(since=discord_date(summary["hidden_since"])))
        else:
            # The totals are added up from the posts credited to the member, so without any there are none yet
            lines.append(messages.MY_DATA_TOTALS_SHOWN if summary["posts"]
                         else messages.MY_DATA_TOTALS_SHOWN_ONCE_FEATURED)
    if summary["opted_out_since"]:
        not_featured = messages.MY_DATA_NOT_FEATURED.format(since=discord_date(summary["opted_out_since"]))
        # Not featuring a member only concerns new messages, so anything from before is still there
        if has_stored_rows(summary):
            not_featured += " " + messages.MY_DATA_EARLIER_KEPT
        lines.append(not_featured)
    lines.append(messages.MY_DATA_FOOTER)
    return "\n".join(lines)


class MyDataView(discord.ui.View):
    """
    The buttons under /my_data, the one place a member manages what the bot stores about them: two
    settings, hiding their totals across servers and not being featured, and two actions, downloading
    and deleting their data. Only the member who ran the command can use them
    """

    def __init__(self, owner_id: int, summary: dict, on_download, on_toggle_totals, on_toggle_featuring,
                 on_delete, timeout_seconds: float = 120):
        """
        :param owner_id: The member the data belongs to
        :param summary: What is stored, as my_data_summary takes it. The buttons follow it
        :param on_download, on_toggle_totals, on_toggle_featuring, on_delete: Coroutine functions taking
            the button's interaction and this view, which act and answer
        :param timeout_seconds: How long the buttons stay usable
        """
        super().__init__(timeout=timeout_seconds)
        self.owner_id = owner_id
        self.summary = summary
        self.original_interaction = None
        self.finished = False

        self.download_button = discord.ui.Button(style=discord.ButtonStyle.primary,
                                                 label=messages.MY_DATA_DOWNLOAD_BUTTON)
        self.totals_button = discord.ui.Button(style=discord.ButtonStyle.secondary)
        self.featuring_button = discord.ui.Button(style=discord.ButtonStyle.secondary)
        self.delete_button = discord.ui.Button(style=discord.ButtonStyle.danger, label=messages.DELETE_MY_DATA_BUTTON)
        for button, handler in ((self.download_button, on_download), (self.totals_button, on_toggle_totals),
                                (self.featuring_button, on_toggle_featuring), (self.delete_button, on_delete)):
            button.callback = self._calling(handler)
        self.refresh()

    def _calling(self, handler):
        async def callback(interaction: discord.Interaction):
            await handler(interaction, self)
        return callback

    def refresh(self):
        """Lay the buttons out for the current summary"""
        self.clear_items()
        self.totals_button.label = (messages.SHOW_TOTALS_BUTTON if self.summary["hidden_since"]
                                    else messages.HIDE_TOTALS_BUTTON)
        self.featuring_button.label = (messages.FEATURE_ME_AGAIN_BUTTON if self.summary["opted_out_since"]
                                       else messages.STOP_FEATURING_BUTTON)
        # Download and Delete are always shown, so the panel looks the same for everyone, and greyed out
        # when nothing at all is stored. A choice is data about the member too, so a member whose only
        # stored data is the choice not to be featured can still download and delete it
        self.download_button.disabled = not has_anything_stored(self.summary)
        self.add_item(self.download_button)
        # Hiding totals a member cannot have would store a choice about them for nothing
        if has_totals(self.summary):
            self.add_item(self.totals_button)
        self.add_item(self.featuring_button)
        # Deleting removes everything stored, the member's two choices included
        self.delete_button.disabled = not has_anything_stored(self.summary)
        self.add_item(self.delete_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # The message is ephemeral, so nobody else should see it, but a click is checked all the same
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(messages.MY_DATA_NOT_YOURS, ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.finished or self.original_interaction is None:
            return
        try:
            await self.original_interaction.edit_original_response(view=None)
        except discord.HTTPException:
            # The member dismissed the message, so there is nothing left to update
            pass


async def server_leaderboard(interaction, connection, month_emoji: str, all_time_emoji: str):
    """
    Command to get the Hall of Fame leaderboard for a server
    :param interaction:
    :param connection:
    :param month_emoji:
    :param all_time_emoji:
    :return:
    """
    # Defer the interaction response to prevent timeout
    await interaction.response.defer()

    embed = discord.Embed(
        title=f"📊 {interaction.guild.name} Hall of Fame Leaderboard",
        description="Here are the top users in this server:",
        color=discord.Color.blue()
    )

    # Consolidated Leaderboard
    leaderboard = ""

    # Top 5 This Month's Hall of Fame Messages
    top_monthly = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "this_month_hall_of_fame_messages", limit=5)
    leaderboard += f"{month_emoji} **Top 5 This Month's Hall of Fame Messages**\n"
    for rank, user in enumerate(top_monthly, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_messages', 0)} messages\n"

    # Top 5 All-Time Hall of Fame Messages
    top_all_time = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "total_hall_of_fame_messages", limit=5)
    leaderboard += f"\n{all_time_emoji} **Top 5 All-Time Hall of Fame Messages**\n"
    for rank, user in enumerate(top_all_time, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_messages', 0)} messages\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_messages', 0)} messages\n"

    # Top 5 This Month's Reactions
    top_monthly_reactions = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "this_month_hall_of_fame_message_reactions", limit=5)
    leaderboard += f"\n💬 **Top 5 This Month's Reactions**\n"
    for rank, user in enumerate(top_monthly_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('this_month_hall_of_fame_message_reactions', 0)} reactions\n"

    # Top 5 All-Time Reactions
    top_all_time_reactions = server_user_repo.get_top_users_by_stat(connection, interaction.guild_id, "total_hall_of_fame_message_reactions", limit=5)
    leaderboard += f"\n💬 **Top 5 All-Time Reactions**\n"
    for rank, user in enumerate(top_all_time_reactions, start=1):
        try:
            member = await interaction.guild.fetch_member(int(user["user_id"]))
            leaderboard += f"{rank}. {member.name}: {user.get('total_hall_of_fame_message_reactions', 0)} reactions\n"
        except discord.NotFound:
            leaderboard += f"{rank}. Unknown Member: {user.get('total_hall_of_fame_message_reactions', 0)} reactions\n"

    embed.add_field(name="Leaderboard", value=leaderboard, inline=False)
    embed.set_footer(text=messages.STATS_FOOTER)
    await interaction.followup.send(embed=embed)


# A ping is answered at most once per channel in this window, so that it cannot be used to make the
# bot flood a channel
mention_cooldown_seconds = 30
recently_answered_mentions = ExpiringSet(ttl_seconds=mention_cooldown_seconds)


def is_bot_mention(message: discord.Message, bot_user) -> bool:
    """
    Decide whether a message is somebody pinging the bot to ask what it is.

    Deliberately narrow. A role ping or an @everyone is not addressed to the bot, a reply carries a
    mention of the author it is replying to, and a message that mentions the bot in passing is a
    conversation rather than a question. Answering any of those turns the bot into a nuisance.
    :param message: The message that was sent
    :param bot_user: The bot's own user
    :return: True when the message is a bare mention of the bot
    """
    if bot_user is None or message.author.bot:
        return False
    if not any(user.id == bot_user.id for user in message.mentions):
        return False
    if message.reference is not None:
        return False

    remaining = message.content
    for mention in (f"<@{bot_user.id}>", f"<@!{bot_user.id}>"):
        remaining = remaining.replace(mention, "")
    return remaining.strip() == ""


def build_bot_info_embed(guild, bot_user, server_config) -> discord.Embed:
    """
    The card the bot answers a ping with: what it is, how this server has it set up, and where to go
    :param guild: The server the ping came from
    :param bot_user: The bot's own user, for the thumbnail
    :param server_config: The server's configuration, or None when it has not been set up
    :return: The embed to send
    """
    embed = discord.Embed(
        title="🏆 Hall of Fame",
        description="Your server's best moments, and the members behind them. React to a message, "
                    "and once it passes the threshold it is reposted to the hall of fame channel "
                    "and credited to whoever posted it.\n\n"
                    "Landing there is meant to be worth something, so the bot keeps score: "
                    "leaderboards, member profiles and a yearly wrapped.",
        color=discord.Color.gold()
    )

    if server_config is not None:
        method = str(server_config.reaction_count_calculation_method).replace("_", " ")
        embed.add_field(
            name="Set up in this server",
            value=f"Board: <#{server_config.hall_of_fame_channel_id}>\n"
                  f"Reactions needed: **{server_config.reaction_threshold}**\n"
                  f"Counting: {method}\n"
                  f"Full configuration with {command_refs.GET_SERVER_CONFIG}",
            inline=False)
    else:
        embed.add_field(
            name="Not set up in this server yet",
            value=f"Point the bot at a channel with {command_refs.SET_HALL_OF_FAME_CHANNEL}, then "
                  f"pick how many reactions a message needs with {command_refs.SET_REACTION_THRESHOLD}. "
                  f"Both need the Manage Server permission.",
            inline=False)

    embed.add_field(
        name="For everyone",
        value=f"{command_refs.LEADERBOARD} rank the server\n"
              f"{command_refs.USER_PROFILE} a member's standing\n"
              f"{command_refs.HOF_WRAPPED} your year in review\n"
              f"{command_refs.HELP} every command",
        inline=True)
    embed.add_field(
        name="Links",
        value=f"[Add to a server]({messages.INVITE_URL})\n"
              f"[Support server]({messages.SUPPORT_SERVER_URL})\n"
              f"[Vote]({messages.VOTE_URL})\n"
              f"[Source]({messages.SOURCE_URL})",
        inline=True)

    if bot_user is not None and getattr(bot_user, "display_avatar", None) is not None:
        embed.set_thumbnail(url=bot_user.display_avatar.url)
    embed.set_footer(text=f"Hall of Fame {version.VERSION}")
    return embed


calculation_method_labels = {
    calculation_method_type.MOST_REACTIONS_ON_EMOJI: "Most reactions on a single emoji",
    calculation_method_type.TOTAL_REACTIONS: "Total reactions across all emojis",
    calculation_method_type.UNIQUE_USERS: "Unique members who reacted",
}

# Discord rejects an embed field value longer than 1024 characters, and a whitelist of custom emojis
# can pass that
embed_field_value_limit = 1024


def _toggle(enabled: bool, label: str) -> str:
    return f"{'✅' if enabled else '❌'} {label}"


def _whitelist_value(emojis) -> str:
    if not emojis:
        # An empty whitelist filters nothing out, see message_reactions.filter_whitelisted_reactions
        return f"Empty, so every emoji still counts. Add one with {command_refs.WHITELIST_EMOJI}"

    shown = []
    for index, emoji in enumerate(emojis):
        remaining = len(emojis) - index
        overflow = f" and {remaining} more"
        if len(" ".join(shown + [emoji])) + len(overflow) > embed_field_value_limit:
            return " ".join(shown) + overflow
        shown.append(emoji)
    return " ".join(shown)


def build_server_config_embed(guild, server_config) -> discord.Embed:
    """
    The card /get_server_config answers with: every setting, grouped by what it affects.

    Deliberately plain. The settings are what the reader came for, so the values are kept in one
    column with nothing between them: no thumbnail narrowing the text, and no command link on every
    row. Both of those wrap the values onto a second line and cost more in scanning than they give
    back, which is why the command that changes a setting is named once at the bottom instead.
    :param guild: The server the command was used in
    :param server_config: The server's configuration
    :return: The embed to send
    """
    embed = discord.Embed(
        title="⚙️ Hall of Fame Configuration",
        description=f"How the bot is set up in **{guild.name}**. "
                    f"Changing a setting needs the Manage Server permission.",
        color=discord.Color.gold()
    )

    channel = (f"<#{server_config.hall_of_fame_channel_id}>" if server_config.hall_of_fame_channel_id
               else "Not set")
    method = server_config.reaction_count_calculation_method
    method_label = calculation_method_labels.get(method, str(method).replace("_", " "))
    embed.add_field(
        name="🏆 Board",
        value=f"**Channel:** {channel}\n"
              f"**Reactions needed:** {server_config.reaction_threshold}\n"
              f"**Counting:** {method_label}",
        inline=False)

    embed.add_field(
        name="🎯 What qualifies",
        value=f"**Post age:** last {server_config.post_due_date} days\n"
              + "\n".join([
                  _toggle(server_config.include_author_in_reaction_calculation,
                          "Author's own reaction counts"),
                  _toggle(server_config.ignore_bot_messages, "Ignore messages from bots"),
                  _toggle(server_config.require_image_or_video, "Only posts with an image or video"),
              ]),
        inline=False)

    embed.add_field(
        name="📋 Board behaviour",
        value="\n".join([
            _toggle(server_config.allow_messages_in_hof_channel,
                    "Members can chat in the board channel"),
            _toggle(server_config.hide_hof_post_below_threshold,
                    "Hide posts that drop below the threshold"),
            _toggle(server_config.count_in_global_profiles,
                    "Posts count toward members' totals across servers"),
        ]),
        inline=False)

    if server_config.custom_emoji_check_logic:
        embed.add_field(
            name="😀 Emoji whitelist · on",
            value=_whitelist_value(server_config.whitelisted_emojis),
            inline=False)
    else:
        embed.add_field(
            name="😀 Emoji whitelist · off",
            value=f"Every emoji counts. Restrict it with {command_refs.CUSTOM_EMOJI_CHECK_LOGIC}",
            inline=False)

    # Discord rejects an empty field name, so a zero-width space keeps the spacer without a heading
    embed.add_field(
        name="​",
        value=f"Change any setting with its own command · {command_refs.HELP}\n"
              f"{messages.CONFIG_TROUBLESHOOT_HINT}",
        inline=False)
    embed.set_footer(text=f"Hall of Fame {version.VERSION}")
    return embed


async def answer_bot_mention(message: discord.Message, bot_user, server_config) -> bool:
    """
    Answer a ping with the information card, when the bot is able and has not just answered.
    :param message: The message that pinged the bot
    :param bot_user: The bot's own user
    :param server_config: The server's configuration, or None when it has not been set up
    :return: True when something was sent
    """
    permissions = message.channel.permissions_for(message.guild.me)
    if not permissions.send_messages:
        return False

    if not recently_answered_mentions.add_if_absent(message.channel.id):
        return False

    if not permissions.embed_links:
        # Without this permission an embed is dropped silently, so the answer is given as text
        await message.channel.send(
            f"**Hall of Fame** turns your server's best moments into a highlight reel and credits "
            f"the members behind them. Use {command_refs.HELP} for the commands. "
            f"(Grant the bot the Embed Links permission for the full card.)")
        return True

    await message.channel.send(embed=build_bot_info_embed(message.guild, bot_user, server_config))
    return True
