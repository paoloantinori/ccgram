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

## Progress (2026-09-21 23:35)

Both fixes shipped as 94ba59d2 (pushed mine/fork/main, deployed bird,
venv verified, service clean). Code-review high ran (agent pass): gate
placement, marker semantics, mutation-sensitive test, fold-recovery
ordering verified; its Medium (retain path re-probed and re-logged
every poll cycle once the finally cleared the marker) and Low
(retired-topic drain ignoring the knob) both fixed in the same commit:
the dead-marker stays sticky on the retain path and the drain is
gated. Env plumbing proven end-to-end (module probe read False from
the live .env before deploy). Remaining observation: the first real
agent re-key should log dead_session_topic_retained and produce NO
deletion; auto-skip fires on the anti-vocale should stop (cap 16MB).

## Mac closure (2026-09-22, cc-config handoff, verified by bird)

Mac redeployed on fork/main feadb4ef (4.11.3.dev39, tool install with
ext), env knobs applied with backup, all three code markers verified in
the tool venv by bird independently. Re-key done on four panes
(local_ai, mnemosyne, hermes-fleet, scalpel) with real SessionStart and
new topics 16956/16976/16982/16998; planner pending its idle. The five
legacy wN:t1 keys stay retained (they predate the digest era: the Mac
ran ccgram 4.3.11 until Sep 21, which is where those keys and the
[14,15,16] protocol set came from); the durable fold cannot map them
because they are not herdr-session-v1 digests, so those five topics are
replaced by the new ones, not re-linked. Zero deletions since the knob
landed (the one cleanup line in the log predates today's redeploy).
Also found by cc-config: the Mac guard's pgrep matches the operator's
ssh command line containing 'ccgram' (double-kickstart race); the
durable fix is a time gate or concatenated label, owned by cc-config
with the guard script.


Battery + lint + pyright green; code-review high on the diff; commit
with gates; push mine/fork/main; deploy bird and verify the knob is
read (log line dead_session_topic_retained on the next re-key, no
further topic deletions); upstream contribution only after explicit
user approval (not covered by earlier blanket). APPROVED and
sent 2026-09-22: issue #272 + PR 273 (branch
fix/autodelete-dead-topics, 6a82ff13, battery 7278).
