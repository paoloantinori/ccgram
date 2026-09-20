---
id: TASK-36
title: Auto backlog-skip hygiene: per-session backoff and same-file gap guard
status: Open
assignee: []
created_date: '2026-09-20 09:10'
updated_date: '2026-09-20 09:10'
labels: [backlog-skip, robustness]
dependencies: []
---

## Description

Evidence 2026-09-18/19 on bird: 3,673 "Cannot snapshot transcript for
backlog skip" warnings in 36h, one session (pyteman 0942e19d), every poll
(~2s) for 3h20m, across TWO process instances. Two defects in
`_maybe_auto_backlog_skip` / `request_backlog_skip`:

1. No backoff on the failed-attempt path: when `request_backlog_skip`
   returns None (stat failure, regressed EOF, unresolvable session), the
   next poll retries immediately; the warning loop at poll cadence is this
   bug, not a filesystem mystery.
2. Cross-file arithmetic: the gap is `file_path.stat().st_size - session.last_byte_offset`
   where file_path comes from the session map (or scan) while the tracked
   offset/watermark belong to `session.file_path`; they are never
   re-synced when a session's transcript moves (worktree resume:
`pyteman/.claude/worktrees/*` publishes a different project-dir path; live
   proof: session_map still points 0942e19d at a now-MISSING worktree
   project file while tracked state points at the real 76MB main file).
   Sizes of two different files minus an offset of one of them is nonsense;
   it can hold the gap above the cap forever (retry storm) or skip ranges
   that were never read.

Fix: (a) reuse the existing skip-retry backoff for failed auto-skip
attempts (throttle per session); (b) before the gap check, compare
str(file_path) with session.file_path: on mismatch, log once (throttled)
and decline the auto-skip; the replacement/rekey machinery owns path
changes, not the cap heuristic. Tests: mismatched paths never trigger a
skip; a failing snapshot throttles to the backoff curve.

## Review outcome (2026-09-20, code-review high)

Shipped plus review hardening: the same-file verdict resolves both paths
(symlinked spellings of one file no longer disable the cap), env knobs
parse through a tolerant _env_float with clamps (empty or non-numeric
values previously crashed the process at import; 0 no longer silently
disables the throttle), the once-per-session mismatch log is instance
state retired with the session, and the three sibling test fixtures that
had been passing vacuously through a swallowed AttributeError now carry
the real attributes. FOLLOW-UP (accepted debt): nothing rebinds
TrackedSession.file_path for a live session after a real path change, so
manual /skip and _settle_all_sessions_at_eof keep using the stale tracked
path; adoption machinery should own that rebind. The flat 30s throttle
after a single transient None delays barrier formation while the source
keeps being read (the read path has no cap): documented tradeoff.
