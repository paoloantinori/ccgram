---
id: TASK-28
title: In-memory lineage orphans bindings across bridge restarts
status: Done
assignee: []
created_date: '2026-09-06 16:05'
updated_date: '2026-09-06 16:05'
labels: []
dependencies: []
---

## Description

Diagnosed live 2026-09-06: herdr agents that re-key their session
(/clear, --resume) mint new digests; the alias/lineage machinery that
should fold bound topics onto the new digest is IN-MEMORY ONLY
("In-memory only, like _provisional_targets" in the herdr adapter).
When the bridge restarts in the window between re-key and reconcile,
the lineage is empty and the binding gets swept as stale. Today: three
bridge restarts while agents ran turned 26 bindings into 7; the hassio
topic (agent alive, third identity) was orphaned and its /names apply
skipped it. Recovery is one message in the topic (dead-window banner ->
resume -> rebind, and the ext now auto-names on that bind).

Gap is upstream-owned (the lineage design is theirs). Internal options
if it recurs: persist supersession aliases into window_states (the
2026-08 port-4.6-incident manual procedure, automated), or make the
startup sweep resolve by session_id via session_map before unbinding.
Any upstream conversation stays on hold per user decision.

FIXED 2026-09-06 (commit 1b012df1): reconcile_window_aliases folds, in
addition to the in-memory lineage, aliases the persisted session_map
attests alone (dead digest -> unique live digest on the same full
(cwd, provider); ambiguous workspaces never fold). Production-proven
on the deploy restart itself: the hassio binding survived a bridge
restart with the re-keyed agent, which was exactly the failing
scenario. Review 4/4 + ambiguity-guard test; battery 7063.

REGRESSION FOUND 2026-09-21: the v4.11.2 replay (27-commit
cherry-pick series) dropped this feature during conflict resolution
and the restore commit 27163ee5 did not list it among the four
restored features (its title named TASK-28 but the durable fold was
not in it). fork/main ran without the fold from the replay until
today. RESTORED same day as commit c18d40c8 (cherry-pick of 033fe1ae
with a trivial end-of-file test conflict resolved): battery 7328
passed, session tests 149. Lesson applied: when a replay commit's
title claims a task, verify the FEATURE not the title (grep the
symbol) before calling the restore complete.
