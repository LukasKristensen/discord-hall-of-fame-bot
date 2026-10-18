"""A small faked Discord for the database tests: channels, messages with reactions, and a board.

The database underneath is real; only what the bot would ask Discord is faked, and only as much of it
as the code paths under test touch.
"""

import datetime
import types

import discord

from tests.fakes import FakeReaction


class Author:
    def __init__(self, user_id, bot=False):
        self.id = user_id
        self.bot = bot
        self.name = f"member-{user_id}"
        self.mention = f"<@{user_id}>"


class Guild:
    def __init__(self, guild_id, name="Server", member_count=50, manage_channels=True):
        self.id = guild_id
        self.name = name
        self.member_count = member_count
        self.me = types.SimpleNamespace(id=1, guild_permissions=types.SimpleNamespace(manage_channels=manage_channels))
        self.default_role = types.SimpleNamespace(id=guild_id)
        self.channels = {}
        self.created_channels = []
        # Where the bot would post a notice when setting the server up fails; none in these tests
        self.text_channels = []

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def create_text_channel(self, name):
        channel = Board(9_000_000 + self.id, self, name=name)
        self.created_channels.append(channel)
        self.channels[channel.id] = channel
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

    def __init__(self, channel_id, guild, readable=True):
        self.id = channel_id
        self.guild = guild
        self.name = f"channel-{channel_id}"
        self.messages = {}
        self.readable = readable
        guild.channels[channel_id] = self

    def permissions_for(self, _member):
        return types.SimpleNamespace(read_messages=self.readable, view_channel=self.readable)

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.messages[message_id]

    def add(self, message_id, author, created_at=None, attachments=()):
        message = Message(message_id, self, author, created_at=created_at, attachments=attachments)
        self.messages[message_id] = message
        return message


class Post:
    """A message the bot sent to the board"""

    def __init__(self, message_id, content=None, embed=None):
        self.id = message_id
        self.content = content or ""
        self.embeds = [embed] if embed is not None else []
        self.edits = []
        self.deleted = False

    async def edit(self, content=None, embed=..., **_kwargs):
        self.edits.append({"content": content, "embed": embed})
        if content is not None:
            self.content = content
        if embed is not ...:
            self.embeds = [embed] if embed is not None else []

    async def delete(self):
        self.deleted = True


class Board:
    """
    The Hall of Fame channel: what the bot sends there is kept, and can be fetched back. Also stands in
    for any other text channel the bot posts a notice in
    """

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
        guild.channels[channel_id] = self

    async def send(self, content=None, embed=None, **_kwargs):
        self.next_id += 1
        post = Post(self.next_id, content, embed)
        self.posts[post.id] = post
        self.sent.append(post)
        return post

    async def fetch_message(self, message_id):
        return self.posts[message_id]

    async def edit(self, topic=None, **_kwargs):
        self.topic = topic

    async def set_permissions(self, *_args, **_kwargs):
        pass

    def permissions_for(self, _member):
        granted = dict(read_messages=True, view_channel=True, send_messages=True, read_message_history=True,
                       embed_links=True, manage_channels=True)
        granted.update({name: False for name in self.missing_permissions})
        return types.SimpleNamespace(**granted)


class Bot:
    def __init__(self, *guilds):
        self.guilds = list(guilds)
        self.user = types.SimpleNamespace(id=1)

    def get_channel(self, channel_id):
        for guild in self.guilds:
            channel = guild.get_channel(channel_id)
            if channel is not None:
                return channel
        return None

    def get_guild(self, guild_id):
        return next((guild for guild in self.guilds if guild.id == guild_id), None)


def reaction_event(message):
    return types.SimpleNamespace(channel_id=message.channel.id, message_id=message.id, guild_id=message.guild.id)


async def post_embed(*_args, **_kwargs):
    """Stands in for the bot's embed builder, which is layout rather than data: one Reactions field"""
    embed = discord.Embed(description="post")
    embed.add_field(name="Reactions", value="0")
    return embed
