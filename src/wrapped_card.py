"""
Hall of Fame Wrapped as one card, and the two cards it opens.

/hof_wrapped posts the member's Wrapped in the channel as a single card. It has buttons any member can press:
Year in squares and Top 10 open those cards privately for whoever pressed, and Get my Wrapped posts the
presser's own. They are DynamicItems keyed by the server, member and year in their custom_id, so they keep
working on cards posted before a restart.

Everything shown comes from the member's stored Wrapped and their stored board posts. The fame rate uses
the messages the member sent that year, counted by Discord's message search when Wrapped was made. The search
also returns one of those messages, which is dropped unread; only the count is kept. When a post was written
comes from its message ID, so no message is fetched for the cards either.
"""
import calendar
import datetime
import json
from collections import Counter
from dataclasses import dataclass

import discord

import board_post
import setup_check
from repositories import hall_of_fame_message_repo, hof_wrapped_repo, opt_out_repo
from translations import messages

# Set by main at startup: lends a database connection, and opens a member's own Wrapped
connect = None
open_wrapped_handler = None

# A fame rate at or under this earns The Sharpshooter
SHARPSHOOTER_RATE = 150
REGULAR_POSTS = 25
EXPLORER_CHANNELS = 5
TOP_POSTS = 10
# How many fans, members they were a fan of and channels the card lists, and how many emojis
LIST_LENGTH = 3
EMOJI_LIST_LENGTH = 5
# A member featured more often than once in this many messages sees their fame rate as a share instead
PERCENT_BELOW_RATE = 10
BEST_POST_QUOTE_LIMIT = 200
SQUARE_SHADES = "·▒▓█"
WEEKDAYS = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


@dataclass
class Summary:
    """One member's Wrapped, as the card and the cards it opens read it"""
    guild_id: int
    user_id: int
    year: int
    posts: int
    reactions_received: int
    reactions_given: int
    messages_sent: int | None
    rank: int | None
    members: int
    server_messages_sent: int
    server_posts: int
    top_fans: list[tuple[int, int]]
    fans_of: list[tuple[int, int]]
    top_emojis: list[tuple[str, int]]
    top_channels: list[tuple[int, int]]
    ranks: dict
    channels_used: int
    best_post_channel_id: int | None
    best_post_message_id: int | None
    best_post_reactions: int

    @property
    def top_fan(self):
        return self.top_fans[0] if self.top_fans else None

    @property
    def top_emoji(self):
        return self.top_emojis[0] if self.top_emojis else None

    @property
    def top_channel(self):
        return self.top_channels[0] if self.top_channels else None


def _ranked(counts: dict, limit: int) -> list:
    """The entries with the highest counts first, as stored in JSON, up to limit"""
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]


def build_summary(row: dict, totals: dict) -> Summary:
    """
    :param row: The member's hof_wrapped row
    :param totals: hof_wrapped_repo.get_guild_wrapped_totals for the same server and year
    """
    own_id = str(row["user_id"])
    # A member reacting to their own posts is counted by Wrapped, but they are not their own fan
    fans = {member: count for member, count in json.loads(row.get("users_fans") or "{}").items() if member != own_id}
    fan_of = {member: count for member, count in json.loads(row.get("fan_of_users") or "{}").items()
              if member != own_id}
    emojis = json.loads(row.get("most_used_emojis") or "{}")
    channels = json.loads(row.get("most_used_channels") or "{}")
    ranks = json.loads(row.get("user_ranks") or "{}")
    return Summary(
        guild_id=row["guild_id"], user_id=row["user_id"], year=row["year"],
        posts=row.get("hof_message_posts") or 0,
        reactions_received=sum(fans.values()),
        reactions_given=row.get("reaction_count") or 0,
        messages_sent=row.get("messages_sent"),
        rank=ranks.get("hallOfFameMessagePosts"),
        members=totals["members"],
        server_messages_sent=totals["messages_sent"], server_posts=totals["posts"],
        top_fans=[(int(member), count) for member, count in _ranked(fans, LIST_LENGTH)],
        fans_of=[(int(member), count) for member, count in _ranked(fan_of, LIST_LENGTH)],
        top_emojis=_ranked(emojis, EMOJI_LIST_LENGTH),
        top_channels=[(int(channel), count) for channel, count in _ranked(channels, LIST_LENGTH)],
        ranks=ranks,
        channels_used=len(channels),
        best_post_channel_id=row.get("most_reacted_post_channel_id"),
        best_post_message_id=row.get("most_reacted_post_message_id"),
        best_post_reactions=row.get("most_reacted_post_reaction_count") or 0,
    )


def fame_rate(posts: int, messages_sent: int | None) -> int | None:
    """
    One in how many messages reached the board, or None when the messages were not counted. Also None when
    more posts were featured than messages counted, which happens when Discord's search has not indexed all
    of a server, since no rate drawn from that would be true
    """
    if not posts or not messages_sent or posts > messages_sent:
        return None
    return max(1, round(messages_sent / posts))


def fame_text(posts: int, messages_sent: int | None) -> str | None:
    """
    The fame rate as the card shows it: "1 in 214" for most members, and a share such as "77%" for those who
    get most of their messages featured, where "1 in 1" would say nothing
    """
    rate = fame_rate(posts, messages_sent)
    if rate is None:
        return None
    if messages_sent / posts < PERCENT_BELOW_RATE:
        return f"{round(100 * posts / messages_sent)}%"
    return f"1 in {rate:,}"


def member_fame_rate(summary: Summary) -> int | None:
    return fame_rate(summary.posts, summary.messages_sent)


def server_fame_rate(summary: Summary) -> int | None:
    return fame_rate(summary.server_posts, summary.server_messages_sent)


def title_for(summary: Summary) -> tuple[str, str]:
    """The member's title and why they earned it: the first that fits"""
    rate = member_fame_rate(summary)
    if summary.rank == 1 and summary.posts:
        name, reason = messages.WRAPPED_TITLE_HEADLINER
    elif rate is not None and rate <= SHARPSHOOTER_RATE:
        name, reason = messages.WRAPPED_TITLE_SHARPSHOOTER
    elif summary.posts >= REGULAR_POSTS:
        name, reason = messages.WRAPPED_TITLE_REGULAR
    elif summary.reactions_given > summary.reactions_received:
        name, reason = messages.WRAPPED_TITLE_HYPE
    elif summary.channels_used >= EXPLORER_CHANNELS:
        name, reason = messages.WRAPPED_TITLE_EXPLORER
    else:
        name, reason = messages.WRAPPED_TITLE_RISING
    return name, reason.format(fame=fame_text(summary.posts, summary.messages_sent), posts=summary.posts,
                               channels=summary.channels_used)


def post_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def best_post_link(summary: Summary) -> str | None:
    if not (summary.best_post_channel_id and summary.best_post_message_id):
        return None
    return post_link(summary.guild_id, summary.best_post_channel_id, summary.best_post_message_id)


def best_post_media(message) -> discord.MediaGalleryItem | None:
    """
    The first picture or video of the best post, to show with it. Left out when Discord flagged it, when it
    comes from an age-restricted channel, since the card can be posted in any channel, or when there is none
    """
    if message is None or board_post.content_scan_flags(message):
        return None
    if setup_check.is_age_restricted(getattr(message, "channel", None)):
        return None
    items = board_post.media_items(getattr(message, "attachments", None) or [])
    return items[0] if items else None


def best_post_quote(message) -> str:
    """
    The best post's words, cut short, read from Discord when the card is made and never stored. Left out
    from an age-restricted channel, as its picture is
    """
    if message is None or setup_check.is_age_restricted(getattr(message, "channel", None)):
        return ""
    return board_post.truncate_content(getattr(message, "content", None) or "", BEST_POST_QUOTE_LIMIT)


async def fetch_best_post(guild, summary: Summary):
    """The best post itself, for its picture. None when it is gone or out of reach"""
    channel = guild.get_channel(summary.best_post_channel_id) if summary.best_post_channel_id else None
    if channel is None or not summary.best_post_message_id:
        return None
    try:
        return await channel.fetch_message(summary.best_post_message_id)
    except discord.HTTPException:
        return None


def wrapped_container(summary: Summary, name: str, avatar_url: str | None, best_post=None) -> discord.ui.Container:
    """
    The member's Wrapped on one card: title and rank, fame rate and totals, the best moment, their people,
    emojis and channels, and their ranks in the server
    :param best_post: The best post itself, for its words and picture, None when it could not be fetched
    """
    title, _reason = title_for(summary)
    container = discord.ui.Container(accent_colour=discord.Colour.gold())
    heading = f"-# {messages.WRAPPED_PLAQUE_KICKER.format(year=summary.year)}\n## {name}\n{title}"
    if summary.rank:
        heading += " · " + messages.WRAPPED_PLAQUE_RANK.format(rank=summary.rank, members=summary.members)
    if avatar_url:
        container.add_item(discord.ui.Section(heading, accessory=discord.ui.Thumbnail(avatar_url)))
    else:
        container.add_item(discord.ui.TextDisplay(heading))
    container.add_item(discord.ui.Separator())

    fame = fame_text(summary.posts, summary.messages_sent)
    if fame is not None:
        fame_block = messages.WRAPPED_PLAQUE_FAME.format(fame=fame, sent=summary.messages_sent)
        average = fame_text(summary.server_posts, summary.server_messages_sent)
        if average is not None:
            fame_block += messages.WRAPPED_PLAQUE_FAME_AVERAGE.format(average=average)
        container.add_item(discord.ui.TextDisplay(fame_block))
    container.add_item(discord.ui.TextDisplay(messages.WRAPPED_PLAQUE_STATS.format(
        posts=summary.posts, received=summary.reactions_received, given=summary.reactions_given,
        channels=summary.channels_used)))

    if summary.best_post_reactions:
        container.add_item(discord.ui.Separator())
        best = messages.WRAPPED_PLAQUE_BEST.format(count=summary.best_post_reactions)
        quote = best_post_quote(best_post)
        container.add_item(discord.ui.TextDisplay(f"{best}\n>>> {quote}" if quote else best))
        media = best_post_media(best_post)
        if media is not None:
            container.add_item(discord.ui.MediaGallery(media))

    lists = []
    if summary.top_fans:
        lists.append(messages.WRAPPED_PLAQUE_FANS.format(
            members=" · ".join(f"<@{member}> {count}" for member, count in summary.top_fans)))
    if summary.fans_of:
        lists.append(messages.WRAPPED_PLAQUE_FAN_OF.format(
            members=" · ".join(f"<@{member}> {count}" for member, count in summary.fans_of)))
    if summary.top_emojis:
        lists.append(messages.WRAPPED_PLAQUE_EMOJIS.format(
            emojis=" · ".join(f"{emoji} {count}" for emoji, count in summary.top_emojis)))
    if summary.top_channels:
        lists.append(messages.WRAPPED_PLAQUE_CHANNELS.format(
            channels=" · ".join(f"<#{channel}> {count}" for channel, count in summary.top_channels)))
    if lists:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("\n".join(lists)))

    ranks = [f"**#{summary.ranks[key]}** {label}" for key, label in messages.WRAPPED_RANK_LABELS.items()
             if summary.ranks.get(key)]
    if ranks:
        container.add_item(discord.ui.TextDisplay(messages.WRAPPED_PLAQUE_RANKS.format(ranks=" · ".join(ranks))))

    buttons = [SquaresButton(summary.guild_id, summary.user_id, summary.year),
               TopButton(summary.guild_id, summary.user_id, summary.year)]
    link = best_post_link(summary)
    if link:
        buttons.append(discord.ui.Button(style=discord.ButtonStyle.link, label=messages.WRAPPED_JUMP, url=link))
    buttons.append(MineButton(summary.guild_id))
    container.add_item(discord.ui.ActionRow(*buttons))
    return container


def wrapped_view(summary: Summary, name: str, avatar_url: str | None, best_post=None) -> discord.ui.LayoutView:
    """The card as posted. Its buttons are DynamicItems, so it needs no timeout"""
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(wrapped_container(summary, name, avatar_url, best_post))
    return view


async def send_wrapped(interaction: discord.Interaction, row: dict, totals: dict):
    """
    Post the member's Wrapped card in the channel. Deferred first, as the best post is fetched for its words
    and picture. No one it names is pinged
    """
    await interaction.response.defer(thinking=True)
    summary = build_summary(row, totals)
    best_post = await fetch_best_post(interaction.guild, summary)
    member = interaction.user
    avatar = getattr(getattr(member, "display_avatar", None), "url", None)
    view = wrapped_view(summary, getattr(member, "display_name", None) or member.name, avatar, best_post)
    await interaction.followup.send(view=view, allowed_mentions=discord.AllowedMentions.none())


def posts_in_year(posts: list[dict], year: int) -> list[dict]:
    """The posts written in the year, each with when it was written, taken from its message ID"""
    dated = []
    for post in posts:
        written = discord.utils.snowflake_time(post["message_id"])
        if written.year == year:
            dated.append({**post, "written": written})
    return dated


def longest_daily_run(dates) -> int:
    days = sorted(set(dates))
    best = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous is not None and (day - previous).days == 1 else 1
        best = max(best, run)
        previous = day
    return best


def squares_card(member: str, year: int, posts: list[dict]) -> str:
    """
    The year as a grid of characters in a code block, a row per month and a square per day, so it needs no
    image and looks the same on a phone
    """
    per_day = Counter(post["written"].date() for post in posts)
    rows = []
    for month in range(1, 13):
        days = calendar.monthrange(year, month)[1]
        squares = "".join(SQUARE_SHADES[min(per_day.get(datetime.date(year, month, day), 0), 3)]
                          for day in range(1, days + 1))
        rows.append(f"{calendar.month_abbr[month].upper()} {squares}")
    lines = [messages.WRAPPED_SQUARES_TITLE.format(member=member, year=year), "```\n" + "\n".join(rows) + "\n```",
             messages.WRAPPED_SQUARES_LEGEND]
    if posts:
        weekday = Counter(post["written"].weekday() for post in posts).most_common(1)[0][0]
        hour = Counter(post["written"].hour for post in posts).most_common(1)[0][0]
        month = Counter(post["written"].month for post in posts).most_common(1)[0][0]
        run = longest_daily_run(per_day)
        lines += [messages.WRAPPED_SQUARES_STREAK.format(days=f"{run} day" if run == 1 else f"{run} days"),
                  messages.WRAPPED_SQUARES_WEEKDAY.format(weekday=WEEKDAYS[weekday]),
                  messages.WRAPPED_SQUARES_HOUR.format(hour=hour),
                  messages.WRAPPED_SQUARES_MONTH.format(month=calendar.month_name[month])]
    return "\n".join(lines)


def top_card(member: str, year: int, guild_id: int, posts: list[dict]) -> str:
    """The member's most reacted posts of the year, with a link to each. No message text, so nothing is read"""
    best = sorted(posts, key=lambda post: (post["reaction_count"] or 0), reverse=True)[:TOP_POSTS]
    lines = [messages.WRAPPED_TOP_TITLE.format(member=member, count=len(best), year=year)]
    for rank, post in enumerate(best, start=1):
        lines.append(messages.WRAPPED_TOP_LINE.format(
            rank=rank, count=post["reaction_count"] or 0, channel=f"<#{post['channel_id']}>",
            date=f"{calendar.month_abbr[post['written'].month]} {post['written'].day}",
            link=post_link(guild_id, post["channel_id"], post["message_id"])))
    return "\n".join(lines)


async def show_card(interaction: discord.Interaction, guild_id: int, user_id: int, year: int, kind: str):
    """Answer a Wrapped card's Year in squares or Top 10 button, privately for whoever pressed it"""
    async with connect() as connection:
        row = hof_wrapped_repo.get_hof_wrapped(connection, guild_id, user_id, year)
        # A member who asked not to be featured since sharing is not shown, nor one who deleted their data
        available = row is not None and not opt_out_repo.is_opted_out(connection, user_id)
        posts = hall_of_fame_message_repo.get_member_posts(connection, guild_id, user_id) if available else []
    if not available:
        await interaction.response.send_message(messages.WRAPPED_CARD_GONE, ephemeral=True)
        return
    dated = posts_in_year(posts, year)
    if not dated:
        await interaction.response.send_message(messages.WRAPPED_CARD_EMPTY.format(year=year), ephemeral=True)
        return
    member = f"<@{user_id}>"
    text = squares_card(member, year, dated) if kind == "squares" else top_card(member, year, guild_id, dated)
    view = discord.ui.LayoutView()
    container = discord.ui.Container(accent_colour=discord.Colour.gold())
    container.add_item(discord.ui.TextDisplay(text))
    view.add_item(container)
    await interaction.response.send_message(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class SquaresButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"hofw:sq:(?P<guild>\d+):(?P<user>\d+):(?P<year>\d+)"):
    def __init__(self, guild_id: int, user_id: int, year: int):
        super().__init__(discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.WRAPPED_SQUARES_BUTTON,
                                           custom_id=f"hofw:sq:{guild_id}:{user_id}:{year}"))
        self.guild_id, self.user_id, self.year = guild_id, user_id, year

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["guild"]), int(match["user"]), int(match["year"]))

    async def callback(self, interaction: discord.Interaction):
        await show_card(interaction, self.guild_id, self.user_id, self.year, "squares")


class TopButton(discord.ui.DynamicItem[discord.ui.Button],
                template=r"hofw:top:(?P<guild>\d+):(?P<user>\d+):(?P<year>\d+)"):
    def __init__(self, guild_id: int, user_id: int, year: int):
        super().__init__(discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.WRAPPED_TOP_BUTTON,
                                           custom_id=f"hofw:top:{guild_id}:{user_id}:{year}"))
        self.guild_id, self.user_id, self.year = guild_id, user_id, year

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["guild"]), int(match["user"]), int(match["year"]))

    async def callback(self, interaction: discord.Interaction):
        await show_card(interaction, self.guild_id, self.user_id, self.year, "top")


class MineButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hofw:me:(?P<guild>\d+)"):
    """Get my Wrapped on someone else's card: the presser's own card, as /hof_wrapped would post it"""

    def __init__(self, guild_id: int):
        super().__init__(discord.ui.Button(style=discord.ButtonStyle.primary, label=messages.WRAPPED_MINE_BUTTON,
                                           custom_id=f"hofw:me:{guild_id}"))
        self.guild_id = guild_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["guild"]))

    async def callback(self, interaction: discord.Interaction):
        if open_wrapped_handler is not None:
            await open_wrapped_handler(interaction)


DYNAMIC_ITEMS = (SquaresButton, TopButton, MineButton)
