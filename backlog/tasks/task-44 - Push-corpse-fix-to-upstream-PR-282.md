---
id: TASK-44
title: Push the scheduler corpse fix to upstream PR #282 (branch carries the 7h-wedge bug)
status: Done
assignee: []
created_date: '2026-09-27 17:05'
updated_date: '2026-09-28 10:12'
labels: [upstream, fork, ratelimit]
dependencies: []
---

## Context

PR #282 (feat/interactive-priority-lane) is open upstream and its
scheduler has the unfixed corpse bug diagnosed in TASK-43: a
cancelled parked waiter stays in the deque and the pump burns one
real token per corpse, starving the background lane with zero logs.
Verified on 2026-09-27: the branch's telegram_rate_limiter.py has the
old "The pump never saw us; nothing to clean" handler.

## Prepared

Commit 09b2bb0a on feat/interactive-priority-lane (worktree
/tmp/ccgram-pr-prio, local only): the corpse removal + pump guard +
red-green regression test, cherry-applied from d60ebc6e; the branch's
scheduler test files pass 13/13 with it (after a clean `uv sync
--extra dev --reinstall`; the worktree venv was broken, missing
telegram._bot).

## Gate

Blocked on the maintainer's explicit approval to touch the upstream
surface. On approval: `git push` the branch; no PR comment needed
unless the maintainer wants the incident called out in the PR
description (any comment passes /pstack:unslop first).

Done 2026-09-28: maintainer approved ("okay per pushare i fix");
09b2bb0a pushed to feat/interactive-priority-lane on the fork
(087e60ea..09b2bb0a), PR #282 now carries the fix. PR remained
MERGEABLE against upstream main; no rebase needed (verified: all
seven open PRs merge cleanly, six BLOCKED awaiting maintainer, #283
CLEAN).
