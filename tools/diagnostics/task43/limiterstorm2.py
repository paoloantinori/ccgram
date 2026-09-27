"""Corrected cancellation geometry: cancel requests that are PARKED
in the scheduler deque (spawn >capacity, cancel the tail), plus a
direct pump kill. Discriminator: do LATER clean requests still flow?"""
import asyncio
import time

from ccgram.telegram_rate_limiter import CCGramAIORateLimiter

GROUP = -100999
DATA = {"chat_id": GROUP}


async def cb(*a, **kw):
    return {"ok": True}


async def main():
    # 1) cancel PARKED waiters, then verify fresh traffic flows
    lim = CCGramAIORateLimiter(max_retries=3)
    parked = [asyncio.create_task(lim.process_request(cb, (), {}, "sendMessage", DATA, None))
              for _ in range(45)]  # capacity 20 -> 25 parked
    await asyncio.sleep(0.2)         # all spawned; 20 served, 25 parked
    for t in parked[20:]:
        t.cancel()
    served = 0
    for t in parked[:20]:
        try:
            await asyncio.wait_for(t, 5)
            served += 1
        except Exception:
            pass
    print(f"[cancel-parked] transport_served={served} of 20")
    sched = lim._priority_schedulers[GROUP]
    print(f"    after-cancel: bg_waiters={len(sched._background)} "
          f"interactive={len(sched._interactive)} pump_done={sched._pump.done() if sched._pump else None}")
    # recovery probe: new bucket cycle is 60s, so probe with wait up to 70s
    t0 = time.monotonic()
    fresh = [asyncio.create_task(lim.process_request(cb, (), {}, "sendMessage", DATA, None))
             for _ in range(3)]
    done, pending = await asyncio.wait(fresh, timeout=70)
    lat = time.monotonic() - t0
    print(f"[cancel-parked recovery] done={len(done)} pending={len(pending)} after={lat:.0f}s")
    for t in pending:
        t.cancel()
    await asyncio.gather(*parked, *fresh, return_exceptions=True)

    # 2) kill the pump directly mid-service, then verify respawn
    lim2 = CCGramAIORateLimiter(max_retries=3)
    tasks = [asyncio.create_task(lim2.process_request(cb, (), {}, "sendMessage", DATA, None))
             for _ in range(25)]
    await asyncio.sleep(0.2)
    sched2 = lim2._priority_schedulers[GROUP]
    sched2._pump.cancel()
    try:
        await sched2._pump
    except asyncio.CancelledError:
        pass
    print(f"[pump-kill] waiters_at_kill bg={len(sched2._background)} "
          f"pump_done={sched2._pump.done()}")
    # the 5 parked waiters should be stranded UNTIL a new acquire respawns the pump
    probe = asyncio.create_task(lim2.process_request(cb, (), {}, "sendMessage", DATA, None))
    done2, pend2 = await asyncio.wait(tasks + [probe], timeout=70)
    print(f"[pump-kill recovery] done={len(done2)} pending={len(pend2)}")
    for t in pend2:
        t.cancel()
    await asyncio.gather(*tasks, probe, return_exceptions=True)
    print(f"    final pump_done={sched2._pump.done()} "
          f"(respawned and alive: {not sched2._pump.done()})")


asyncio.run(main())
