"""Real CCGramAIORateLimiter stack probe (PTB calls process_request
directly; this is the same surface). Scenarios: baseline, single
transport hang, RetryAfter retries, and the scheduler under
saturation + cancellation storms (pump-survival hunt)."""
import asyncio
import sys
import time

from telegram.error import RetryAfter

from ccgram.telegram_rate_limiter import (
    CCGramAIORateLimiter,
    interactive_priority,
)

GROUP = -100999
DATA = {"chat_id": GROUP}


def mk_callback(script):
    """script: dict call_index -> 'ok' | 'hang' | ('ra', seconds)."""
    calls = {"n": 0}

    async def cb(*a, **kw):
        calls["n"] += 1
        n = calls["n"]
        action = script.get(n, "ok")
        if action == "hang":
            await asyncio.sleep(10**9)
        if isinstance(action, tuple) and action[0] == "ra":
            raise RetryAfter(action[1])
        return {"ok": True, "call": n}

    return cb, calls


async def scenario(name, script, concurrent=1, interactive_at=None,
                   cancel_some=False, seconds=12.0):
    lim = CCGramAIORateLimiter(max_retries=3)
    cb, calls = mk_callback(script)
    tasks = []

    async def one(i):
        if interactive_at is not None and i == interactive_at:
            with interactive_priority():
                t0 = time.monotonic()
                await lim.process_request(cb, (), {}, "sendMessage", DATA, None)
                return ("interactive", time.monotonic() - t0)
        else:
            await lim.process_request(cb, (), {}, "sendMessage", DATA, None)
            return ("bg", None)

    for i in range(concurrent):
        tasks.append(asyncio.create_task(one(i)))

    if cancel_some:
        await asyncio.sleep(0.05)
        for t in tasks[: cancel_some]:
            t.cancel()

    done, pending = await asyncio.wait(tasks, timeout=seconds)
    lat = [r for r in (t.result() for t in done if not t.cancelled())
           if r and r[0] == "interactive"]
    print(f"[{name}] completed={len(done)} pending={len(pending)} "
          f"transport_calls={calls['n']}"
          + (f" interactive_latency={lat[0][1]:.1f}s" if lat else ""))
    for t in pending:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    # pump autopsy: any stranded waiter?
    for gid, sched in lim._priority_schedulers.items():
        print(f"    scheduler[{gid}]: interactive_waiters="
              f"{len(sched._interactive)} bg_waiters={len(sched._background)} "
              f"pump_done={sched._pump.done() if sched._pump else None}")


async def main():
    await scenario("baseline-10", {}, concurrent=10)
    await scenario("hang-2nd-of-5", {2: "hang"}, concurrent=5, seconds=6)
    await scenario("retryafter-x3-then-ok",
                   {1: ("ra", 0.1), 2: ("ra", 0.1), 3: ("ra", 0.1)},
                   concurrent=1)
    await scenario("saturated-25-bg-plus-1-interactive", {},
                   concurrent=26, interactive_at=25, seconds=25)
    await scenario("saturation-cancellation-storm", {}, concurrent=30,
                   cancel_some=15, seconds=20)


if __name__ == "__main__":
    asyncio.run(main())
