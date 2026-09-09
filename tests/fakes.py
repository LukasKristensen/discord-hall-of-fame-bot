"""Minimal stand-ins for the Discord and database objects used by the bot."""


class FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id


class FakeGuild:
    def __init__(self, guild_id: int):
        self.id = guild_id


class FakeReaction:
    """A reaction with a fixed set of users, mirroring discord.Reaction."""

    def __init__(self, emoji, user_ids):
        self.emoji = emoji
        self.user_ids = list(user_ids)
        self.count = len(self.user_ids)

    async def users(self):
        for user_id in self.user_ids:
            yield FakeUser(user_id)


class FakeMessage:
    def __init__(self, author_id: int, reactions=None, guild_id: int = 1, attachments=None, content: str = ""):
        self.author = FakeUser(author_id)
        self.reactions = reactions if reactions is not None else []
        self.guild = FakeGuild(guild_id)
        self.attachments = attachments if attachments is not None else []
        self.content = content


class FakeAttachment:
    def __init__(self, url: str, content_type: str = None):
        self.url = url
        self.content_type = content_type


class FakeCursor:
    def __init__(self, row, rows=None):
        self.row = row
        self.rows = rows if rows is not None else []
        self.executed = []
        self.rowcount = 0

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    """Connection that hands out cursors returning a single canned row."""

    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows
        self.cursors = []

    def cursor(self):
        cursor = FakeCursor(self.row, self.rows)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        pass

    @property
    def queries(self):
        return [query for cursor in self.cursors for query, _ in cursor.executed]


class FakeLogChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


class FakeLogGuild:
    def __init__(self, channels=None):
        self.channels = channels if channels is not None else {}

    def get_channel(self, channel_id):
        return self.channels.setdefault(channel_id, FakeLogChannel())


class FakeBot:
    """Just enough of a client for the logging helper: a support guild and an identity."""

    PRODUCTION_APPLICATION_ID = 1177041673352663070

    def __init__(self, guild=None, application_id=PRODUCTION_APPLICATION_ID, user_id=1):
        self.application_id = application_id
        self.guild = guild if guild is not None else FakeLogGuild()
        self.user = FakeUser(user_id)

    def get_guild(self, guild_id):
        return self.guild


class FakeBotWithGuilds(FakeBot):
    """A bot that also reports the guilds it is in, for the daily maintenance tasks."""

    def __init__(self, guild_ids, **kwargs):
        super().__init__(**kwargs)
        self.guilds = [FakeGuild(guild_id) for guild_id in guild_ids]


class FakePermissions:
    def __init__(self, manage_messages=True, send_messages=True, view_channel=True,
                 read_message_history=True, read_messages=True):
        self.manage_messages = manage_messages
        self.send_messages = send_messages
        self.view_channel = view_channel
        self.read_message_history = read_message_history
        self.read_messages = read_messages


class FakeSentMessage:
    def __init__(self, content):
        self.content = content
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeTextChannel:
    """A channel that reports a fixed permission set for the bot."""

    def __init__(self, channel_id=100, permissions=None):
        self.id = channel_id
        self.permissions = permissions if permissions is not None else FakePermissions()
        self.sent = []

    def permissions_for(self, _member):
        return self.permissions

    async def send(self, content):
        sent = FakeSentMessage(content)
        self.sent.append(sent)
        return sent


class FakeMemberGuild:
    """A guild that can report its own bot member, for permission checks."""

    def __init__(self, guild_id=200, name="Test Server"):
        self.id = guild_id
        self.name = name
        self.me = FakeUser(1)


class FakeChannelMessage:
    def __init__(self, channel, guild, author_is_bot=False, author_id=5):
        self.channel = channel
        self.guild = guild
        self.author = FakeUser(author_id)
        self.author.bot = author_is_bot
        self.author.mention = f"<@{author_id}>"
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeGuildWithChannels(FakeMemberGuild):
    """A guild that can hand back its channels, for the daily permission sweep."""

    def __init__(self, guild_id=200, name="Test Server", channels=None):
        super().__init__(guild_id=guild_id, name=name)
        self.channels = channels if channels is not None else {}

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


class FakeBotWithGuildLookup:
    def __init__(self, guilds_by_id=None):
        self.guilds_by_id = guilds_by_id if guilds_by_id is not None else {}
        self.guilds = list(self.guilds_by_id.values())
        self.user = FakeUser(1)

    def get_guild(self, guild_id):
        return self.guilds_by_id.get(guild_id)
