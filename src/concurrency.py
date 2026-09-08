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
