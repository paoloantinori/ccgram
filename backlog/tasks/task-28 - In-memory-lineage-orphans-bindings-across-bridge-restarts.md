---
id: TASK-28
title: In-memory lineage orphans bindings across bridge restarts
status: Open
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
