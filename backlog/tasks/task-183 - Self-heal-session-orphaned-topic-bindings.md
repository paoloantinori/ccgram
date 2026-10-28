---
id: TASK-183
title: Self-heal session-orphaned topic bindings (orphan watch)
status: Done
assignee: []
created_date: '2026-10-28 17:50'
updated_date: '2026-10-28 17:50'
labels:
  - kind/bug
  - kind/reliability
dependencies: []
references: []
priority: high
ordinal: 100
---

## Incident (2026-10-28, two days mute)

hermes-fleet on the Mac went silent: herdr window ids are STABLE across
session churn (the digest covers the pane composite, not the session
uuid) but the session_map entry had been swept by cleanup when the
container's session changed without a hook update, leaving the bound
topic pointing at a live window with no session pointer. Nothing read,
nothing alerted. Manual cure: recreate the entry at the stable digest
pointing at the live session uuid + transcript, seed monitor offset at
EOF (surgery of 2026-10-25, repeated).

## Fix (fork/main d41184a2, deployed both bridges 2026-10-28)

handlers/polling/orphan_watch.py rides the 60s topic-check gate after
check_delivery_wedges: detects bound live windows whose session_map
entry is missing or whose session_id is no longer live, relinks to the
single fresh unclaimed transcript in the cwd-encoded project dir when
unambiguous (backup + EOF seed + write through the v1 serializer),
posts ONE direct notice per incident naming topic, old and new session,
journal WARNING per incident. Knobs CCGRAM_ORPHAN_WATCH and
CCGRAM_ORPHAN_AUTO_RELINK, both default on. Known limits: a same-cwd
operator session inside the 900s freshness window can in principle be
chosen (notice names the winner; rolling backup kept); idle orphans
stay notice-only until their agent writes again.

## Related open threads

- Mac herdr daemon instability ("herdr socket transport failed:
  Connection lost" bursts on agent list / pane reads, 2026-10-28):
  av-mac/local_ai lane.
- The Mac's startup is slow (extension line ~80s after start) due to
  the retained-keys reconciliation burst: cosmetic, watch only.
