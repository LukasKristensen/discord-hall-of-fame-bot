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
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.row

    def close(self):
        pass


class FakeConnection:
    """Connection that hands out cursors returning a single canned row."""

    def __init__(self, row=None):
        self.row = row
        self.cursors = []

    def cursor(self):
        cursor = FakeCursor(self.row)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        pass

    @property
    def queries(self):
        return [query for cursor in self.cursors for query, _ in cursor.executed]
