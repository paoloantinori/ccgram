"""Headless delivery-queue harness for the 2026-09-26 wedge repro.

Signature to match (from the live incident): worker task alive, zero
deliveries, zero log lines, offset frozen. Each seam sweep stalls one
point via pyteman; we then check the signature after a bounded wait.
"""
import asyncio
import sys
import time

from ccgram.handlers.messaging_pipeline import message_queue as mq
from ccgram.handlers.messaging_pipeline.message_task import ContentTask


class HangingClient:
    """TelegramClient stand-in: counts sends, never hangs by itself."""

    def __init__(self):
        self.sends = 0

    async def send_message(self, *a, **kw):
        self.sends += 1
        return SimpleNamespace(message_id=self.sends)


class SimpleNamespace:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def main(timeout_s: float = 8.0) -> None:
    client = HangingClient()
    uid = 4242
    queue = mq.get_or_create_queue(client, uid)
    for i in range(5):
        queue.put_nowait(
            ContentTask(
                window_id="@0",
                parts=(f"message {i}",),
                content_type="text",
                role="assistant",
                thread_id=42,
                chat_id=-100,
            )
        )
    await asyncio.sleep(timeout_s)
    worker = mq._queue_workers.get(uid)
    print("RESULT sends=", client.sends,
          "worker_alive=", worker is not None and not worker.done(),
          "pending=", len(queue.pending_items()))
    # Signature match: worker_alive=True AND sends==0 AND pending==5.
    if worker is not None and not worker.done() and client.sends == 0:
        print("SIGNATURE MATCH: silent wedge reproduced")
        sys.exit(0)
    print("NO MATCH (delivery flowed or worker died)")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 8.0))
