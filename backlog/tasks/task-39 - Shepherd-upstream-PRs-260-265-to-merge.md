---
id: TASK-39
title: Shepherd upstream PRs 263/264/265 (issues 260/261/262) to merge
status: In Progress
assignee: []
created_date: '2026-09-20 22:52'
updated_date: '2026-09-20 22:52'
labels: [upstream, review]
dependencies: []
---

## Description

Three contributions opened on alexei-led/ccgram on 2026-09-20, each
one commit on top of upstream/main 0d2e395e (v4.11.2), each closing its
issue and passing the checklist (make test, make lint, one thing, test
added):

- PR 263 fix/interactive-join-bound closes #260 (global monitor stall
  on unbounded queue.join in the interactive path; final design: 90s
  total budget plus the respawning getter).
- PR 264 fix/conflict-exit-watchdog closes #261 (wedged shutdown leaves
  a live mute process; final design: daemon threading.Timer armed in
  post_stop, cancelled in post_shutdown, 600s, captured-monitor save).
- PR 265 fix/skip-barrier-deadline closes #262 (pending skip barrier
  pauses a source forever; created_at stamp, conservative expiry,
  config.py knob with non-finite fallback). Related to #245.

Already handled (do not re-triage): Greptile inline P1 on 263 (qsize
misses in-flight), P1 on 264 (watchdog shares the blocked loop), P2 on
265 (inf deadline): all confirmed, fixed on the branches (force-push),
replied inline citing the commits. CI green on all three, MERGEABLE.

Remaining: watch for maintainer or bot feedback (reviews, inline
comments, CI), answer every substantive comment, iterate to merge or
close. When a maintainer requests changes, prefer additive commits over
force-pushes. Note: the session-only watcher in the Ccgram-mac session
polls every 9 minutes; if that session is gone, poll with gh on resume.
