"""
Hall of Fame Wrapped as a story, a plaque and two cards.

/hof_wrapped opens a private story: a few pages the member steps through, ending on their summary. From the
summary, Show to others posts that summary, the plaque, in the channel. The plaque has buttons any member can
press: Year in squares and Top 10 open those cards privately for whoever pressed, and Get my Wrapped opens
the presser's own story. They are DynamicItems keyed by the server, member and year in their custom_id, so
they keep working on plaques posted before a restart.

Everything shown comes from the member's stored Wrapped and their stored board posts. The fame rate uses
the messages the member sent that year, counted by Discord's message search when Wrapped was made. The search
also returns one of those messages, which is dropped unread; only the count is kept. When a post was written comes from its message ID, so no message is fetched for the
cards either.
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

STORY_TIMEOUT_SECONDS = 900
# A fame rate at or under this earns The Sharpshooter
SHARPSHOOTER_RATE = 150
REGULAR_POSTS = 25
EXPLORER_CHANNELS = 5
TOP_POSTS = 10
SQUARE_SHADES = "·▒▓█"
WEEKDAYS = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")


@dataclass
class Summary:
    """One member's Wrapped, as the story, the plaque and the cards read it"""
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
    top_fan: tuple[int, int] | None
    fan_of: tuple[int, int] | None
    top_emoji: tuple[str, int] | None
    top_channel: tuple[int, int] | None
    channels_used: int
    best_post_channel_id: int | None
    best_post_message_id: int | None
    best_post_reactions: int


def _top(counts: dict):
    """The entry with the highest count, its key as stored in JSON, or None when empty"""
    if not counts:
        return None
    key, count = max(counts.items(), key=lambda item: item[1])
    return key, count


def build_summary(row: dict, totals: dict) -> Summary:
    """
    :param row: The member's hof_wrapped row
    :param totals: hof_wrapped_repo.get_guild_wrapped_totals for the same server and year
    """
    fans = json.loads(row.get("users_fans") or "{}")
    fan_of = json.loads(row.get("fan_of_users") or "{}")
    emojis = json.loads(row.get("most_used_emojis") or "{}")
    channels = json.loads(row.get("most_used_channels") or "{}")
    ranks = json.loads(row.get("user_ranks") or "{}")
    top_fan, top_fan_of, top_channel = _top(fans), _top(fan_of), _top(channels)
    return Summary(
        guild_id=row["guild_id"], user_id=row["user_id"], year=row["year"],
        posts=row.get("hof_message_posts") or 0,
        reactions_received=sum(fans.values()),
        reactions_given=row.get("reaction_count") or 0,
        messages_sent=row.get("messages_sent"),
        rank=ranks.get("hallOfFameMessagePosts"),
        members=totals["members"],
        server_messages_sent=totals["messages_sent"], server_posts=totals["posts"],
        top_fan=(int(top_fan[0]), top_fan[1]) if top_fan else None,
        fan_of=(int(top_fan_of[0]), top_fan_of[1]) if top_fan_of else None,
        top_emoji=_top(emojis),
        top_channel=(int(top_channel[0]), top_channel[1]) if top_channel else None,
        channels_used=len(channels),
        best_post_channel_id=row.get("most_reacted_post_channel_id"),
        best_post_message_id=row.get("most_reacted_post_message_id"),
        best_post_reactions=row.get("most_reacted_post_reaction_count") or 0,
    )


def fame_rate(posts: int, messages_sent: int | None) -> int | None:
    """One in how many messages reached the board, or None when the messages were not counted"""
    if not posts or not messages_sent:
        return None
    return max(1, round(messages_sent / posts))


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
    return name, reason.format(rate=rate or 0, posts=summary.posts, channels=summary.channels_used)


def post_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def best_post_link(summary: Summary) -> str | None:
    if not (summary.best_post_channel_id and summary.best_post_message_id):
        return None
    return post_link(summary.guild_id, summary.best_post_channel_id, summary.best_post_message_id)


def best_post_media(message) -> discord.MediaGalleryItem | None:
    """
    The first picture or video of the best post, to show with it. Left out when Discord flagged it, when it
    comes from an age-restricted channel, since the plaque can be shared anywhere, or when there is none
    """
    if message is None or board_post.content_scan_flags(message):
        return None
    if setup_check.is_age_restricted(getattr(message, "channel", None)):
        return None
    items = board_post.media_items(getattr(message, "attachments", None) or [])
    return items[0] if items else None


async def fetch_best_post(guild, summary: Summary):
    """The best post itself, for its picture. None when it is gone or out of reach"""
    channel = guild.get_channel(summary.best_post_channel_id) if summary.best_post_channel_id else None
    if channel is None or not summary.best_post_message_id:
        return None
    try:
        return await channel.fetch_message(summary.best_post_message_id)
    except discord.HTTPException:
        return None


@dataclass
class Page:
    kicker: str
    big: str
    text: str = ""
    media: discord.MediaGalleryItem | None = None
    link: str | None = None


def story_pages(summary: Summary, name: str, media: discord.MediaGalleryItem | None) -> list[Page]:
    """The pages before the summary. A page with nothing to say, such as the fame rate when the messages
    were not counted, is left out"""
    pages = [Page(messages.WRAPPED_INTRO_KICKER.format(year=summary.year), name, messages.WRAPPED_INTRO_TEXT)]

    posts_text = messages.WRAPPED_POSTS_TEXT
    if summary.rank:
        posts_text += " " + messages.WRAPPED_POSTS_RANK.format(rank=summary.rank, members=summary.members)
    pages.append(Page(messages.WRAPPED_POSTS_KICKER, str(summary.posts), posts_text))

    rate = member_fame_rate(summary)
    if rate is not None:
        fame_text = messages.WRAPPED_FAME_TEXT.format(sent=summary.messages_sent, rate=rate)
        average = server_fame_rate(summary)
        if average is not None:
            fame_text += " " + messages.WRAPPED_FAME_AVERAGE.format(average=average)
        pages.append(Page(messages.WRAPPED_FAME_KICKER, f"1 in {rate:,}", fame_text))

    if summary.best_post_reactions:
        pages.append(Page(messages.WRAPPED_BEST_KICKER, str(summary.best_post_reactions),
                          messages.WRAPPED_BEST_TEXT, media, best_post_link(summary)))

    people = []
    if summary.top_fan:
        people.append(messages.WRAPPED_TOP_FAN.format(fan=f"<@{summary.top_fan[0]}>", count=summary.top_fan[1]))
    if summary.fan_of:
        people.append(messages.WRAPPED_FAN_OF.format(member=f"<@{summary.fan_of[0]}>", count=summary.fan_of[1]))
    if summary.top_emoji:
        people.append(messages.WRAPPED_EMOJI.format(emoji=summary.top_emoji[0]))
    if people:
        big = f"<@{summary.top_fan[0]}>" if summary.top_fan else summary.top_emoji[0] if summary.top_emoji else ""
        pages.append(Page(messages.WRAPPED_PEOPLE_KICKER, big, "\n".join(people)))

    title, reason = title_for(summary)
    pages.append(Page(messages.WRAPPED_TITLE_KICKER, title, reason))
    return pages


def page_container(page: Page, number: int, total: int) -> discord.ui.Container:
    container = discord.ui.Container(accent_colour=discord.Colour.gold())
    progress = "▰" * number + "▱" * (total - number)
    container.add_item(discord.ui.TextDisplay(
        f"-# {progress}  {messages.WRAPPED_PAGE.format(page=number, pages=total)}\n**{page.kicker}**"))
    container.add_item(discord.ui.TextDisplay(f"# {page.big}"))
    if page.text:
        container.add_item(discord.ui.TextDisplay(page.text))
    if page.media is not None:
        container.add_item(discord.ui.MediaGallery(page.media))
    if page.link:
        container.add_item(discord.ui.ActionRow(discord.ui.Button(style=discord.ButtonStyle.link,
                                                                  label=messages.WRAPPED_JUMP, url=page.link)))
    return container


def plaque_container(summary: Summary, name: str, avatar_url: str | None,
                     media: discord.MediaGalleryItem | None, shared: bool) -> discord.ui.Container:
    """
    The one-page summary, shown last in the story and posted by Show to others
    :param shared: Whether it is the copy posted for everyone, which also offers Get my Wrapped
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

    rate = member_fame_rate(summary)
    if rate is not None:
        fame = messages.WRAPPED_PLAQUE_FAME.format(rate=rate, sent=summary.messages_sent)
        average = server_fame_rate(summary)
        if average is not None:
            fame += messages.WRAPPED_PLAQUE_FAME_AVERAGE.format(average=average)
        container.add_item(discord.ui.TextDisplay(fame))
    container.add_item(discord.ui.TextDisplay(messages.WRAPPED_PLAQUE_STATS.format(
        posts=summary.posts, received=summary.reactions_received, given=summary.reactions_given)))

    if summary.best_post_reactions:
        container.add_item(discord.ui.TextDisplay(messages.WRAPPED_PLAQUE_BEST.format(count=summary.best_post_reactions)))
        if media is not None:
            container.add_item(discord.ui.MediaGallery(media))

    highlights = []
    if summary.top_fan:
        highlights.append(messages.WRAPPED_PLAQUE_FAN.format(fan=f"<@{summary.top_fan[0]}>", count=summary.top_fan[1]))
    if summary.top_emoji:
        highlights.append(messages.WRAPPED_PLAQUE_EMOJI.format(emoji=summary.top_emoji[0]))
    if summary.top_channel:
        highlights.append(messages.WRAPPED_PLAQUE_CHANNEL.format(channel=f"<#{summary.top_channel[0]}>"))
    if highlights:
        container.add_item(discord.ui.TextDisplay("\n".join(highlights)))

    buttons = [SquaresButton(summary.guild_id, summary.user_id, summary.year),
               TopButton(summary.guild_id, summary.user_id, summary.year)]
    link = best_post_link(summary)
    if link:
        buttons.append(discord.ui.Button(style=discord.ButtonStyle.link, label=messages.WRAPPED_JUMP, url=link))
    if shared:
        buttons.append(MineButton(summary.guild_id))
    container.add_item(discord.ui.ActionRow(*buttons))
    return container


def plaque_view(summary: Summary, name: str, avatar_url: str | None, media) -> discord.ui.LayoutView:
    """The plaque as posted for everyone. Its buttons are DynamicItems, so it needs no timeout"""
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.TextDisplay(messages.WRAPPED_SHARED_BY.format(member=f"<@{summary.user_id}>")))
    view.add_item(plaque_container(summary, name, avatar_url, media, shared=True))
    return view


class StoryView(discord.ui.LayoutView):
    """
    The private story. It is only seen by the member who opened it, so its buttons need no check on who
    pressed them, and it lives as long as the message stays open
    """

    def __init__(self, summary: Summary, name: str, avatar_url: str | None, media):
        super().__init__(timeout=STORY_TIMEOUT_SECONDS)
        self.summary = summary
        self.name = name
        self.avatar_url = avatar_url
        self.media = media
        self.pages = story_pages(summary, name, media)
        self.index = 0
        self.shared = False
        self.render()

    @property
    def total(self) -> int:
        # The summary is the last page
        return len(self.pages) + 1

    @property
    def on_summary(self) -> bool:
        return self.index == len(self.pages)

    def render(self):
        self.clear_items()
        if self.on_summary:
            self.add_item(plaque_container(self.summary, self.name, self.avatar_url, self.media, shared=False))
        else:
            self.add_item(page_container(self.pages[self.index], self.index + 1, self.total))

        back = discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.WRAPPED_BACK,
                                 disabled=self.index == 0)
        back.callback = self.go_back
        row = [back]
        if self.on_summary:
            share = discord.ui.Button(style=discord.ButtonStyle.primary,
                                      label=messages.WRAPPED_SHARED if self.shared else messages.WRAPPED_SHARE,
                                      disabled=self.shared)
            share.callback = self.share
            row.append(share)
        else:
            forward = discord.ui.Button(style=discord.ButtonStyle.primary, label=messages.WRAPPED_NEXT)
            forward.callback = self.go_next
            skip = discord.ui.Button(style=discord.ButtonStyle.secondary, label=messages.WRAPPED_SKIP)
            skip.callback = self.skip
            row += [forward, skip]
        self.add_item(discord.ui.ActionRow(*row))

    async def show(self, interaction: discord.Interaction, index: int):
        self.index = max(0, min(index, len(self.pages)))
        self.render()
        await interaction.response.edit_message(view=self)

    async def go_back(self, interaction: discord.Interaction):
        await self.show(interaction, self.index - 1)

    async def go_next(self, interaction: discord.Interaction):
        await self.show(interaction, self.index + 1)

    async def skip(self, interaction: discord.Interaction):
        await self.show(interaction, len(self.pages))

    async def share(self, interaction: discord.Interaction):
        """Post the plaque for everyone, once, as a followup, which needs no permission to send in the channel"""
        if self.shared:
            # A second press that arrived before the button was disabled. Set before the first await below, so
            # only one press gets past this
            # noinspection PyUnresolvedReferences
            await interaction.response.defer()
            return
        self.shared = True
        self.render()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(view=plaque_view(self.summary, self.name, self.avatar_url, self.media),
                                        allowed_mentions=discord.AllowedMentions.none())


async def send_story(interaction: discord.Interaction, row: dict, totals: dict):
    """Open the story for the member who asked, privately. Deferred first, as the best post is fetched"""
    await interaction.response.defer(ephemeral=True, thinking=True)
    summary = build_summary(row, totals)
    media = best_post_media(await fetch_best_post(interaction.guild, summary))
    member = interaction.user
    avatar = getattr(getattr(member, "display_avatar", None), "url", None)
    view = StoryView(summary, getattr(member, "display_name", None) or member.name, avatar, media)
    await interaction.followup.send(view=view, ephemeral=True)


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
    """Answer a plaque's Year in squares or Top 10 button, privately for whoever pressed it"""
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
    """Get my Wrapped on a shared plaque: the presser's own story, as /hof_wrapped would open it"""

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
