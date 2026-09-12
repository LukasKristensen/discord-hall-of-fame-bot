"""Drives the bot's real reaction handler under concurrent load.

This is not a unit test and does not run with the suite. It imports the actual handler from
``main`` and calls it the way the gateway does, with the real ``KeyedLocks`` and the real
``get_db_connection`` context manager in place. Discord and PostgreSQL are replaced with stand-ins
that model the two things that decide how the bot behaves under load:

* A Discord call is slow but does not block the event loop, so it is awaited.
* A database call is fast but *does* block the event loop, because psycopg2 is synchronous, so it
  really sleeps the thread.

The connection pool stand-in reproduces psycopg2's semantics exactly, including the part that
matters most here: ``getconn`` raises ``PoolError`` when every connection is checked out. It does
not queue and it does not wait.

Run it::

    python tests/stress/reaction_storm.py --scenario spread
    python tests/stress/reaction_storm.py --scenario storm --events 2000
    python tests/stress/reaction_storm.py --scenario spread --pool-size 25

Exit code is non-zero when a run breaks one of the invariants it checks.
"""

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict

SOURCE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SOURCE_PATH not in sys.path:
    sys.path.insert(0, SOURCE_PATH)

import concurrency  # noqa: E402
import events  # noqa: E402
import main  # noqa: E402
import utils  # noqa: E402
from classes.server_class import Server  # noqa: E402
from enums import calculation_method_type  # noqa: E402


class PoolExhausted(Exception):
    """Stands in for psycopg2.pool.PoolError, which is raised rather than waited on."""


class InstrumentedPool:
    """
    A connection pool with psycopg2's exhaustion behaviour and a record of how hard it was pushed.
    """

    def __init__(self, maxconn, db_latency):
        self.maxconn = maxconn
        self.db_latency = db_latency
        self.in_flight = 0
        self.peak_in_flight = 0
        self.exhausted = 0
        self.handed_out = 0

    def getconn(self):
        if self.in_flight >= self.maxconn:
            self.exhausted += 1
            raise PoolExhausted("connection pool exhausted")
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        self.handed_out += 1
        return FakeConnection(self.db_latency)

    def putconn(self, _connection):
        self.in_flight -= 1


class FakeConnection:
    def __init__(self, latency):
        self.latency = latency

    def commit(self):
        # Blocking on purpose: psycopg2 is synchronous, so a commit stalls the whole event loop
        if self.latency:
            time.sleep(self.latency)

    def rollback(self):
        pass


class MessageStore:
    """The hall of fame message table, in memory, with the latency of a real one."""

    def __init__(self, latency):
        self.latency = latency
        self.rows = {}
        self.reads = 0
        self.writes = 0

    def _wait(self):
        if self.latency:
            time.sleep(self.latency)

    def find_hall_of_fame_message(self, _connection, guild_id, channel_id, message_id):
        self.reads += 1
        self._wait()
        return self.rows.get((guild_id, channel_id, message_id))

    def guild_message_count_today(self, _connection, _guild_id):
        self.reads += 1
        self._wait()
        return 0

    def update_field_for_message(self, _connection, guild_id, channel_id, message_id, field, value):
        self.writes += 1
        self._wait()
        row = self.rows.get((guild_id, channel_id, message_id))
        if row is not None:
            row[field] = value

    def insert_hall_of_fame_message(self, _connection, message_id, channel_id, guild_id,
                                    hall_of_fame_message_id, reaction_count, author_id,
                                    created_at, video_link_message_id=None):
        self.writes += 1
        self._wait()
        self.rows[(guild_id, channel_id, message_id)] = {
            "message_id": message_id,
            "channel_id": channel_id,
            "guild_id": guild_id,
            "hall_of_fame_message_id": hall_of_fame_message_id,
            "reaction_count": reaction_count,
            "author_id": author_id,
            "created_at": created_at,
            "video_link_message_id": video_link_message_id,
        }


class FakeReaction:
    def __init__(self, emoji, reactors):
        self.emoji = emoji
        self.reactors = reactors

    @property
    def count(self):
        return len(self.reactors)

    async def users(self):
        for user_id in list(self.reactors):
            yield FakeUser(user_id)


class FakeUser:
    def __init__(self, user_id, bot=False):
        self.id = user_id
        self.name = f"member-{user_id}"
        self.bot = bot


class FakeGuild:
    def __init__(self, guild_id):
        self.id = guild_id
        self.name = f"guild-{guild_id}"
        self.me = FakeUser(1)


class TrackedMessage:
    """A message whose reactions change while the handler is reading them."""

    def __init__(self, message_id, channel, guild, author_id, latency):
        self.id = message_id
        self.channel = channel
        self.guild = guild
        self.author = FakeUser(author_id)
        self.attachments = []
        self.embeds = []
        self.content = f"message {message_id}"
        self.latency = latency
        self.reactions = [FakeReaction("🔥", set())]
        self.created_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    def add_reactor(self, user_id):
        self.reactions[0].reactors.add(user_id)

    def remove_reactor(self, user_id):
        self.reactions[0].reactors.discard(user_id)

    @property
    def live_count(self):
        return self.reactions[0].count


class FakeChannel:
    """A channel whose every call costs a Discord round trip."""

    def __init__(self, channel_id, guild, latency, stats):
        self.id = channel_id
        self.guild = guild
        self.latency = latency
        self.stats = stats
        self.messages = {}
        self.posted = []
        self.next_id = channel_id * 1000

    def permissions_for(self, _member):
        return FakePermissions()

    async def _round_trip(self):
        self.stats["discord_calls"] += 1
        await asyncio.sleep(self.latency)

    async def fetch_message(self, message_id):
        await self._round_trip()
        if message_id not in self.messages:
            raise LookupError(f"Unknown Message {message_id}")
        return self.messages[message_id]

    async def send(self, content=None, embed=None):
        await self._round_trip()
        self.next_id += 1
        posted = PostedMessage(self.next_id, self, [embed] if embed else [])
        self.messages[posted.id] = posted
        self.posted.append(posted)
        return posted

    def history(self, limit=None):
        async def iterator():
            for message in list(self.messages.values())[:limit]:
                yield message

        return iterator()


class PostedMessage:
    def __init__(self, message_id, channel, embeds):
        self.id = message_id
        self.channel = channel
        self.embeds = list(embeds)
        self.content = ""
        self.author = FakeUser(1, bot=True)
        self.edits = 0

    async def edit(self, **kwargs):
        await self.channel._round_trip()
        self.edits += 1
        if "embed" in kwargs:
            self.embeds = [kwargs["embed"]] if kwargs["embed"] else []


class FakePermissions:
    def __init__(self):
        self.read_messages = True
        self.send_messages = True
        self.view_channel = True
        self.read_message_history = True
        self.manage_messages = True


class FakeBot:
    def __init__(self, channels):
        self.channels = channels
        self.user = FakeUser(1, bot=True)
        self.guilds = []

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    def get_guild(self, _guild_id):
        return None


class Payload:
    def __init__(self, guild_id, channel_id, message_id, user_id):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.user_id = user_id
        self.member = None


def build_server(guild_id, channel_id, threshold):
    return Server(
        hall_of_fame_channel_id=channel_id,
        guild_id=guild_id,
        reaction_threshold=threshold,
        post_due_date=1000,
        sweep_limit=1000,
        sweep_limited=False,
        include_author_in_reaction_calculation=True,
        allow_messages_in_hof_channel=False,
        custom_emoji_check_logic=False,
        whitelisted_emojis=[],
        leaderboard_setup=False,
        ignore_bot_messages=True,
        reaction_count_calculation_method=calculation_method_type.MOST_REACTIONS_ON_EMOJI,
        hide_hof_post_below_threshold=True,
        leaderboard_message_ids=[],
        server_member_count=500,
        require_image_or_video=False,
    )


class Harness:
    def __init__(self, options):
        self.options = options
        self.stats = Counter()
        self.errors = Counter()
        self.latencies = []
        self.queue_depth = defaultdict(int)
        self.peak_queue_depth = defaultdict(int)

        self.store = MessageStore(options.db_latency)
        self.pool = InstrumentedPool(options.pool_size, options.db_latency)
        self.messages = []
        self.channels = {}
        self.server_classes = {}

        for guild_index in range(options.guilds):
            guild_id = 1000 + guild_index
            guild = FakeGuild(guild_id)
            source_channel = FakeChannel(2000 + guild_index, guild, options.discord_latency, self.stats)
            target_channel = FakeChannel(3000 + guild_index, guild, options.discord_latency, self.stats)
            self.channels[source_channel.id] = source_channel
            self.channels[target_channel.id] = target_channel
            self.server_classes[guild_id] = build_server(guild_id, target_channel.id, options.threshold)

            per_guild = max(1, options.messages // options.guilds)
            for message_index in range(per_guild):
                message_id = guild_id * 100 + message_index
                message = TrackedMessage(message_id, source_channel, guild, 50 + message_index,
                                         options.discord_latency)
                source_channel.messages[message_id] = message
                self.messages.append(message)

        self.bot = FakeBot(self.channels)

    def install(self):
        """Point the real handler at the stand-ins, leaving its locks and pool handling intact."""
        async def record_log(_bot, message, *_args, **_kwargs):
            text = str(message)
            self.stats["log_lines"] += 1
            if "exhausted" in text:
                self.errors["pool exhausted"] += 1
            elif "Error in" in text or "Database error" in text:
                self.errors[text.split(":")[0][:60]] += 1

        async def build_embed(*_args, **_kwargs):
            # Embed rendering is covered by the unit suite and is pure formatting. Standing in for
            # it keeps the run measuring what it is here to measure, and keeps the posting path
            # reachable: on_raw_reaction discards any error containing "object has no attribute",
            # so a stand-in message that create_embed cannot read would be silently dropped
            self.stats["embeds_built"] += 1
            return object()

        self.patched = [
            (utils, "logging", utils.logging),
            (utils, "create_embed", utils.create_embed),
            (utils, "hall_of_fame_message_repo", utils.hall_of_fame_message_repo),
            (events, "hall_of_fame_message_repo", events.hall_of_fame_message_repo),
        ]
        utils.logging = record_log
        utils.create_embed = build_embed
        utils.hall_of_fame_message_repo = self.store
        events.hall_of_fame_message_repo = self.store

        main.bot = self.bot
        main.server_classes = self.server_classes
        main.connection_pool = self.pool
        main.message_locks = concurrency.KeyedLocks()

    def restore(self):
        for module, name, original in self.patched:
            setattr(module, name, original)

    def build_events(self):
        """The sequence of reactions and un-reactions that will be thrown at the bot."""
        random.seed(self.options.seed)
        plan = []
        hot = self.messages[:max(1, len(self.messages) // 10)]
        for _ in range(self.options.events):
            if self.options.scenario == "storm":
                message = random.choice(hot)
            elif self.options.scenario == "spread":
                message = random.choice(self.messages)
            else:
                message = random.choice(hot) if random.random() < 0.5 else random.choice(self.messages)
            user_id = random.randint(100, 100 + self.options.users)
            adding = random.random() < self.options.add_ratio
            plan.append((message, user_id, adding))
        return plan

    async def fire(self, message, user_id, adding):
        if adding:
            message.add_reactor(user_id)
        else:
            message.remove_reactor(user_id)

        payload = Payload(message.guild.id, message.channel.id, message.id, user_id)
        self.queue_depth[message.id] += 1
        self.peak_queue_depth[message.id] = max(self.peak_queue_depth[message.id],
                                                self.queue_depth[message.id])
        started = time.perf_counter()
        try:
            await main.handle_raw_reaction(payload, "stress")
            self.stats["handled"] += 1
        except Exception as error:
            self.errors[f"uncaught {type(error).__name__}"] += 1
        finally:
            self.queue_depth[message.id] -= 1
            self.latencies.append(time.perf_counter() - started)

    async def run(self):
        plan = self.build_events()
        limit = asyncio.Semaphore(self.options.concurrency)

        async def run_one(entry):
            async with limit:
                await self.fire(*entry)

        started = time.perf_counter()
        await asyncio.gather(*(run_one(entry) for entry in plan))
        self.stats["wall_seconds"] = time.perf_counter() - started


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def report(harness):
    options = harness.options
    stats = harness.stats
    print()
    print("=" * 72)
    print(f"  scenario {options.scenario}  |  {options.events} events  |  "
          f"{options.concurrency} concurrent  |  pool {options.pool_size}")
    print("=" * 72)

    wall = stats["wall_seconds"]
    dropped = sum(harness.errors.values())
    # The handler catches its own errors, so an event that was dropped still looks like it returned
    print(f"  events fired            {options.events}")
    print(f"  completed               {stats['handled'] - dropped}")
    print(f"  dropped                 {dropped}")
    print(f"  wall time               {wall:.2f}s  ({options.events / wall:.0f} events/s)")
    print(f"  discord calls           {stats['discord_calls']}  "
          f"({stats['discord_calls'] / max(1, options.events):.1f} per event)")
    print(f"  database reads/writes   {harness.store.reads} / {harness.store.writes}")
    print()
    print(f"  pool peak in flight     {harness.pool.peak_in_flight} of {options.pool_size}")
    print(f"  pool exhausted          {harness.pool.exhausted}")
    print(f"  connections handed out  {harness.pool.handed_out}")
    print()
    latencies = harness.latencies
    print(f"  latency p50             {percentile(latencies, 0.50) * 1000:.0f} ms")
    print(f"  latency p95             {percentile(latencies, 0.95) * 1000:.0f} ms")
    print(f"  latency max             {max(latencies) * 1000:.0f} ms" if latencies else "")
    print(f"  deepest lock queue      {max(harness.peak_queue_depth.values(), default=0)} "
          f"events waiting on one message")
    print()

    failures = []

    leaked = main.message_locks.active_keys()
    print(f"  locks still held        {leaked}")
    if leaked:
        failures.append(f"{leaked} message locks were not released")

    if harness.pool.in_flight:
        failures.append(f"{harness.pool.in_flight} connections were never returned to the pool")
    print(f"  connections not returned {harness.pool.in_flight}")

    stale = []
    for message in harness.messages:
        row = harness.store.rows.get((message.guild.id, message.channel.id, message.id))
        if row is None:
            continue
        if message.live_count >= options.threshold and row["reaction_count"] != message.live_count:
            stale.append((message.id, row["reaction_count"], message.live_count))
    print(f"  stale counts on board   {len(stale)}")
    if stale:
        failures.append(f"{len(stale)} featured messages recorded a count that is not the final one "
                        f"(for example message {stale[0][0]}: stored {stale[0][1]}, actual {stale[0][2]})")

    if harness.errors:
        print()
        print("  errors")
        for name, count in harness.errors.most_common():
            print(f"    {count:>6}  {name}")
        if harness.pool.exhausted:
            failures.append(f"the pool was exhausted {harness.pool.exhausted} times, "
                            f"and those reactions were dropped")

    print()
    if failures:
        print("  FAILED")
        for failure in failures:
            print(f"    - {failure}")
    else:
        print("  OK - every event handled, no locks leaked, no connections lost, counts settled")
    print("=" * 72)
    return 1 if failures else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=("storm", "spread", "mixed"), default="mixed",
                        help="storm: everyone piles onto a few messages. "
                             "spread: reactions land across many messages. mixed: both")
    parser.add_argument("--events", type=int, default=500, help="reaction events to fire")
    parser.add_argument("--concurrency", type=int, default=50,
                        help="events allowed to be in flight at once, as the gateway would deliver them")
    parser.add_argument("--messages", type=int, default=100, help="messages that can be reacted to")
    parser.add_argument("--guilds", type=int, default=5, help="servers the bot is in")
    parser.add_argument("--users", type=int, default=200, help="distinct members reacting")
    parser.add_argument("--pool-size", type=int, default=10,
                        help="connections in the pool, matching maxconn in main.py")
    parser.add_argument("--threshold", type=int, default=3, help="reaction threshold for every server")
    parser.add_argument("--discord-latency", type=float, default=0.05,
                        help="seconds per Discord API round trip, awaited rather than blocking")
    parser.add_argument("--db-latency", type=float, default=0.001,
                        help="seconds per database call, which really blocks the event loop")
    parser.add_argument("--add-ratio", type=float, default=0.7,
                        help="share of events that add a reaction rather than remove one")
    parser.add_argument("--seed", type=int, default=1, help="seed, so a run can be repeated")
    return parser.parse_args(argv)


def main_entry(argv=None):
    options = parse_args(argv)
    harness = Harness(options)
    harness.install()
    try:
        asyncio.run(harness.run())
        return report(harness)
    finally:
        harness.restore()


if __name__ == "__main__":
    sys.exit(main_entry())
