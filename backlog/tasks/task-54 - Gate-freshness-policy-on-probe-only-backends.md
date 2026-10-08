# Task 54: Gate freshness policy on probe-only backends

Status: open
Filed: 2026-10-08 (altitude review of the v4.15 merge resolution)
Source: /simplify altitude agent, finding 1

## Problem

`observe._agent_working` (the TASK-47 working-agent gate) resolves through
`agent_status_cache.get_status_or_probe` on every backend. The cache's
positive TTL is push-tuned (90s) because herdr's event stream refreshes it.
On probe-only backends with native agent status (agterm: `native_agent_status=
True`, `supports_event_stream=False`) nothing refreshes an entry, so the gate
can trust a stale `working` for up to 90 seconds after the agent went idle
and suppress a real prompt as queued-input. In the same file,
`_native_agent_status` refuses the cache on non-stream backends for exactly
this reason ("no push stream to refresh cached transitions").

Note: this behavior is inherited from the fork parent (its
`resolve_agent_status` had the same TTL-first policy on all backends); the
v4.15 merge resolution preserved it faithfully. The asymmetry became visible
only because upstream #319 added the split to `_native_agent_status`.

## Fix directions (pick one)

1. `_agent_working` applies the same `supports_event_stream` branch as
   `_native_agent_status`: cache-or-probe on stream backends, raw probe on
   probe-only ones. Requires test updates in
   `tests/ccgram/handlers/polling/window_tick/test_working_gate.py` (the
   suppressing tests seed the cache with no backend stub).
2. `get_status_or_probe` takes the max-age as a parameter so a consumer
   without a push stream can request a short freshness bound instead of
   inheriting the push-tuned 90s.

## Related facet (same coin, efficiency review finding 1)

The mirror problem sits in `_native_agent_status`'s probe-only arm: it probes
RAW every tick for gap-fill windows (one agtermctl/socket round-trip per
second, uncached, result discarded), and can double up with a gate probe in
the same tick. This arm is upstream's deliberate code: his test
`test_probe_only_backend_reads_each_status_transition` pins uncached
positive reads (await_count == 2 across a working→idle→working sequence),
so fixing it fork-side means carrying a delta against freshly-canonicalized
upstream code. The negative-only-cache idea (store None 15s, never store a
positive) is an upstream issue candidate, to file only with the maintainer's
issue-first workflow and explicit user approval.

## Acceptance

- On a probe-only backend, a working-to-idle transition lets the gate admit
  an interactive status within one TTL of the shorter bound (<=15s), not 90s.
- Herdr behavior unchanged (push-refreshed cache still answers gate checks
  without a subprocess).
- test_working_gate covers the probe-only transition case explicitly.
