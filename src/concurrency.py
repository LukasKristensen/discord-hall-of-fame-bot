import asyncio
from contextlib import asynccontextmanager


class KeyedLocks:
    """
    Hands out one lock per key so that work on the same key runs one at a time.

    Reaction events arrive in bursts for the same message, and handling them concurrently makes the
    bot post duplicates or write stale reaction counts. Dropping the extra events loses the newest
    count instead, so they are queued behind the message they belong to. Locks are discarded once
    nobody is waiting for them, which keeps the bot from growing a lock per message it has ever seen.
    """

    def __init__(self):
        self._locks = {}
        self._waiters = {}

    def active_keys(self) -> int:
        """
        :return: The number of keys currently holding a lock, used to assert nothing leaks
        """
        return len(self._locks)

    @asynccontextmanager
    async def acquire(self, key):
        """
        Acquire the lock belonging to a key for the duration of the block
        :param key: The key to serialize on, for example a message id
        """
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._waiters[key] = self._waiters.get(key, 0) + 1

        try:
            async with lock:
                yield
        finally:
            self._waiters[key] -= 1
            if self._waiters[key] == 0:
                del self._waiters[key]
                del self._locks[key]


class BatchOutcome:
    """
    What a batched run managed to do, so the caller can report it without counting for itself.
    """

    def __init__(self):
        self.completed = []
        self.failed = []

    @property
    def timed_out(self) -> list:
        """
        :return: The items that were abandoned for taking too long
        """
        return [item for item, error in self.failed if isinstance(error, asyncio.TimeoutError)]

    def __len__(self) -> int:
        return len(self.completed) + len(self.failed)


async def run_in_batches(items, worker, limit: int, timeout: float = None, on_error=None) -> BatchOutcome:
    """
    Run the worker over every item, with at most a fixed number of them in flight at once.

    The daily maintenance work runs across every server the bot is in, so it needs three
    guarantees that a plain loop does not give. Nothing may be dropped or done twice, since a
    skipped server means a stale leaderboard for a day. One server may not stall the rest, so each
    item is given its own timeout and abandoned when it passes. And the number of requests in
    flight stays bounded, because the point of doing this concurrently is to stop waiting on one
    server at a time, not to open a request per server at once.

    The timeout is measured from when an item starts rather than from when the batch does, so an
    item waiting for a free slot is not charged for the wait.
    :param items: The items to process, each passed to the worker on its own
    :param worker: An async callable taking one item
    :param limit: How many items may be in flight at once
    :param timeout: How many seconds one item may take, or None to let it run
    :param on_error: An async callable taking the item and the exception it raised
    :return: A BatchOutcome naming what finished and what did not
    """
    items = list(items)
    outcome = BatchOutcome()
    if not items:
        return outcome

    semaphore = asyncio.Semaphore(max(1, limit))

    async def run_one(item):
        async with semaphore:
            try:
                if timeout is None:
                    await worker(item)
                else:
                    await asyncio.wait_for(worker(item), timeout)
            except Exception as error:
                outcome.failed.append((item, error))
                if on_error is None:
                    return
                try:
                    await on_error(item, error)
                except Exception:
                    # Reporting a failure must not become a second failure that stops the batch,
                    # as the reporting itself goes over the same connection that just broke
                    pass
            else:
                outcome.completed.append(item)

    await asyncio.gather(*(run_one(item) for item in items))
    return outcome
