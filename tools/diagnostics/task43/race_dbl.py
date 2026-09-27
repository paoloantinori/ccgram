"""Race: two concurrent get_or_create_queue spawns two workers for one user.

Monitor (routing) and a PTB handler can both call get_or_create_queue
for the same user with no lock around the check-then-spawn. Two
workers share one _ShardedUserQueue: the facade's _last (no-arg
task_done authority) is shared state, and per-shard counters can
drift. Does traffic under two workers wedge or corrupt?
"""
import asyncio
import sys

sys.path.insert(0, "/tmp/freeze-repro")
from harness import HangingClient, SimpleNamespace  # noqa: E402
from ccgram.handlers.messaging_pipeline import message_queue as mq
from ccgram.handlers.messaging_pipeline.message_task import ContentTask


async def main(seconds: float = 6.0) -> None:
    client = HangingClient()
    uid = 4343
    # Two concurrent creators: both observe no worker, both spawn.
    q1, q2 = await asyncio.gather(
        asyncio.to_thread(lambda: None),  # warm to_thread
        asyncio.to_thread(lambda: None),
    )
    # Simulate the interleaving deterministically by calling the two
    # halves the way two tasks would: sequential check+spawn, twice.
    for _ in range(2):
        if uid not in mq._message_queues:
            mq._message_queues[uid] = mq._ShardedUserQueue()
            mq._queue_locks[uid] = asyncio.Lock()
        existing = mq._queue_workers.get(uid)
        if existing is None or existing.done():
            mq._queue_workers[uid] = asyncio.create_task(
                mq._message_queue_worker(client, uid)
            )
    queue = mq._message_queues[uid]
    for i in range(10):
        queue.put_nowait(
            ContentTask(
                window_id="@0",
                parts=(f"m{i}",),
                content_type="text",
                role="assistant",
                thread_id=42,
                chat_id=-100,
            )
        )
    await asyncio.sleep(seconds)
    workers_alive = sum(
        1
        for t in [mq._queue_workers.get(uid)]
        if t is not None and not t.done()
    )
    # Count actual workers referencing this uid: only the dict entry is
    # tracked; the orphaned first task also runs. Detect it by sends.
    print("RESULT sends=", client.sends,
          "dict_worker_alive=", workers_alive,
          "pending=", len(queue.pending_items()),
          "unfinished=", queue._unfinished)
    drift = queue._unfinished != len(queue.pending_items())
    orphan_running = client.sends > 0 and workers_alive == 0
    if drift or orphan_running:
        print("ANOMALY: accounting drift or orphan worker")
    else:
        print("no anomaly in this window")
    # Cancel everything the dict does not track: the orphan.
    for t in list(asyncio.all_tasks()):
        if t.get_coro() is not None and "message_queue_worker" in repr(t.get_coro()):
            t.cancel()


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 6.0))
