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

Added 2026-09-21: PR 266 (fix/expired-interactive-escape, closes #256,
the interactive dismissal reordered above the pane send; found while
preparing the PR that the shipped order sent the text into the pane
first). The dispatched adversarial reviewer died without completing
(no notification, task record gone after the compaction); replaced
by a targeted inline verification of the fold (logic, write-through
under lock, anti-loop guards, PEP 758 floor matches upstream
requires-python >=3.14, 2x battery 7280 on the branch). Posted:
issue 267 + PR 268 (fix/durable-session-aliases, closes 267) on
2026-09-21. PR family now 263/264/265/266/268.

Greptile round 2 (2026-09-21 10:10-10:23 UTC), all answered inline:
- 266 P1 Escape literal: CONFIRMED (literal=True types the word +
  Enter into the modal). Fixed on the branch (1c7ef173, additive)
  and on the fork (8fdf1ddb, battery 7328, stamp, bird redeployed
  and verified). Fork production ran this bug since 866eedf1.
- 268 P1 PEP 758 syntax: REFUTED (upstream requires >=3.14, same
  form in session_monitor/hook/screen_buffer/session_map).
- 268 P1 unrelated-merge: data-loss half refuted (setdefault keeps
  the live entry on collision); adoption semantics defended as the
  issue's own proposal, config-flag opt-in offered to the
  maintainer.
#245 gets NO PR: the maintainer took the design and fix on the
maintainer side on 2026-09-13.

Remaining: watch for maintainer or bot feedback (reviews, inline
comments, CI), answer every substantive comment, iterate to merge or
close. When a maintainer requests changes, prefer additive commits over
force-pushes. Note: the session-only watcher in the Ccgram-mac session
polls every 9 minutes; if that session is gone, poll with gh on resume.
