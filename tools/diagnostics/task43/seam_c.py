"""Seam (c): the per-user queue lock is acquired and never released."""
import asyncio
import sys

sys.path.insert(0, "/tmp/freeze-repro")
from harness import main  # noqa: E402
from ccgram.handlers.messaging_pipeline import message_queue as mq  # noqa: E402


async def hold_lock_forever():
    uid = 4242
    queue = mq._ShardedUserQueue()
    mq._message_queues[uid] = queue
    mq._queue_locks[uid] = asyncio.Lock()
    # Pre-acquire: worker's status dispatch will wedge on async with lock.
    async with mq._queue_locks[uid]:
        await asyncio.sleep(10**9)


async def run():
    holder = asyncio.create_task(hold_lock_forever())
    await asyncio.sleep(0.2)
    await main(float(sys.argv[1]) if len(sys.argv) > 1 else 4.0)
    holder.cancel()


if __name__ == "__main__":
    asyncio.run(run())
