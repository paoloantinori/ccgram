---
id: TASK-27
title: Quiet topic titles and simple naming (ccbot model)
status: Done
assignee: []
created_date: '2026-09-06 12:10'
updated_date: '2026-09-06 12:10'
labels: []
dependencies: []
---

## Description

The user wanted ccgram's topic titles closer to ccbot: less advanced,
less noisy. Three noise sources found: the herdr discovery chain
(Provider ▸ workspace ▸ tab ▸ pane, three dead segments), the creation
counter names, and the state machinery rewriting titles on every
transition (the editForumTopic flood family exists FOR this noise).

Delivered 2026-09-06:
- Core: CCGRAM_TOPIC_EMOJI=off gates EVERY title writer (topic_emoji's
  two, plus the four creation/bind/recovery/resume renames via the
  shared title_writes_disabled() helper; wrapped conditionally because
  three sites have success UI after the rename; two noqa for ruff's
  complexity cap). State stays in the status bubble.
- ccgram-ext: [topic-names] style = "ccbot" names each newly bound
  topic once (cwd basename, per-chat counter on collision), mirroring
  core's manual-rename path including session display-name alignment;
  /names dry-runs, /names apply renames all bound topics, paced and
  flood-coordinated with the icons pass.
- Gates: code-review agent (5 points; all findings applied: the four
  ungated writers, display-name alignment race, RetryAfter pause,
  per-chat collision scope, honest totals on flood skip, degenerate
  guards); /simplify inline; battery 7058 + ext 39; pyright 0.
- Config armed on bird (backups first): CCGRAM_TOPIC_EMOJI=off in
  ~/.ccgram/.env, [topic-names] in toolbar.toml.
