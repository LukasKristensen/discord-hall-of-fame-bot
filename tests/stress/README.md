# Stress testing

The unit suite answers "does one reaction do the right thing". This answers "what happens when
several hundred arrive at once", which is a different question with different failure modes: the
per-message locks, the connection pool, and the event loop itself.

Nothing here runs with `python -m unittest discover`. These are scripts, run deliberately.

<br>

## reaction_storm.py

Drives `main.handle_raw_reaction`, the real handler, with the real `KeyedLocks` and the real
`get_db_connection` in place. Discord and PostgreSQL are replaced with stand-ins that model the two
properties that decide how the bot behaves under load:

- a Discord call is slow but yields to the event loop, so it is awaited
- a database call is fast but **blocks** the event loop, because psycopg2 is synchronous, so it
  really sleeps the thread

The pool stand-in reproduces psycopg2's semantics, including the one that matters most:
`getconn` **raises** `PoolError` when every connection is checked out. It does not queue and it does
not wait.

```
python tests/stress/reaction_storm.py --scenario spread
python tests/stress/reaction_storm.py --scenario storm --events 2000 --concurrency 100
python tests/stress/reaction_storm.py --scenario spread --concurrency 40 --pool-size 40
```

### The two scenarios test different things

**`storm`** piles every reaction onto a handful of messages. This is one post going viral, and it is
what tests the locks. Note that it puts almost no pressure on the pool: the per-message locks mean
only one handler per message is ever past the lock, so the number of connections in use is bounded
by the number of *distinct* hot messages, not by the number of events.

**`spread`** lands reactions across many different messages, which is what a busy evening across
many servers actually looks like. This is what tests the pool, because every distinct message is a
connection held for the length of a Discord round trip.

Run both. A change that helps one can hurt the other.

### What it checks

Beyond throughput and latency it asserts four invariants, and exits non-zero if any break:

| Invariant | Why it matters |
|:---|:---|
| No locks still held | `KeyedLocks` deletes a lock once nobody waits on it. A leak means unbounded memory growth, one entry per message ever reacted to. |
| No connections unreturned | A connection that is never put back is gone from the pool for the life of the process. Ten of those and the bot stops working entirely. |
| No stale counts on the board | After the storm settles, the count stored for a featured message must equal its real reaction count. This is the guarantee the locks exist to provide. |
| No dropped events | An event the bot failed to process is a reaction the member made that the board never reflects. |

### Reading the output

`pool peak in flight` against `pool exhausted` is the number to watch. Exhaustion is not graceful
degradation: a starved event fails instantly and frees its slot, so the next one rushes in and fails
too, while the working connections stay held for the length of a Discord round trip. The result is
that a small overshoot drops most of the traffic rather than a proportional share.

`deepest lock queue` is how many events were waiting behind one message. Multiply by the per-event
latency to get the delay the last person to react sees on a hot post.

<br>

## What this harness cannot tell you

It models the shape of the load, not the real thing. Three things it deliberately does not cover,
in the order worth doing them:

1. **Real query cost.** Every query here is a dictionary lookup plus a sleep. Point a load generator
   at a copy of production data instead, with `EXPLAIN ANALYZE` on the four queries in the reaction
   path, and check the indexes are actually used at real table sizes.
2. **Real Discord rate limits.** discord.py queues internally when a channel's edit limit is hit,
   which lengthens exactly the window during which a connection is held. The harness uses a fixed
   latency instead, so it understates this.
3. **Sustained load.** Everything here finishes in seconds. Connection leaks, memory growth in the
   caches and the duplicate-log filter, and slow degradation only show up over hours. Run the
   development bot in a busy test server for a day and watch resident memory and the pool.
