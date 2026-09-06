---
id: TASK-23
title: Eternal-replay damper follow-up: verified done-by-adoption
status: Reopened
assignee: []
created_date: '2026-09-04 19:30'
updated_date: '2026-09-04 19:30'
labels: []
dependencies: []
---

## Description

The 2026-08-30 incident's structural fix ('replay damper / incremental watermark commit', filed 8/30 in the lost backlog) shipped as our settled-prefix incremental commit (2f00e81), merged upstream as PR #207, and lives in the current tree (session_monitor.py 'Commit each session's longest settled receipt run (#205)'). No work remains; the manual unstick procedure stays in project memory for old-offset emergencies.

REOPENED 2026-09-06: the "done-by-adoption" closure was premature. The
incremental settled-prefix commit (#207) fires only when receipts
settle, and under the escalated group rate penalty of 2026-09-06 they
never did: nine sessions kept up to 52MB unsettled and six restarts
starved every live topic (second occurrence of the family). Structural
work moved to TASK-29 (replay cap) + TASK-30 (round-robin fair
scheduling); the manual advance runbook in project memory remains the
operational unstick and was validated again.
