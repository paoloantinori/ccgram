---
id: TASK-42
title: 'TASK-128 (local_ai backlog): host-side admin channel for topic lifecycle'
status: Done
assignee: []
created_date: '2026-09-22 15:30'
updated_date: '2026-09-22 15:30'
labels: [feature, upstream, delivery]
dependencies: [TASK-40]
---

## What was asked (from the Mac, 2026-09-22)

ccgram admin bind|unbind|sync|rethread on the host, reusing
thread_router/topic_deletion code paths from the process that owns the
state, never touching getUpdates/polling, explicit arguments only.
Workflow: upstream PR like 263/264, deploy Mac via uv tool, notify
local_ai.

## What shipped

- src/ccgram/admin.py: the channel (submit/read/execute/consume) with
  the four commands through the real code paths; files 0600.
- src/ccgram/admin_cmd.py + cli.py: the `ccgram admin` group.
- bootstrap.py: 1s consumer task, starts at EOF (no replay across
  restarts), survives failed passes, stopped in post_stop and reset in
  tests.
- Code-review high: 9 findings; the HIGH (history replay on restart)
  and three MEDIUMs (loop death, unbind --delete masking the retire
  outcome, bind masking UNKNOWN liveness) fixed in the same commit;
  legacy-binding sweep in rethread; offsets concern refuted (keyed by
  window, not thread).
- Fork: commits 96200ce1 (forensics, separate) + 6ec9b304 (admin),
  battery 7352. Upstream: issue #276 + PR #277 (branch
  feat/admin-topic-lifecycle, battery 7293).
- Deployed: bird first sync closed 5 dead topics; Mac tool venv
  rebuilt from 6ec9b304 (uv lives at /opt/homebrew/bin on the Mac),
  consumer verified, first sync closed 5 more; 12 legacy issues remain
  on the Mac by design (explicit retirement only). local_ai notified
  via herdr as requested (usage examples included).
