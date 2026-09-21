---
id: TASK-40
title: Dead-session topic deletion ignores operator intent; replay cap 1MB too tight
status: In Progress
assignee: []
created_date: '2026-09-21 22:40'
updated_date: '2026-09-21 22:40'
labels: [incident, fork, ux]
dependencies: []
---

## Incident (2026-09-21, user report "something still off, here and on the Mac")

Bird: 17 topics auto-created and 14 auto-deleted in one day (4 the day
before, 0 before that). The group visibly flashed topics all afternoon.
Mechanism, verified line by line: an agent re-key changes its herdr
digest; the old digest leaves the reconciliation listing;
_handle_dead_window_notification sees window_presence False and calls
_delete_dead_topic_immediately (apply.py), which deletes the topic with
NO knob. The re-keyed digest then surfaces as unbound and a new topic
is auto-created for it. The durable-alias fold (TASK-28) cannot
intervene where several live panes share the cwd (11 of 14 deletions
were pyteman topics; three live pyteman panes; the ambiguity guard
correctly refuses to fold). The AUTOCLOSE_* envs in .env are dead
configuration from the pre-4.9 era: no code reads them.

Second finding: the anti-vocale session (86MB transcript, no persisted
watermark) re-formed a 1MB unsettled gap every ~2h and tripped the
TASK-29 auto-skip 20 times in two days (plus 4 on the Ccgram-mac
worktree session). Default cap 1MB is sized for restart replay, not
live high-volume flow.

## Fixes

1. Config: CCGRAM_REPLAY_CAP_MB=16 in bird .env (backup taken). Restart
   verified clean.
2. Code: CCGRAM_AUTODELETE_DEAD_TOPICS knob (default true = current
   upstream behavior; false in bird .env). When false, a confirmed-dead
   window keeps its topic and binding: the recovery banner still
   answers the next message, and reconcile_window_aliases can fold the
   binding onto a re-keyed successor digest, which deletion made
   impossible. Parametrized test both branches through
   _handle_dead_window_notification.

Mac: unaffected decision, its incident is the legacy session_map keys
(owned by ccgram-mac + local_ai with an agreed plan).

## Definition of done

Battery + lint + pyright green; code-review high on the diff; commit
with gates; push mine/fork/main; deploy bird and verify the knob is
read (log line dead_session_topic_retained on the next re-key, no
further topic deletions); upstream contribution only after explicit
user approval (not covered by earlier blanket).
