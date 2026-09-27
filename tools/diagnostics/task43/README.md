# TASK-43 wedge diagnosis harnesses

Standalone probes for the 2026-09-26 delivery-queue wedge (7h silent,
worker alive, zero log lines, frozen watermark). Run from the repo
root with `uv run --no-project --with pyyaml` and
`PYTHONPATH=tools/diagnostics/task43`.

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
  zero logs). Production HTTP timeouts are 10s, so the open question
  is which await inside the chain can defeat them. Next: wire the
  real PTB Bot + CCGramAIORateLimiter stack via a mocked HTTPX
  transport and fault-script requests there.

pyteman integration: entry rulesets now fire on coroutine targets
(pyteman TASK-178); tracing rules go in the run's PYTEMAN_RULES. The
sleep action blocks the loop (TASK-181 pending), so loop-alive hangs
stay on direct monkeypatch.
