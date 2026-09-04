---
id: TASK-19
title: herdr stream efficiency: debounce per-event mapping checks, gather the re-prime
status: Done
assignee: []
created_date: '2026-09-04 19:30'
updated_date: '2026-09-04 19:30'
labels: []
dependencies: []
---

## Description

TASK-13 noted the per-event mapping check (one agent-list fork per non-terminal event) as the dominant stream subprocess cost, and the sentinel re-prime ran serially. Implemented 2026-09-04: _MOVE_CHECK_MIN_INTERVAL=5.0s debounce (stamped fresh at the sentinel; idle path still checks every 30s; a permanently-busy stream still checks periodically since monotonic grows past any fixed stamp) + asyncio.gather for the re-prime. Existing move test patches the constant to 0 (per-event detection is what it tests); new dedicated debounce test (sentinel+3 quick events = 1 resolve). Code-review gate in flight; commit+deploy on pass.

Closed 2026-09-04: code-review verified all five points (debounce interplay with a mechanical busy-stream probe, gather parity and ordering, bounded ack-window exposure); the sentinel-stamp comment was reworded to not overclaim. Committed and deployed with the backlog batch.
