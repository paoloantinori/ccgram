---
id: TASK-182
title: Reduce chronic bridge polling CPU (43% of a core at idle)
status: Open
assignee: []
created_date: '2026-10-25 16:20'
updated_date: '2026-10-25 16:20'
labels:
  - kind/performance
dependencies: []
references: []
priority: high
ordinal: 100
---

## Description

The bridge burns a third to nearly half of a CPU core while completely
idle, on both hosts and both current build generations:

- bird, 4.17 line, 49 monitored sessions: ~43% of one core steady state
  (measured 2026-10-25: 1288 scheduler ticks over 30 s with no delivery
  activity).
- Mac, 4.14 line: ~31% of one core steady state (6.28 s CPU over 20 s).

This is chronic, not a regression of any recent change: it predates the
2026-10-25 skip-path hardening (the reverted known-good tree spun
identically) and the v4.17 shared-session-core merge (the Mac pre-v4.17
build shows it too). It was simply never measured before.

Ruled out as causes (2026-10-25 evidence): subprocess spawn storms (zero
execve in a 4 s strace of the spinning process), herdr socket connection
storms (daemon log quiet), journald saturation side effects (CPU
unchanged after the flood source was removed). The spin is in-process
asyncio work with ~150 syscalls/s (fcntl/getsockopt heavy, negligible
write volume): a hot await/yield loop in the polling path.

## Progress 2026-10-25 (evening)

SLICE 1 SHIPPED (fork/main cbb9d426, deployed on both bridges): the
per-cycle transcript prefix re-verification (full read + sha256 of the
whole consumed prefix, twice per cycle) is now marker-fast-path for
appends with exponential digest backoff; deterministic side-by-side on
30 poll cycles over a 10 MB transcript: 90 digest calls / 902.7 MB
hashed on the old line vs 2 calls / 20 MB on the new one; all
replacement-protection tests green unchanged (branch
fix/prefix-verify-cost, commits 8ecc7ab1..cbb9d426).

MEASURED STEADY STATE AFTER SLICE 1 (298 s cProfile of the live-shaped
foreground run, /tmp/ccgram-prof.out): the remaining cost decomposes as
(1) pyte screen rendering driven by handlers/polling/polling_state.py:
parse_with_pyte re-feeding FULL pane captures every tick:
pyte/screens.py render hit ~7M internal calls, the biggest named item;
(2) sha256 prefix verification with the new 32-cycle backoff cap;
(3) transcript JSON parsing of genuinely new entries. Live CPU now
17-31% of a core depending on agent activity (was 30-43% baseline).

## NEXT (hotspot 1 named)

parse_with_pyte should feed only the delta since the last capture or
skip unchanged captures entirely (content-hash gate like live_view's);
protects the same buffers, cost moves from O(captured bytes) per tick
to O(delta). After that lands, re-measure with the tick-delta method;
if still above 5%, the residual is the 1s polling model itself
(interval tuning is a product decision, not a bug).

## Acceptance

- The hot loop is NAMED with a profile or equivalent evidence (py-spy
  does not support Python 3.15; use a sampling hack, asyncio
  instrumentation, or a bisection of the polling components), not guessed.
- Steady-state CPU on bird with ~49 monitored sessions is below 5% of a
  core, measured with the same /proc/<pid>/stat tick-delta method, with
  no change in delivery latency or status freshness.
- The measurement method is recorded here so the number stays
  explainable (see the explain-the-number principle: what limits the
  cost, what the new cost is, why).
