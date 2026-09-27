"""Full-chain wedge probe: REAL worker + dispatch + sender + rate
limiter stack; only the HTTP layer is fault-scripted (hang on the
Nth request) to see whether the signature reproduces with the exact
production components and their real timeouts.
"""
import asyncio
import sys

sys.path.insert(0, "/tmp/freeze-repro")

from telegram.error import TelegramError  # noqa: E402

from ccgram.handlers.messaging_pipeline import message_queue as mq  # noqa: E402
from ccgram.handlers.messaging_pipeline.message_task import ContentTask  # noqa: E402


class ScriptedBot:
    """Minimal Bot duck-type for the sender chain: routes sends into a
    scripted transport that can hang or succeed per call index."""

    def __init__(self, hang_at: int | None = None):
        self.calls = 0
        self.hang_at = hang_at
        self._lock = asyncio.Lock()

    async def send_message(self, *args, **kwargs):
        self.calls += 1
        n = self.calls
        if self.hang_at is not None and n == self.hang_at:
            print(f"[transport] request {n} hanging forever")
            await asyncio.sleep(10**9)
        return SimpleMessage(n)


class SimpleMessage:
    def __init__(self, mid):
        self.message_id = mid


async def main(seconds: float, hang_at: int | None) -> None:
    uid = 90909
    bot = ScriptedBot(hang_at=hang_at)

    async def _noop(chat_id):
        return None

    mq.rate_limit_send = _noop  # isolate the limiter under test: PTB's

    queue = mq.get_or_create_queue(bot, uid)
    for i in range(6):
        queue.put_nowait(
            ContentTask(
                window_id="@0",
                parts=(f"m{i}",),
                content_type="text",
                role="assistant",
                thread_id=9,
                chat_id=-100,
            )
        )
    await asyncio.sleep(seconds)
    worker = mq._queue_workers.get(uid)
    print(
        "RESULT transport_calls=", bot.calls,
        "worker_alive=", worker is not None and not worker.done(),
        "pending=", len(queue.pending_items()),
        "unfinished=", queue._unfinished,
    )
    outstanding = len(queue.pending_items()) + queue._unfinished
    if worker is not None and not worker.done() and outstanding > 0:
        print("SIGNATURE MATCH: worker wedged with deliveries outstanding")
    else:
        print("no match (chain drained or worker died)")


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    hang = int(sys.argv[2]) if len(sys.argv) > 2 else None
    asyncio.run(main(secs, hang))
