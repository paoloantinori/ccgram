---
id: TASK-18
title: File the limiter-bypass upstream (6e0f6c6; trigger condition fired)
status: On Hold
assignee: []
created_date: '2026-09-04 19:30'
updated_date: '2026-09-04 19:30'
labels: []
dependencies: []
---

## Description

TopicEditAwareRateLimiter (PTB per-group bucket starves editForumTopic behind a busy outbound queue), local fix 6e0f6c6 on the pre-reset tree. Filing condition was 'when the #199/#205 conversation starts': both issues were closed via our merged PRs #206/#207 on 2026-08-31. Recover the fix from old history (14c727a lineage), re-evaluate against current upstream delivery core (v4.9.6+ hardened it five times; the starvation may be gone), then file or close. Blocked on user approval for anything upstream.

ON HOLD (user decision 2026-09-04): no upstream pushing. Reopen only if the candidate becomes particularly uncontroversial or the user explicitly changes their mind. Drafts and artifacts stay in fork territory.
