---
id: TASK-29
title: Cap the replayable backlog per session (kills the eternal-replay loop)
status: Open
assignee: []
created_date: '2026-09-06 20:30'
updated_date: '2026-09-06 20:30'
labels: []
dependencies: []
---

## Description

2026-09-06 incident (second of the family, see reopened TASK-23): nine
sessions carried unsettled backlogs up to 52MB; six bridge restarts +
an escalated group rate penalty (429s from 01:10, retry_after rising
5s->12s->17s) stalled settle, and every restart replayed the whole
unsettled mass into the single per-user FIFO: live topics starved for
hours. Manual runbook (advance offsets, backup first) restored flow.

THE FIX: bound the replayable backlog per session in the monitor's read
path. Beyond the cap (proposal: 1MB or N=200 messages, whichever
first), fast-forward the watermark past the excess and deliver ONE
notice ("N messages skipped, /history to read them"). Effects: replay
mass bounded, drain time bounded, rate pressure bounded, settle can
progress again. Design note: this deliberately trades at-least-once
completeness for liveness on stale content; fresh content (under the
cap) keeps at-least-once.

Placement: session_monitor read/parse path (upstream-owned; conscious
fork debt, same class as the four seam lines). Config-gated
(CCGRAM_REPLAY_CAP_MB, default on at 1MB; 0 disables).
Gates: full battery + /simplify + code-review; live verification must
include a restart with a fabricated >cap gap.
