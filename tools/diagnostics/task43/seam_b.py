"""Seam (b): the PTB HTTP send awaits forever (timeout defeated)."""
import asyncio
import sys

sys.path.insert(0, "/tmp/freeze-repro")
from harness import main  # noqa: E402
from ccgram.handlers.messaging_pipeline import message_queue as mq  # noqa: E402

_orig = mq._dispatch


async def hung_dispatch(*a, **kw):
    await asyncio.sleep(10**9)


mq._dispatch = hung_dispatch

if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 5.0))
