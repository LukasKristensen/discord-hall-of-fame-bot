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


def build_invite_view() -> discord.ui.View:
    return build_link_buttons(INVITE_LINK, SUPPORT_SERVER_LINK)


def build_vote_view() -> discord.ui.View:
    return build_link_buttons(VOTE_LINK)


def build_help_view() -> discord.ui.View:
    return build_link_buttons(INVITE_LINK, VOTE_LINK, SUPPORT_SERVER_LINK)


def build_welcome_view() -> discord.ui.View:
    # The server has just installed the bot, so there is nothing to invite it to yet
    return build_link_buttons(SUPPORT_SERVER_LINK, VOTE_LINK)


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
              f"{command_refs.SERVER_HOF_WRAPPED} the server's year in review",
        inline=False)

    embed.add_field(
        name="🔒 Your data",
        value=f"{command_refs.MY_DATA} see everything stored about you\n"
              f"{command_refs.DELETE_MY_DATA} delete it\n"
              f"{command_refs.PROFILE_PRIVACY} hide or show your totals across servers",
        inline=False)

    embed.add_field(
        name="⚙️ Board · Manage Server",
        value=f"{command_refs.SET_HALL_OF_FAME_CHANNEL} the channel posts go to\n"
              f"{command_refs.SET_REACTION_THRESHOLD} reactions needed\n"
              f"{command_refs.CALCULATION_METHOD} how reactions are counted\n"
              f"{command_refs.GET_SERVER_CONFIG} every current setting",
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
              f"[Vote]({messages.VOTE_URL}) · "
              f"[Source](https://github.com/LukasKristensen/discord-hall-of-fame-bot)\n"
              f"Found a bug or have an idea? {command_refs.FEEDBACK}\n"
              f"Not working? Check the bot's permissions in the channel, or re-invite it.",
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
    :return:
    """
    user_has_most_this_month_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "this_month_hall_of_fame_messages")
    user_with_most_all_time_hall_of_fame_messages = server_user_repo.check_if_user_is_top_of_stat(
        connection, user.id, interaction.guild.id, "total_hall_of_fame_messages")

    show_global = global_profile_adds_something(global_profile, user_stats)
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

    if user_stats:
        highlights = hall_of_fame_message_repo.get_member_highlights(connection, interaction.guild.id, user.id)
        gap = rank_gap_line(user_stats, lambda stat, rank_field, rank: server_user_repo.get_stat_at_rank(
            connection, interaction.guild.id, stat, rank_field, rank))
        value = highlights_value(interaction.guild.id, highlights, gap)
        if value:
            embed.add_field(name=messages.HIGHLIGHTS_HEADING, value=value, inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=messages.GLOBAL_STATS_FOOTER if show_global else messages.STATS_FOOTER)
    await interaction.response.send_message(embed=embed)


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


def global_profile_adds_something(global_profile: dict, user_stats: dict) -> bool:
    """
    Whether the totals across servers say more than the server profile above them. When every
    counted post is from this server the two match, and the section would only repeat the card
    :param global_profile: The totals from global_profile_repo.get_global_profile, or None
    :param user_stats: The member's row in this server
    """
    if not global_profile or not global_profile["posts"]:
        return False
    return global_profile["posts"] != (user_stats or {}).get("total_hall_of_fame_messages", 0)


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


def build_my_data_export(user_id: int, posts: list, standings: list, wrapped: list, profile_hidden: bool,
                         not_counted: bool = False) -> bytes:
    """
    The file /my_data attaches: every row stored about a member, as JSON.

    Only ever sent privately to the member it describes, so unlike the totals on a profile it does include
    the server and message IDs, which are the member's own data.
    :param user_id: The member's user ID
    :param posts: Their featured posts, from hall_of_fame_message
    :param standings: Their per-server statistics, from server_user
    :param wrapped: Their Wrapped rows, from hof_wrapped
    :param profile_hidden: Whether they hid their totals across servers
    :param not_counted: Whether they asked not to be counted from now on
    :return: The file's contents
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

    for key in ("featured_posts", "server_statistics", "wrapped"):
        export[key] = stringify_ids(export[key])
    # Datetimes, and anything else JSON has no type for, are written as text
    return json.dumps(export, indent=2, default=str, ensure_ascii=False).encode("utf-8")


class ConfirmDeleteView(discord.ui.View):
    """
    The confirm and cancel buttons under /delete_my_data. Deleting cannot be undone, so it only
    happens on a deliberate second click, and only the member who asked can make it
    """

    def __init__(self, owner_id: int, on_confirm, timeout_seconds: float = 120):
        """
        :param owner_id: The member whose data would be deleted
        :param on_confirm: Coroutine function taking the button's interaction and whether the member
            also asked not to be counted from now on, which deletes and answers
        :param timeout_seconds: How long the buttons stay usable
        """
        super().__init__(timeout=timeout_seconds)
        self.owner_id = owner_id
        self.on_confirm = on_confirm
        self.original_interaction = None
        self.finished = False

        confirm = discord.ui.Button(style=discord.ButtonStyle.danger, label=messages.DELETE_MY_DATA_BUTTON)
        stop_counting = discord.ui.Button(style=discord.ButtonStyle.danger, label=messages.DELETE_AND_STOP_BUTTON)
        cancel = discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.CANCEL_BUTTON)
        confirm.callback = self.confirm
        stop_counting.callback = self.confirm_and_stop_counting
        cancel.callback = self.cancel
        self.add_item(confirm)
        self.add_item(stop_counting)
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # The prompt is ephemeral, so nobody else should see it, but a click is checked all the same
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(messages.DELETE_MY_DATA_NOT_YOURS, ephemeral=True)
            return False
        return True

    async def confirm(self, interaction: discord.Interaction):
        self.finished = True
        self.stop()
        await self.on_confirm(interaction, False)

    async def confirm_and_stop_counting(self, interaction: discord.Interaction):
        self.finished = True
        self.stop()
        await self.on_confirm(interaction, True)

    async def cancel(self, interaction: discord.Interaction):
        self.finished = True
        self.stop()
        await interaction.response.edit_message(content=messages.DELETE_MY_DATA_CANCELLED, view=None)

    async def on_timeout(self):
        if self.finished or self.original_interaction is None:
            return
        try:
            await self.original_interaction.edit_original_response(
                content=messages.DELETE_MY_DATA_EXPIRED.format(command=command_refs.DELETE_MY_DATA), view=None)
        except discord.HTTPException:
            # The member dismissed the prompt, so there is nothing left to update
            pass


class CountAgainView(discord.ui.View):
    """The button /delete_my_data offers a member who asked not to be counted"""

    def __init__(self, owner_id: int, on_count_again, timeout_seconds: float = 120):
        super().__init__(timeout=timeout_seconds)
        self.owner_id = owner_id
        self.on_count_again = on_count_again
        button = discord.ui.Button(style=discord.ButtonStyle.primary, label=messages.COUNT_ME_AGAIN_BUTTON)
        button.callback = self.count_again
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(messages.DELETE_MY_DATA_NOT_YOURS, ephemeral=True)
            return False
        return True

    async def count_again(self, interaction: discord.Interaction):
        self.stop()
        await self.on_count_again(interaction)


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
              "[Source](https://github.com/LukasKristensen/discord-hall-of-fame-bot)",
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
        value=f"Change any setting with its own command · {command_refs.HELP}",
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
