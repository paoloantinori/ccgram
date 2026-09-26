---
id: TASK-43
title: Per-user delivery queue worker wedged silently for 7 hours (2026-09-26 incident)
status: In Progress
assignee: []
created_date: '2026-09-26 17:35'
updated_date: '2026-09-26 17:35'
labels: [incident, fork, diagnosis, pyteman-repro]
dependencies: []
---

## Incident

2026-09-26, roughly 09:34 to 16:40 local: the per-user delivery
queue stopped delivering for the user across ALL topics (anti-vocale
reported by the operator; /screenshot still worked because it does
not go through the delivery pipeline). The monitor loop kept running
(reading other sessions, skipping enqueues for closed windows). The
anti-vocale transcript kept growing to 62.3 MB while its delivery
offset froze at 60.5 MB (1.8 MB unsettled). ZERO journal lines for
the affected window between 09:34:45 (last interactive UI send) and
the operator-forced restart at 16:40, which unblocked delivery
immediately (offset settled at EOF via skip-backlog-on-start).

## Evidence collected before the restart destroyed in-memory state

- Last window activity: interactive UI send 09:34:45; before that,
  "Delivery queue still draining before interactive UI; proceeding"
  09:14:55 (the PR #263 join-bound path with the 90s budget), and
  rate-limit retries on sendMessage/editMessageText 08:55-08:56.
- The worker was NOT respawned (no "Respawning dead queue worker"
  warning), so the task was alive: awaiting something indefinitely.
- Worker structure (message_queue.py): exceptions are caught and
  logged at every level (dispatch, worker loop); a hang therefore
  must be an await that never resolves, not an exception path.
- Candidates for an indefinite await with no log line:
  (a) the send awaiting the group rate-limiter scheduler token
  forever (deployed 2026-09-25, c803e2a9: _PriorityGroupScheduler
  pump wraps the aiolimiter bucket; a pump death or missed wakeup
  would stall exactly like this),
  (b) an HTTP request without effective timeout inside the send,
  (c) the interactive-join path holding the worker.
- Timing correlates with the priority-scheduler deploy (first full
  day of production traffic under it) AND with an interactive
  session the operator was actively driving.

## Plan (pyteman-first, per the tool's purpose)

Build a headless reproduction harness with pyteman fault injection
on the delivery-path seams: rules that stall/kill at
_message_queue_worker dequeue, _dispatch_with_retry entry,
CCGramAIORateLimiter.process_request entry, the scheduler pump's
limiter acquire, and the send itself. Sweep one seam at a time;
the signature to match is: worker task alive, zero deliveries, zero
log lines, offset frozen. The seam that reproduces the signature
names the root cause; then a regression test and the fix.

## Progress (2026-09-26 evening)

Reproduction infrastructure built and the wedge class isolated:
- Headless harness (/tmp/freeze-repro/harness.py): stands up the real
  per-user queue + worker with ContentTasks; signature = worker alive,
  zero sends, pending intact, zero log lines.
- Seam sweep results: (a) group-scheduler token stall does NOT match
  alone (first send flows; merged sends complicate, not conclusive
  exoneration); (b) never-resolving await inside _dispatch MATCHES;
  (c) per-user queue lock never released MATCHES.
- Wedge class: a never-resolving await inside the dispatch chain, or
  an equivalent lock leak (which itself requires a hang inside the
  lock body; async-with releases on exceptions).
- Saturation ruled out: rate_limit_send serializes the group at
  3.1s/message, but the offset stayed EXACTLY frozen for 2+ hours;
  saturation would advance it slowly.
- pyteman note: 0.2.x refuses coroutine targets for entry/exit
  injection (SuspendableTargetError on AsyncLimiter.acquire), so
  async seams are monkeypatched directly in the harness; pyteman
  remains the tracer for sync seams when needed.

Next: enumerate every await reachable from _dispatch (content path:
_handle_content_task, _flush_batch_for_task; status path: coalesce
under lock, process_status_update; shared: rate_limit_send_message,
edit_with_fallback, PTB send, CCGramAIORateLimiter.process_request
including my scheduler pump and the RetryAfter retry loop) and find
which can await unboundedly in production. Prime suspects given the
timeline (interactive session + join-budget expiry at 09:14, then
total silence): something in the interactive-join neighborhood
holding the per-user lock or an in-flight send that never settles.

## Definition of done

Reproduction harness + ruleset in repo (or as a documented script if
too synthetic for the suite), root cause named with mechanism, fix
with regression test, battery, deploy both bridges.
