"""Incident fingerprint test: corpse backlog + saturation.
Prediction: an INTERACTIVE send is served within ~one refill (3s)
while a BACKGROUND send waits ~corpses x 3s. This asymmetry is the
/screenshot-works-while-queue-frozen signature of 2026-09-26.
"""
import asyncio
import time

from ccgram.telegram_rate_limiter import (
    CCGramAIORateLimiter,
    interactive_priority,
)

GROUP = -100999
DATA = {"chat_id": GROUP}


async def cb(*a, **kw):
    return {"ok": True}


async def timed(lim, interactive):
    t0 = time.monotonic()
    if interactive:
        with interactive_priority():
            await lim.process_request(cb, (), {}, "sendMessage", DATA, None)
    else:
        await lim.process_request(cb, (), {}, "sendMessage", DATA, None)
    return time.monotonic() - t0


async def main():
    lim = CCGramAIORateLimiter(max_retries=3)
    # drain the bucket
    warm = [asyncio.create_task(lim.process_request(cb, (), {}, "sendMessage", DATA, None))
            for _ in range(20)]
    await asyncio.wait(warm, timeout=5)
    # park 60 requests, then cancel them all -> 60 corpses under saturation
    corpses = [asyncio.create_task(lim.process_request(cb, (), {}, "sendMessage", DATA, None))
               for _ in range(60)]
    await asyncio.sleep(0.3)
    for t in corpses:
        t.cancel()
    await asyncio.gather(*corpses, return_exceptions=True)
    sched = lim._priority_schedulers[GROUP]
    print(f"corpses_in_deque={len(sched._background)} "
          f"pump_alive={not sched._pump.done()}")
    # the incident moment: interactive send (screenshot) + background send (queue)
    bg = asyncio.create_task(timed(lim, interactive=False))
    await asyncio.sleep(0.2)
    inter = asyncio.create_task(timed(lim, interactive=True))
    dt_i = await asyncio.wait_for(inter, 120)
    dt_b = await asyncio.wait_for(bg, 400)
    print(f"interactive_served_in={dt_i:.1f}s  background_served_in={dt_b:.1f}s")


asyncio.run(main())
