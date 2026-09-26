import asyncio
import unittest

import concurrency


class KeyedLocksTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.locks = concurrency.KeyedLocks()

    async def test_work_on_the_same_key_does_not_overlap(self):
        events = []

        async def work(name):
            async with self.locks.acquire("message"):
                events.append(f"{name} start")
                await asyncio.sleep(0)
                events.append(f"{name} end")

        await asyncio.gather(work("first"), work("second"))

        self.assertEqual(["first start", "first end", "second start", "second end"], events)

    async def test_work_on_different_keys_overlaps(self):
        started = asyncio.Event()
        released = asyncio.Event()

        async def holder():
            async with self.locks.acquire("one"):
                started.set()
                await released.wait()

        async def other():
            await started.wait()
            async with self.locks.acquire("two"):
                released.set()

        await asyncio.wait_for(asyncio.gather(holder(), other()), timeout=1)

        self.assertTrue(released.is_set())

    async def test_a_failure_releases_the_lock(self):
        with self.assertRaises(ValueError):
            async with self.locks.acquire("message"):
                raise ValueError("boom")

        async with self.locks.acquire("message"):
            pass

        self.assertEqual(0, self.locks.active_keys())

    async def test_locks_are_discarded_once_nobody_waits(self):
        async def work():
            async with self.locks.acquire("message"):
                await asyncio.sleep(0)

        await asyncio.gather(work(), work(), work())

        self.assertEqual(0, self.locks.active_keys())

    async def test_a_lock_is_kept_while_another_caller_waits(self):
        inside = asyncio.Event()
        release = asyncio.Event()

        async def holder():
            async with self.locks.acquire("message"):
                inside.set()
                await release.wait()

        async def waiter():
            await inside.wait()
            async with self.locks.acquire("message"):
                pass

        holder_task = asyncio.create_task(holder())
        waiter_task = asyncio.create_task(waiter())
        await inside.wait()
        await asyncio.sleep(0)

        self.assertEqual(1, self.locks.active_keys())

        release.set()
        await asyncio.wait_for(asyncio.gather(holder_task, waiter_task), timeout=1)
        self.assertEqual(0, self.locks.active_keys())


if __name__ == "__main__":
    unittest.main()
