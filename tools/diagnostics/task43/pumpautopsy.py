"""Does the pump die with IndexError when all waiters cancel while it
awaits a token? (Path newly reachable by corpse removal.)"""
import asyncio

from ccgram.telegram_rate_limiter import _PriorityGroupScheduler


class SlowLimiter:
    max_rate = 20

    async def acquire(self) -> None:
        await asyncio.sleep(0.05)


async def main():
    sched = _PriorityGroupScheduler(SlowLimiter())
    parked = [asyncio.create_task(sched.acquire(interactive=False)) for _ in range(3)]
    await asyncio.sleep(0.01)          # parked; pump awaiting the token
    for t in parked:
        t.cancel()
    await asyncio.gather(*parked, return_exceptions=True)
    await asyncio.sleep(0.2)           # let the pump wake
    pump = sched._pump
    print(f"deques_empty={not sched._background and not sched._interactive}")
    print(f"pump_done={pump.done()}")
    if pump.done():
        exc = pump.exception()
        print(f"pump_exception={exc!r}")


asyncio.run(main())
