"""A small faked Discord for the database tests: channels, messages with reactions, and a board.

The database underneath is real; only what the bot would ask Discord is faked, and only as much of it
as the code paths under test touch.
"""

import datetime
import types

import discord

from tests.fakes import FakePermissions, FakeReaction


class Author:
    def __init__(self, user_id, bot=False, manage_guild=False):
        self.id = user_id
        self.bot = bot
        self.name = f"member-{user_id}"
        self.global_name = None
        self.mention = f"<@{user_id}>"
        self.avatar = None
        self.display_avatar = types.SimpleNamespace(url=f"https://cdn.example/avatars/{user_id}.png")
        # What a slash command reads to decide whether the member may change the server's settings
        self.guild_permissions = types.SimpleNamespace(manage_guild=manage_guild)


def not_found(what="Unknown Message"):
    return discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), what)


class Guild:
    def __init__(self, guild_id, name="Server", member_count=50, manage_channels=True):
        self.id = guild_id
        self.name = name
        self.member_count = member_count
        # Every server permission the join log reads, granted unless the test takes manage_channels away
        self.me = types.SimpleNamespace(id=1, guild_permissions=FakePermissions(manage_channels=manage_channels),
                                        joined_at=datetime.datetime.now(datetime.timezone.utc))
        self.default_role = types.SimpleNamespace(id=guild_id)
        # By ID for get_channel. Discord's guild.channels is a list, which the setup check walks
        self.channels_by_id = {}
        self.created_channels = []
        # Where the bot would post a notice when setting the server up fails; none unless a test adds one
        self.text_channels = []
        # Members fetch_member finds, for the leaderboard's names
        self.members = {}
        self.features = []
        self.icon = None
        self.filesize_limit = 10 * 1024 * 1024

    @property
    def channels(self):
        return list(self.channels_by_id.values())

    def get_channel(self, channel_id):
        return self.channels_by_id.get(channel_id)

    async def fetch_member(self, user_id):
        if user_id not in self.members:
            raise not_found("Unknown Member")
        return self.members[user_id]

    async def create_text_channel(self, name):
        channel = Board(9_000_000 + self.id, self, name=name)
        self.created_channels.append(channel)
        self.channels_by_id[channel.id] = channel
        return channel


class Message:
    def __init__(self, message_id, channel, author, reactions=(), created_at=None, attachments=()):
        self.id = message_id
        self.channel = channel
        self.guild = channel.guild
        self.author = author
        self.content = f"message {message_id}"
        self.reactions = list(reactions)
        self.attachments = list(attachments)
        self.embeds = []
        self.stickers = []
        self.reference = None
        self.created_at = created_at or datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        self.jump_url = f"https://discord.com/channels/{channel.guild.id}/{channel.id}/{message_id}"

    def react(self, emoji, *user_ids):
        """Add reactions of one emoji from the given members, merging with any already there"""
        for reaction in self.reactions:
            if reaction.emoji == emoji:
                reaction.user_ids.extend(user_ids)
                reaction.count = len(reaction.user_ids)
                return
        self.reactions.append(FakeReaction(emoji, user_ids))

    def unreact(self, emoji, *user_ids):
        for reaction in self.reactions:
            if reaction.emoji == emoji:
                reaction.user_ids = [user for user in reaction.user_ids if user not in user_ids]
                reaction.count = len(reaction.user_ids)
        self.reactions = [reaction for reaction in self.reactions if reaction.count]


class SourceChannel(discord.TextChannel):
    """A text channel members post in. A real TextChannel subclass, as Wrapped checks the type"""

    def __init__(self, channel_id, guild, readable=True, nsfw=False):
        self.id = channel_id
        self.guild = guild
        self.name = f"channel-{channel_id}"
        self.messages = {}
        self.readable = readable
        # Read by the setup check, which only looks at channels members can react in
        self._type = discord.ChannelType.text.value
        # What TextChannel.is_nsfw and TextChannel.flags read: whether the channel is age-restricted, and
        # the channel flags, which carry whether Discord hid the channel from the bot
        self.nsfw = nsfw
        self._flags = 0
        guild.channels_by_id[channel_id] = self

    def permissions_for(self, _member):
        return types.SimpleNamespace(read_messages=self.readable, view_channel=self.readable,
                                     read_message_history=self.readable)

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise not_found()
        return self.messages[message_id]

    def add(self, message_id, author, created_at=None, attachments=()):
        message = Message(message_id, self, author, created_at=created_at, attachments=attachments)
        self.messages[message_id] = message
        return message

    def delete(self, message_id):
        """The author or a moderator deletes the message: fetching it from now on finds nothing"""
        self.messages.pop(message_id, None)


class Post:
    """A message the bot sent to the board, as an embed or as a Components V2 view"""

    def __init__(self, message_id, content=None, embed=None, view=None):
        self.id = message_id
        self.content = content or ""
        self.embeds = [embed] if embed is not None else []
        # A message keeps the Components V2 flag it was sent with, and shows its view's components. Only a
        # LayoutView sets the flag: buttons under a plain message, such as the welcome message, do not
        self.flags = types.SimpleNamespace(components_v2=isinstance(view, discord.ui.LayoutView))
        self.view = view
        # The bot wrote it, which is how the edit handler tells its own posts from members' messages
        self.author = types.SimpleNamespace(id=1, bot=True)
        self.components = list(view.children) if view is not None else []
        self.edits = []
        self.deleted = False
        self.created_at = datetime.datetime.now(datetime.timezone.utc)

    async def edit(self, content=None, embed=..., view=..., **_kwargs):
        self.edits.append({"content": content, "embed": embed, "view": view})
        if content is not None:
            self.content = content
        if embed is not ...:
            self.embeds = [embed] if embed is not None else []
        if view is not ...:
            self.components = list(view.children) if view is not None else []

    async def delete(self):
        self.deleted = True


class Board:
    """
    The Hall of Fame channel: what the bot sends there is kept, and can be fetched back. Also stands in
    for any other text channel the bot posts a notice in
    """

    type = discord.ChannelType.text

    def __init__(self, channel_id, guild, name="hall-of-fame", position=0):
        self.id = channel_id
        self.guild = guild
        self.name = name
        self.position = position
        # Names of the permissions taken away from the bot here, such as "send_messages"
        self.missing_permissions = set()
        self.topic = None
        self.mention = f"<#{channel_id}>"
        self.posts = {}
        self.sent = []
        self.next_id = 700_000 + channel_id % 1000 * 1000
        # Whether the board is age-restricted, which decides what may be posted to it
        self.nsfw = False
        guild.channels_by_id[channel_id] = self

    def is_nsfw(self):
        return self.nsfw

    async def send(self, content=None, embed=None, view=None, **kwargs):
        if "send_messages" in self.missing_permissions or "view_channel" in self.missing_permissions:
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        self.next_id += 1
        post = Post(self.next_id, content, embed, view)
        # Whom the message may ping, None when the bot left Discord's default of pinging everyone named
        post.allowed_mentions = kwargs.get("allowed_mentions")
        post.files = list(kwargs.get("files") or [])
        self.posts[post.id] = post
        self.sent.append(post)
        return post

    async def fetch_message(self, message_id):
        post = self.posts.get(message_id)
        # A post somebody deleted is gone for the bot too, as Discord answers Unknown Message
        if post is None or post.deleted:
            raise not_found()
        return post

    async def edit(self, topic=None, **_kwargs):
        self.topic = topic

    async def set_permissions(self, *_args, **_kwargs):
        pass

    def permissions_for(self, _member):
        granted = dict(read_messages=True, view_channel=True, send_messages=True, read_message_history=True,
                       embed_links=True, attach_files=True, manage_channels=True, manage_messages=True)
        granted.update({name: False for name in self.missing_permissions})
        return types.SimpleNamespace(**granted)


class Search:
    """
    The REST calls the bot makes itself, of which only Discord's message search is used: it counts a
    member's messages for the Wrapped fame rate. messages_sent gives the count per member, 100 otherwise
    """

    def __init__(self):
        self.messages_sent = {}
        self.asked = []

    async def request(self, route, params=None, **_kwargs):
        self.asked.append((route.path, params))
        return {"total_results": self.messages_sent.get(params["author_id"], 100), "messages": []}


class Bot:
    def __init__(self, *guilds):
        self.guilds = list(guilds)
        self.user = types.SimpleNamespace(id=1)
        self.http = Search()

    def get_channel(self, channel_id):
        for guild in self.guilds:
            channel = guild.get_channel(channel_id)
            if channel is not None:
                return channel
        return None

    def get_guild(self, guild_id):
        return next((guild for guild in self.guilds if guild.id == guild_id), None)

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    async def fetch_guild(self, guild_id):
        """Asked by the daily task before it deletes a server that went missing"""
        guild = self.get_guild(guild_id)
        if guild is None:
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")
        return guild


def reaction_event(message):
    return types.SimpleNamespace(channel_id=message.channel.id, message_id=message.id, guild_id=message.guild.id)


async def post_embed(*_args, **_kwargs):
    """Stands in for the bot's embed builder, which is layout rather than data: one Reactions field"""
    embed = discord.Embed(description="post")
    embed.add_field(name="Reactions", value="0")
    return embed


def reaction_payload(message, member):
    """
    What Discord sends when somebody adds or removes a reaction, as main's handlers take it. The member is
    only filled in for an added reaction in a server, and is how the bot skips other bots' reactions
    """
    return types.SimpleNamespace(channel_id=message.channel.id, message_id=message.id, guild_id=message.guild.id,
                                 user_id=member.id, member=member)


def post_text(post):
    """Everything a board post shows as text, an embed's description and fields or a Components V2 post's text"""
    from board_post import walk_components
    parts = [post.content or ""]
    for embed in post.embeds:
        parts += [embed.description or ""] + [f"{field.name} {field.value}" for field in embed.fields]
    for component in walk_components(post.components):
        content = getattr(component, "content", None)
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(part for part in parts if part)


class Reply:
    """One answer to an interaction, as the member sees it"""

    def __init__(self, content=None, embed=None, view=None, ephemeral=False, files=()):
        self.content = content
        self.embed = embed
        self.view = view
        self.ephemeral = ephemeral
        self.files = list(files)

    def text(self):
        """The answer's content and its embed's text, for asserting on what the member reads"""
        parts = [self.content or ""]
        if self.embed is not None:
            parts += [self.embed.title or "", self.embed.description or ""]
            parts += [f"{field.name}\n{field.value}" for field in self.embed.fields]
        return "\n".join(part for part in parts if part)


class Interaction:
    """
    A slash command, button press or form being answered. Every answer lands in replies, in order, with
    whether only the member sees it. After a defer the first followup replaces the "thinking..." message and
    takes its privacy, as on Discord, unless the bot deleted that message first
    """

    def __init__(self, user, guild=None, channel_id=555, app_permissions=None):
        self.user = user
        self.guild = guild
        self.guild_id = guild.id if guild is not None else None
        self.channel_id = channel_id
        self.app_permissions = app_permissions
        self.command = types.SimpleNamespace(name="journey")
        self.replies = []
        self.edits = []
        self.modal = None
        self.deferred = None
        self.thinking_message_open = False
        interaction = self

        class Response:
            async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False, files=None,
                                   file=None, **_kwargs):
                interaction._answer(content, embed, view, ephemeral, (files or []) + ([file] if file else []))

            async def defer(self, ephemeral=False, thinking=False):
                interaction.deferred = types.SimpleNamespace(ephemeral=ephemeral, thinking=thinking)
                interaction.thinking_message_open = True

            async def send_modal(self, modal):
                interaction.modal = modal

            async def edit_message(self, content=None, view=None, **_kwargs):
                interaction.edits.append(types.SimpleNamespace(content=content, view=view))

            def is_done(self):
                return bool(interaction.replies or interaction.deferred or interaction.modal or interaction.edits)

        class Followup:
            async def send(self, content=None, *, embed=None, view=None, ephemeral=False, files=None, file=None,
                           **_kwargs):
                if interaction.thinking_message_open:
                    # Replaces the deferred message, so it keeps that message's privacy
                    ephemeral = interaction.deferred.ephemeral
                    interaction.thinking_message_open = False
                interaction._answer(content, embed, view, ephemeral, (files or []) + ([file] if file else []))

        self.response = Response()
        self.followup = Followup()

    def _answer(self, content, embed, view, ephemeral, files):
        self.replies.append(Reply(content, embed, view, ephemeral, files))

    async def edit_original_response(self, content=None, view=..., **_kwargs):
        self.edits.append(types.SimpleNamespace(content=content, view=None if view is ... else view))

    async def original_response(self):
        flags = types.SimpleNamespace(loading=self.thinking_message_open,
                                      ephemeral=bool(self.deferred and self.deferred.ephemeral))
        return types.SimpleNamespace(flags=flags)

    async def delete_original_response(self):
        self.thinking_message_open = False

    def is_guild_integration(self):
        return self.guild is not None

    @property
    def last(self) -> Reply:
        return self.replies[-1]

    def text(self) -> str:
        """Everything the member was answered, edits included"""
        return "\n".join([reply.text() for reply in self.replies] + [edit.content or "" for edit in self.edits])


def attachment(filename="picture.png", content_type="image/png", flags=0):
    """A file on a message. flags carries Discord's content scanning results, such as utils.GORE_CONTENT"""
    url = f"https://cdn.example/attachments/{filename}"
    return types.SimpleNamespace(url=url, proxy_url=url, filename=filename, content_type=content_type,
                                 description=None, is_spoiler=lambda: False, size=1000, width=100, height=100,
                                 duration=None, flags=discord.AttachmentFlags._from_value(flags))
