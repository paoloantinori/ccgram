---
id: TASK-185
title: Reuse a reopened workspace's topic instead of duplicating it (family rebind)
status: Done
assignee: []
created_date: '2026-10-29 08:20'
updated_date: '2026-10-29 08:20'
labels:
  - kind/reliability
  - kind/ux
dependencies: []
references: []
priority: high
ordinal: 100
---

## Problem (maintainer directive 2026-10-29)

Reopening a session/workspace on a machine churns the herdr agent session
composite, so a NEW window digest appears. Adoption created a duplicate
topic (the "X", "X 2", "X 3" proliferation and the duplicate sync) while
the old topic stayed bound to the dead digest forever. The alias fold
(`SessionManager.reconcile_window_aliases`) heals it only when an alias
is attested, and `prune_session_map` usually deletes the dead digest's
entry before any durable fold can fire, so the heal never arrives.

## Fix (handlers/topics/family_rebind.py, new module)

At automatic adoption time, before creating any topic: exactly one dead
binding (window id gone from the confirmed listing) whose resolved
(cwd, provider) family matches the new live topic-eligible window means
the new window is that topic's agent back. The topic is rebound via the
shared `_bind_topic_to_user` write, the monitor is seeded at EOF when
the new hook entry is known (seed-before-bind closes the replay window),
and ONE direct notice lands in the topic (byte count skipped, or
pending-session form when no entry exists yet, in which case
orphan_watch's relink and the restart replay cap own the backlog).
Zero or 2+ candidates keep today's behavior. The decision plus bind is
serialized by a module lock so two same-family reopenings in one batch
cannot both steal the one dead topic. Idempotent: a second pass finds
the binding live and exits at the existing already-bound check.

`still_adoptable` became `confirmed_adoption_listing` (returns the
listing it judged, handed down so eligibility and family matching share
one liveness truth); `still_adoptable` deleted, callers migrated. The
two triggers are documented side by side in the module docstring
(orphan_watch: live window, dead session entry; family_rebind: gone
window id, new digest for the same family).

## Gates and verification

Suite 8251 (17 new tests: pure matcher, flow scenarios, concurrency,
fold-ordering, fail-closed paths), ruff format/check clean,
lint_lazy_imports clean, pyright 0 errors on touched files. /simplify 4
reviewers (8 findings applied after dedup, 3 declined with reasons),
/code-review high effort (8 findings: 5 applied, 3 declined with
reasons). Side finding filed: pre-existing test-isolation leak
test_new_window_sync -> sync audit (TASK-186).

2026-10-31 append: the rebind also refuses when a live same-family sibling
((cwd, provider) pair, state-then-map facts, casefolded provider) already
serves the family; a live window of a different provider on the same cwd is
not family and must not block the reuse (skeptic-refuted hole, closed with
regression tests).
