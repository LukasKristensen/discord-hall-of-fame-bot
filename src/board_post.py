"""
A Hall of Fame post as one Components V2 message: the author, the reply they answered, the text, every image
and video, the counted emojis and a button back to the message.

Everything here only builds what a post shows. Sending, updating, hiding and restoring posts stay in utils,
which also keeps the embed posts made before.

Media reaches a post four ways, and the featured message and the one it replies to go through the same steps:
attachments (images, GIFs and videos into the gallery, audio and other files as links), stickers (into the
gallery, or named when Discord's animated Lottie stickers cannot be shown), link previews (their picture, GIF
or video file) and the snapshot a forward keeps of the message it forwards. tests/test_post_matrix.py crosses
them all.
"""
import re
import urllib.parse

import discord

from message_reactions import filter_whitelisted_reactions, reaction_count
from repositories import opt_out_repo, server_config_repo
from translations import messages

# Set by Discord's content scanning on attachments and embeds, with the same bits on both. discord.py 2.5
# names only the explicit one, so all three are read from the raw flags value
EXPLICIT_CONTENT = 1 << 4
GORE_CONTENT = 1 << 6
SELF_HARM_CONTENT = 1 << 7

# New posts are one Components V2 message, which holds every image and video of a message, keeps spoilers
# covered and lists the most used counted emojis. Posts made before keep their embed, and are updated and hidden as
# embeds, since a message cannot change between the two once sent

# A media gallery holds at most ten items
post_media_limit = 10
# The most emojis listed on a post, most used first, so a message with dozens keeps a short line
post_reactions_listed = 8
# Files that are not images or videos are linked under the text, up to this many
post_files_listed = 5
# Text up to this long sits beside the avatar. Longer text goes under the header at full width, where it reads
post_text_beside_limit = 300
# A post holds 4,000 characters of text, so a message keeps up to this much of its own
post_text_limit = 2000
# Discord's limit on the text of one Components V2 message, all text displays together
post_text_budget = 4000
# The replied-to message is quoted this far, as Discord's own reply preview is a single line
post_quote_limit = 200
# A message that is nothing but a link
BARE_LINK = re.compile(r"^<?https?://\S+>?$")
# Link previews Discord shows in place of their link when the link is the whole message: a picture, a GIF,
# or a link straight to a video file, which preview_media names video_file
PREVIEWS_REPLACING_LINK = ("image", "gifv", "video_file")
# A Tenor GIF's MP4, whose path ends its ID with the format code AAAPo. The GIF of the same ID ends in AAAAC
TENOR_MP4 = re.compile(r"^(https://media\d*\.tenor\.com/[\w-]+?)AAAPo/([^/?#]+)\.mp4$")
# The ID given to a post's reactions line, so a new count is compared with the post without rebuilding it
POST_REACTIONS_ID = 50
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.webm')
MEDIA_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp') + VIDEO_EXTENSIONS
AUDIO_EXTENSIONS = ('.mp3', '.ogg', '.oga', '.opus', '.wav', '.m4a', '.flac', '.aac')
# A post repeats the words of the message it features. An embed never pinged its mentions, but text in
# components does, so every post is sent and edited without mentions
NO_MENTIONS = discord.AllowedMentions.none()


def truncate_content(content: str, limit: int = 1024) -> str:
    """
    Truncate message content so that it fits within the 1024 character limit of an embed field
    :param content: The content of a message
    :param limit: The most characters the result may have, lower when the field holds other text too
    :return: The truncated content
    """
    if not content:
        return ""
    return content[:limit - 3] + "..." if len(content) > limit else content


async def reply_context(message: discord.Message, connection):
    """
    The message a featured message replies to, shown with it so the moment still makes sense later
    :param message: The featured message
    :param connection: The database connection
    :return: The replied-to message, or None when there is none, it is gone, or its author asked not to be
        featured, and whether it was deleted
    """
    if not (message.reference and message.reference.message_id):
        return None, False
    # A forward carries a reference too, to the message it forwards, which is not a reply
    if getattr(message.reference, "type", None) == discord.MessageReferenceType.forward:
        return None, False
    try:
        reference_message = await message.channel.fetch_message(message.reference.message_id)
    except discord.NotFound:
        return None, True
    except discord.HTTPException:
        # The message that was replied to cannot be read, so the reply is posted on its own
        return None, False
    # A member who asked not to be featured is left off the board in replies too: their name, words and
    # image would otherwise go up with the reply. The reply is posted on its own, with no sign of them
    if opt_out_repo.is_opted_out(connection, reference_message.author.id):
        return None, False
    return reference_message, False


async def forward_may_show(message: discord.Message, connection) -> bool:
    """
    Whether a forward may show the message it forwards. Discord's snapshot of it carries no author, so the
    original is fetched to keep a member who asked not to be featured off the board, as replies do. When it
    cannot be fetched, such as from another server or a channel the bot cannot read, it is not shown either,
    since nobody can tell whose it is
    :param message: A message that forwards another
    :param connection: The database connection
    :return: True when the original was found and its author has not opted out
    """
    reference = getattr(message, "reference", None)
    if reference is None or not reference.message_id:
        return False
    guild = getattr(message, "guild", None)
    reference_guild = getattr(reference, "guild_id", None)
    if reference_guild is not None and (guild is None or reference_guild != guild.id):
        return False
    channel_id = getattr(reference, "channel_id", None)
    if channel_id is None or channel_id == message.channel.id:
        channel = message.channel
    else:
        get_channel = getattr(guild, "get_channel_or_thread", None)
        channel = get_channel(channel_id) if get_channel is not None else None
    if channel is None:
        return False
    try:
        original = await channel.fetch_message(reference.message_id)
    except discord.HTTPException:
        return False
    return not opt_out_repo.is_opted_out(connection, original.author.id)


async def shown_body(message: discord.Message, connection):
    """
    What a post shows of a message: featured_body, except that a forward whose original may not be shown
    shows the forwarding message itself, which carries no words or media of its own
    :return: The body, whether it is a forward, and whether the forwarded message was left out
    """
    body, forwarded = featured_body(message)
    if forwarded and not await forward_may_show(message, connection):
        return message, True, True
    return body, forwarded, False


async def fetch_reply_context(message: discord.Message, connection):
    """The message a featured message replies to, as reply_context finds it, without whether it was deleted"""
    reference_message, _deleted = await reply_context(message, connection)
    return reference_message


def linked_image_url(message: discord.Message) -> str | None:
    """The image of a link preview in a message, used by the embed posts when there are no attachments"""
    for message_embed in message.embeds:
        if message_embed.type == 'image' and message_embed.url:
            return message_embed.url
        # Sometimes images from links are in the thumbnail or image attribute of a generic embed type
        if message_embed.image:
            return message_embed.image.url
        if message_embed.thumbnail:
            return message_embed.thumbnail.url
    return None


def featured_body(message: discord.Message):
    """
    What a message shows: its own text and attachments, or for a forward, those of the message it forwards,
    which Discord keeps in a snapshot. The safety rules read this too, so a forward is judged by what it shows
    :return: The message or its snapshot, and whether it is a forward
    """
    snapshots = getattr(message, "message_snapshots", None) or []
    if snapshots and not message.content and not message.attachments:
        return snapshots[0], True
    return message, False


def content_scan_flags(message) -> int:
    """
    The content scanning flags Discord set on any of a message's attachments and embeds, combined. Scanning
    can finish after a message is sent, so a message fetched later can carry flags it did not have at first
    :param message: The message to look at
    :return: The EXPLICIT_CONTENT, GORE_CONTENT and SELF_HARM_CONTENT bits that are set
    """
    flags = 0
    for item in [*(getattr(message, "attachments", None) or []), *(getattr(message, "embeds", None) or [])]:
        item_flags = getattr(item, "flags", None)
        if item_flags is not None:
            flags |= item_flags.value
    return flags & (EXPLICIT_CONTENT | GORE_CONTENT | SELF_HARM_CONTENT)


def is_components_v2(post) -> bool:
    """Whether a board post was sent as a Components V2 message rather than an embed"""
    return bool(getattr(getattr(post, "flags", None), "components_v2", False))


def walk_components(components):
    """Every component of a message, nested ones and section accessories included"""
    for component in components or []:
        yield component
        yield from walk_components(getattr(component, "children", None))
        accessory = getattr(component, "accessory", None)
        if accessory is not None:
            yield accessory


def post_shows(post) -> bool:
    """
    Whether a board post shows its message: an embed post with its embed, or a Components V2 post with
    its container. A hidden post keeps neither, so it can be restored in place
    """
    if getattr(post, "embeds", None):
        return True
    return any(getattr(component, "type", None) == discord.ComponentType.container
               for component in getattr(post, "components", None) or [])


def posted_reactions_line(post) -> str | None:
    """The reactions line a Components V2 post shows now, None when it has none"""
    for component in walk_components(getattr(post, "components", None)):
        if getattr(component, "id", None) == POST_REACTIONS_ID:
            return getattr(component, "content", None)
    return None


def attachment_is_spoiler(attachment) -> bool:
    is_spoiler = getattr(attachment, "is_spoiler", None)
    return bool(is_spoiler()) if callable(is_spoiler) else False


def has_extension(url: str, extensions) -> bool:
    return (url or "").split("?")[0].lower().endswith(extensions)


def is_media_attachment(attachment) -> bool:
    """Whether an attachment is an image or a video a media gallery can show"""
    content_type = getattr(attachment, "content_type", None) or ""
    return content_type.startswith(("image/", "video/")) or has_extension(attachment.url, MEDIA_EXTENSIONS)


def is_video_attachment(attachment) -> bool:
    content_type = getattr(attachment, "content_type", None) or ""
    return content_type.startswith("video/") or has_extension(attachment.url, VIDEO_EXTENSIONS)


def is_audio_attachment(attachment) -> bool:
    content_type = getattr(attachment, "content_type", None) or ""
    return content_type.startswith("audio/") or has_extension(attachment.url, AUDIO_EXTENSIONS)


def is_voice_message(source) -> bool:
    return bool(getattr(getattr(source, "flags", None), "voice", False))


def ascii_url(url: str) -> str:
    """
    A link with characters outside ASCII percent-encoded. Discord keeps a file's name as written in its link,
    such as ødelagt.mp4, and a media item with such a link fails to load in a post. Characters a link may
    already hold, the % of an existing encoding included, are left as they are
    """
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def media_items(attachments) -> list[discord.MediaGalleryItem]:
    return [discord.MediaGalleryItem(ascii_url(attachment.url), spoiler=attachment_is_spoiler(attachment))
            for attachment in attachments if is_media_attachment(attachment)]


def gif_url(video_url: str) -> str:
    """
    A GIF preview's animation as a GIF. Discord gives the GIF picker's previews as an MP4, which a gallery
    shows as a video player with controls. Tenor serves the same animation as a GIF, at a link that differs
    only in its format code, so that is used for Tenor. Others keep the MP4, which at least plays
    """
    match = TENOR_MP4.match(video_url)
    if match is None:
        return video_url
    return f"{match.group(1)}AAAAC/{match.group(2)}.gif"


def preview_media(source):
    """
    Every picture, GIF and playable video among a message's link previews, in order and without repeats. A
    link may preview as several embeds, such as a post with four images, and a message may hold several links
    :return: The links, and the type of each preview they come from
    """
    links, kinds = [], []
    for message_embed in source.embeds:
        video_url = getattr(getattr(message_embed, "video", None), "url", None)
        image_url = getattr(getattr(message_embed, "image", None), "url", None)
        thumbnail_url = getattr(getattr(message_embed, "thumbnail", None), "url", None)
        kind = message_embed.type
        if kind == "gifv" and video_url:
            link = gif_url(video_url)
        elif kind == "image" and message_embed.url:
            link = message_embed.url
        elif has_extension(video_url, VIDEO_EXTENSIONS):
            # A link straight to a video file plays. A YouTube preview's video is a page, so its picture is used
            link, kind = video_url, "video_file"
        else:
            link = image_url or thumbnail_url
        if link and link not in links:
            links.append(link)
            kinds.append(kind)
    return links, kinds


def message_media(source):
    """
    The pictures and videos a message shows: its attachments, its stickers and its link previews, as Discord
    shows all of them together
    :return: The gallery items, the names of stickers no gallery can show, and whether the link previews stand
        in for the message's text, as Discord shows them when the link is the whole message
    """
    items = media_items(source.attachments)
    unshown_stickers = []
    for sticker in getattr(source, "stickers", None) or []:
        # Animated Lottie stickers are JSON, which a gallery cannot show, so they are named instead
        if getattr(sticker, "format", None) == discord.StickerFormatType.lottie:
            unshown_stickers.append(discord.utils.escape_markdown(sticker.name))
        else:
            items.append(discord.MediaGalleryItem(ascii_url(sticker.url)))
    links, kinds = preview_media(source)
    items.extend(discord.MediaGalleryItem(ascii_url(link)) for link in links)
    link_replaces_text = bool(links) and all(kind in PREVIEWS_REPLACING_LINK for kind in kinds) \
        and bool(BARE_LINK.match((source.content or "").strip()))
    return items, unshown_stickers, link_replaces_text


def quote_placeholder(source, poll) -> str:
    """What a replied-to message holds when it has no words to quote, named as Discord's reply preview does"""
    if poll is not None:
        return messages.POST_QUOTE_POLL.format(question=discord.utils.escape_markdown(poll.question))
    for attachment in source.attachments:
        if is_media_attachment(attachment):
            return messages.POST_QUOTE_VIDEO if is_video_attachment(attachment) else messages.POST_QUOTE_IMAGE
        if is_voice_message(source):
            return messages.POST_VOICE_MESSAGE
        return messages.POST_QUOTE_FILE.format(name=discord.utils.escape_markdown(attachment.filename))
    if getattr(source, "stickers", None):
        return messages.POST_STICKER.format(name=discord.utils.escape_markdown(source.stickers[0].name))
    links, kinds = preview_media(source)
    if links:
        return {"gifv": messages.POST_QUOTE_GIF, "video": messages.POST_QUOTE_VIDEO,
                "video_file": messages.POST_QUOTE_VIDEO}.get(kinds[0], messages.POST_QUOTE_IMAGE)
    return ""


def poll_answer_label(answer) -> str:
    """An answer as members see it: its emoji, its text or both, as an answer may be only an emoji"""
    emoji = getattr(answer, "emoji", None)
    parts = [str(emoji) if emoji else "", discord.utils.escape_markdown(answer.text or "")]
    return " ".join(part for part in parts if part)


def poll_text(poll) -> str:
    """A poll's question and answers with their votes, since a post cannot carry the poll itself"""
    lines = ["-# " + messages.POST_POLL, f"**{discord.utils.escape_markdown(poll.question)}**"]
    for answer in poll.answers:
        votes = messages.POST_POLL_VOTE if answer.vote_count == 1 else messages.POST_POLL_VOTES
        lines.append(f"- {poll_answer_label(answer)} · " + votes.format(count=answer.vote_count))
    return "\n".join(lines)


def more_note(hidden: int) -> str:
    return "-# " + messages.POST_MORE_IN_ORIGINAL.format(count=hidden)


def file_lines(source, budget: int) -> list[str]:
    """
    Links to the files a post cannot show, as many as fit the text left over, then a note for the rest, so a
    message with long file names cannot push a post past Discord's limit
    :param source: The message whose files are linked
    :param budget: The characters of text left for the list
    """
    files = [attachment for attachment in source.attachments if not is_media_attachment(attachment)]
    lines = []
    for attachment in files[:post_files_listed]:
        name = messages.POST_VOICE_MESSAGE if is_voice_message(source) and is_audio_attachment(attachment) \
            else discord.utils.escape_markdown(attachment.filename)
        line = f"[{name}]({ascii_url(attachment.url)})"
        # Room is kept for the note that counts what did not fit
        if sum(len(kept) + 1 for kept in lines) + len(line) + len(more_note(len(files))) + 1 > budget:
            break
        lines.append(line)
    if len(lines) < len(files):
        lines.append(more_note(len(files) - len(lines)))
    return lines


def display_name(user) -> str:
    """The name members see for someone in the server, their nickname when they have one"""
    return discord.utils.escape_markdown(getattr(user, "display_name", None) or user.name)


def reactions_line(message: discord.Message, config: dict, counted: int) -> str:
    """
    Every counted emoji with its count, most used first. How many the server's counting method counted is
    added only when it differs from the top emoji's count, for example with total reactions or when the
    author's own reaction is left out, so the usual post does not show the same number twice
    """
    reactions = sorted(filter_whitelisted_reactions(message.reactions, config), key=lambda reaction: reaction.count,
                       reverse=True)
    listed = " · ".join(f"{reaction.emoji} {reaction.count}" for reaction in reactions[:post_reactions_listed])
    if len(reactions) > post_reactions_listed:
        listed += " · " + messages.POST_MORE_EMOJIS.format(count=len(reactions) - post_reactions_listed)
    if reactions and reactions[0].count == counted:
        return listed
    footer = "-# " + messages.POST_COUNTED.format(count=counted)
    return f"{listed}\n{footer}" if listed else footer


async def create_post_view(message: discord.Message, connection, config: dict = None,
                           corrected_reactions: int = None) -> discord.ui.LayoutView:
    """
    A Hall of Fame post as a Components V2 message: the author with the reply they answered, the text, every
    image and video, the counted emojis and a button back to the message
    :param message: The featured message
    :param connection: The database connection
    :param config: The reaction related server configuration, fetched when not supplied
    :param corrected_reactions: The already calculated reaction count, recalculated when not supplied
    :return: The view to send or edit the post with
    """
    config = config if config is not None else server_config_repo.get_reaction_config(connection, message.guild.id)
    reference_message, reply_deleted = await reply_context(message, connection)
    if corrected_reactions is None:
        corrected_reactions = await reaction_count(message, connection, config)
    body, forwarded, forward_left_out = await shown_body(message, connection)
    media, unshown_stickers, link_replaces_text = message_media(body)
    sticker_note = "-# " + messages.POST_STICKER.format(name=", ".join(unshown_stickers)) if unshown_stickers else None

    # The message it answers goes through the same steps, a forward and a sticker included. A reply without
    # pictures of its own shows those of the message it answers, between the two as in Discord's own reply
    # view, or they would look like the reply's
    reference_media, quote = [], ""
    if reference_message is not None:
        reference_body, _, _ = await shown_body(reference_message, connection)
        answered_media, _, link_replaces_quote = message_media(reference_body)
        # Its media is only checked here, never for posting, so media Discord flagged is named, never shown
        if not media and not content_scan_flags(reference_body):
            reference_media = answered_media
        quote = "" if link_replaces_quote else truncate_content(reference_body.content, post_quote_limit)
        if not quote and not reference_media:
            # Nothing to quote and no picture shown: name what it was, as Discord's reply preview does
            placeholder = quote_placeholder(reference_body, getattr(reference_message, "poll", None))
            quote = f"*{placeholder}*" if placeholder else ""

    text = "" if link_replaces_text else truncate_content(body.content, post_text_limit)
    # Read from what the post shows, like the text and media. discord.py's snapshot of a forward carries no
    # poll, so a forwarded poll has none to show
    poll = getattr(body, "poll", None)
    if poll is not None:
        # Under the words when the message has both, so neither is lost. Counted in the text budget below
        text = f"{text}\n\n{poll_text(poll)}" if text else poll_text(poll)
    if forward_left_out:
        text = f"*{messages.POST_FORWARD_NOT_SHOWN}*"
    # A sticker no gallery can show is named where the words go when there are none, so it is seen
    if not text and sticker_note:
        text, sticker_note = f"*{messages.POST_STICKER.format(name=', '.join(unshown_stickers))}*", None

    # A reply comes first, as in Discord's own reply view: who and what was answered, then the poster's name
    # above their own words, so every piece of text sits under the name of whoever wrote it
    reply_block = None
    if reference_message is not None:
        replying = "-# " + messages.POST_REPLYING_TO.format(name=display_name(reference_message.author))
        reply_block = f"{replying}\n>>> {quote}" if quote else replying
    elif reply_deleted:
        reply_block = "-# " + messages.POST_REPLYING_TO_DELETED

    # Beside the avatar: the poster's name and where it was said, then text short enough for the narrow column
    where = messages.POST_IN_CHANNEL.format(channel=message.channel.mention)
    if forwarded:
        where += " · " + messages.POST_FORWARDED
    heading = [f"**{display_name(message.author)}**\n-# {where}"]
    text_beside = bool(text) and len(text) <= post_text_beside_limit
    if text_beside:
        heading.append(text)

    overflow = more_note(len(media) - post_media_limit) if len(media) > post_media_limit else None
    reference_overflow = (more_note(len(reference_media) - post_media_limit)
                          if len(reference_media) > post_media_limit else None)
    reactions = reactions_line(message, config, corrected_reactions)
    # Everything but the file links, which take what is left of Discord's limit on a message's text
    text_used = sum(len(part) for part in (reply_block or "", *heading, text if not text_beside else "",
                                           overflow or "", reference_overflow or "", sticker_note or "", reactions))
    files = file_lines(body, post_text_budget - text_used)

    container = discord.ui.Container(accent_colour=discord.Colour.gold())
    if reply_block:
        container.add_item(discord.ui.TextDisplay(reply_block))
        if reference_media:
            container.add_item(discord.ui.MediaGallery(*reference_media[:post_media_limit]))
            if reference_overflow:
                container.add_item(discord.ui.TextDisplay(reference_overflow))
        # Space between the message answered and the answer, so the two read as two people
        container.add_item(discord.ui.Separator(visible=False))
    if len(heading) > 1:
        container.add_item(discord.ui.Section(*heading, accessory=discord.ui.Thumbnail(message.author.display_avatar.url)))
    else:
        # A lone name beside the tall avatar left a gap above the picture, so without text it stands alone
        container.add_item(discord.ui.TextDisplay(heading[0]))
    if text and not text_beside:
        container.add_item(discord.ui.TextDisplay(text))
    if media:
        container.add_item(discord.ui.MediaGallery(*media[:post_media_limit]))
        if overflow:
            container.add_item(discord.ui.TextDisplay(overflow))
    if sticker_note:
        container.add_item(discord.ui.TextDisplay(sticker_note))
    if files:
        container.add_item(discord.ui.TextDisplay("\n".join(files)))

    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay(reactions, id=POST_REACTIONS_ID))
    container.add_item(discord.ui.ActionRow(discord.ui.Button(style=discord.ButtonStyle.link, label=messages.POST_JUMP,
                                                              url=message.jump_url)))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


def hidden_post_view() -> discord.ui.LayoutView:
    """What a hidden Components V2 post shows. A message keeps its Components V2 flag, so it is blanked this way"""
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.TextDisplay("** **"))
    return view
