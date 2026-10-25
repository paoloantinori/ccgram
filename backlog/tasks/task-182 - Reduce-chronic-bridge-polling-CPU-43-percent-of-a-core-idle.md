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
