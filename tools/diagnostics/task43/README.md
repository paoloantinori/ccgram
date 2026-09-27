# TASK-43 wedge diagnosis harnesses

Standalone probes for the 2026-09-26 delivery-queue wedge (7h silent,
worker alive, zero log lines, frozen watermark). Run from the repo
root with `uv run --no-project --with pyyaml` and
`PYTHONPATH=tools/diagnostics/task43`.

## Root cause (2026-09-27): scheduler waiter corpses

_PriorityGroupScheduler.acquire left a cancelled waiter's future in
the deque, and the pump burned one real token per corpse (3s under
flood saturation) with zero logs. Verified fingerprint (60 corpses):
background lane frozen 185.7s, interactive lane 2.5s, pump alive,
worker alive. Exactly the incident (/screenshot worked while the
queue starved 09:34-16:40 on 2026-09-26; the corpse-carrying
scheduler had been in production since 08:12 that morning).
Fix: removal at cancellation in acquire()'s CancelledError handler
plus an empty-deque guard so the pump exits cleanly when every waiter
cancels mid-token; red-green regression test
tests/ccgram/test_interactive_priority.py::test_cancelled_waiter_burst_leaves_no_corpses.
Residual: the 7h sustain needed recurring corpse replenishment whose
exact mix the restart destroyed; the fix removes the class entirely.

## Probes

- `harness.py`: headless per-user queue + worker; defines the
  incident signature (worker alive, zero sends, pending intact).
- `seam_a.py`: group-scheduler token never resolves (no match alone).
- `seam_b.py`: never-resolving await in _dispatch (MATCH).
- `seam_c.py`: per-user queue lock never released (MATCH).
- `race_dbl.py` / prior 30-round sweep: double-worker race; the
  apparent ledger leak was RETRACTED (extra_task_done finally at
  message_queue.py:1006 compensates; the sweep's cancellations landed
  inside that finally's window).
- `fullchain.py`: real dispatch/sender chain with a scripted
  transport: baseline drains clean; ONE hanging HTTP request
  reproduces the exact signature (worker alive, unfinished stuck,
  zero logs). Production HTTP timeouts are 10s, which is what pointed
  the hunt at the rate-limiter layer instead.
- `limiterstack.py`: real CCGramAIORateLimiter via process_request
  (baseline / single hang / RetryAfter retries / saturation +
  cancellation storm, with scheduler autopsy per scenario).
- `limiterstorm2.py`: cancel PARKED waiters + direct pump kill, with
  recovery probes (pre-fix: fresh traffic unserved after 70s).
- `corpseasym.py`: the incident fingerprint. 60 cancelled parked
  waiters; pre-fix interactive 2.5s vs background 185.7s; post-fix
  corpses_in_deque=0 and background 5.7s.
- `pumpautopsy.py`: total waiter cancellation while the pump awaits
  its token. Pre-guard the pump died with IndexError (pop from an
  empty deque); with the empty-deque guard it exits cleanly
  (pump_exception=None).

pyteman integration: entry rulesets now fire on coroutine targets
(pyteman TASK-178); tracing rules go in the run's PYTEMAN_RULES. The
sleep action blocks the loop (TASK-181 pending), so loop-alive hangs
stay on direct monkeypatch.
