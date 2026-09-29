---
id: TASK-46
title: New-session launch died during dead-window reconciliation (2026-09-29 09:11)
status: Open
assignee: []
created_date: '2026-09-29 09:30'
updated_date: '2026-09-29 09:30'
labels: [incident, herdr, recovery, launch]
dependencies: []
---

## Incident

2026-09-29 09:11: creating a new session from Telegram failed with
"Session did not register with ccgram and is gone". Single occurrence
so far.

## Evidence (journal, 09:10:50 to 09:11:18)

- 09:10:50 dead window c1e2aeef (Claude > minix_ansible_config > p1)
  shown the recovery UI.
- User acted on the recovery flow; a new window b5e1b596 was created.
- 09:11:15 the "dead" pane RESURRECTED under a new identity
  (reconciled c1e2aeef -> 2861c4d3) and ccgram deleted the old id.
- 09:11:18 wait_for_session_map_entry timed out for b5e1b596 and
  window_presence returned False: the new pane was not merely
  unregistered, it was GONE. The flow reaped it and showed the error.

## Hypothesis

The new pane was killed by the reconciliation/deletion churn of the
resurrecting sibling window (same workspace/tab neighborhood), not by
a launch failure: at 09:11:15 the old window's identity superseded
while the fresh pane was mid-registration, and some cleanup path
(tombstone sweep, tab consolidation, or _finish_failed_provisioning
of the superseded id) closed it.

## Already refuted (2026-09-29 diagnostics)

Not a zai-configuration problem: CCGRAM_CLAUDE_COMMAND=zai resolves
through the provider registry; the wrapper is on the service PATH and
exports the zai CLAUDE_CONFIG_DIR; zai settings.json carries all
ccgram hooks (rewritten by the 2026-09-28 21:59 sync, intact); the
hook binary writes session_map from a claude-shaped payload; and a
live end-to-end probe (fresh herdr tab, pane run zai) started Claude
Code v2.1.284 on GLM-5.3 and registered within seconds.

## Verification plan

Reproduce via the suspected path: kill or stale a window, wait for
the recovery banner, then tap the recovery action while the dead pane
resurrects, and watch whether the new pane survives. Discriminant to
capture from any recurrence: recovery-banner flow vs plain /new. If
the race is confirmed, the fix belongs in the creation-vs-reconciliation
interaction (pending-creation guard or supersession sweep sparing
in-flight panes).

## Definition of done

Reproduced or three failed attempts to reproduce documented; if
reproduced, root cause named with mechanism and fixed with a
regression test.
