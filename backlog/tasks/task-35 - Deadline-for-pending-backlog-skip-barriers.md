---
id: TASK-35
title: Give pending backlog-skip barriers a deadline so a stuck notice cannot mute a source forever
status: Open
assignee: []
created_date: '2026-09-20 09:10'
updated_date: '2026-09-20 09:10'
labels: [delivery, stall, backlog-skip]
dependencies: []
---

## Description

While a session sits in `state.pending_skips`, reading is skipped
(session_monitor.py:531/553) and watermark commits are fenced (:452). The
barrier completes only when its visible notice is delivered and validated
(`_commit_pending_skips`). Nothing bounds that: if the notice cannot deliver
(topic rebind, dead topic, sustained flood control, wedge in the delivery
queue), the source stays paused forever, and `pending_skips` persists across
restarts. This is the "bot mute for hours" class the user reported
2026-09-20, and it compounds with upstream issue #245 (restart replay
starvation, filed by us 2026-09-14).

Fix: add a created/first-attempt monotonic-derived wall clock stamp to
BacklogSkipIntent (persisted); when a barrier is older than a deadline
(order of 10 minutes) and still not committed, force-complete it: advance
the watermark to snapshot_offset, drop the barrier, log a warning. A skip's
purpose is to sacrifice history for liveness; an undeliverable notice must
not invert that into permanent silence.
Test: a persisted stale intent; after the deadline the monitor completes it,
reading resumes, watermark equals snapshot_offset.

## Review outcome (2026-09-20, code-review high)

Shipped plus review hardening: rebound topics cancel instead of advancing
the watermark (_skip_is_current guard, as _commit_pending_skips enforces),
resume attempts run before expiry so a slept process still gets one
delivery attempt, wall-clock age clamps at zero against backwards clock
steps, legacy stamps persist through a MonitorState.stamp_skip_clock
mutator, and one batched save per pass replaces per-barrier writes.
FOLLOW-UP (accepted debt): force-completion ignores purge_complete, so a
barrier whose purge kept failing can retire with pre-skip queue work still
queued; the double-fault window is 600s and the queued work is bounded, so
liveness still wins, but purge-then-complete at expiry is the complete
fix.
