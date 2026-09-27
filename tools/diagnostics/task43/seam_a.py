"""Seam (a): the group scheduler's token acquire never resolves."""
import asyncio
import sys

sys.path.insert(0, "/tmp/freeze-repro")
from harness import main  # noqa: E402
from ccgram.telegram_rate_limiter import _PriorityGroupScheduler  # noqa: E402


async def never(self, *, interactive: bool = False):
    await asyncio.sleep(10**9)


_PriorityGroupScheduler.acquire = never

if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 6.0))
