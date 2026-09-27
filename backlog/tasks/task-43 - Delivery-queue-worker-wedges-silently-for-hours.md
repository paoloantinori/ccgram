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
  forever (c803e2a9, in production from 08:12 on 2026-09-26:
  _PriorityGroupScheduler
  pump wraps the aiolimiter bucket; a pump death or missed wakeup
  would stall exactly like this),
  (b) an HTTP request without effective timeout inside the send,
  (c) the interactive-join path holding the worker.
- Timing correlates with the priority-scheduler deploy (the freeze
  began ~82 minutes after the swap onto it) AND with an interactive
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

## Static elimination matrix (2026-09-26 evening, second pass)

Every await reachable from _dispatch has been read and is bounded;
every exception path logs. Eliminated as the sole cause:
- All queue.join() callers (routing interactive join: wait_for 90s at
  message_routing.py:206; shutdown drain: wait_for drain_timeout at
  message_queue.py:1362). The join neighborhood is exonerated.
- ResilientPollingHTTPXRequest (telegram_request.py): no retry loop;
  single attempt, reset+raise; reset lock body sync; close shield
  bounded by timeout(1.0). Exceptions propagate to dispatch which
  logs them.
- _ShardedUserQueue.get (message_queue.py:155): clear/pick/wait with
  no await between clear and wait; single consumer per user (single
  worker; get_or_create_queue respawns only when done). The classic
  lost-wakeup requires pick to miss a present item; put_nowait is the
  only adder and always sets _wake.
- _coalesce_status_updates / _merge_content_tasks / purge paths: hold
  the per-user lock over SYNCHRONOUS drain/refill bodies only.
- rate_limit_send (message_sender.py:97): per-chat lock held over a
  bounded sleep (3.1s group interval).
- DraftStream: failure counters + TTL, bounded HTTP.
- Facade task_done/_unfinished ledger: accounting drift can hang
  join() but all joins are wait_for-bounded; drift cannot stop the
  worker itself.
- PTB send chain: HTTPXRequest timeouts (connect/write/read 10s).

Conclusion: the 7h silent wedge is NOT reproducible as a single
unbounded await in any path read; it requires either a state-
corruption variant invisible to static reading (lost wakeup or
accounting under a specific interleaving) or an await in PTB/
uncommon dispatch branches not yet reached. The discriminating next
step is the instrumented full-chain harness (real _dispatch + fake
transport scripted to hang/raise per scenario) with per-seam entry
tracing, which becomes practical at scale with pyteman TASK-178
(entry events on coroutine targets). Seam (b) and (c) of the stub
sweep remain the signature templates the instrumented run must
match.

## Instrumented findings (2026-09-26 night)

pyteman TASK-178 landed; harness swapped to real rulesets for entry
tracing (verified firing on async _dispatch in the foreign-project
embedding). Two results:

1. pyteman sleep action is time.sleep: on coroutine targets the
   stall BLOCKS the event loop. Wrong shape for this wedge (loop
   must stay alive); follow-up filed by pyteman as TASK-181. Harness
   keeps the monkeypatch for the hang itself.

2. Double-worker race (get_or_create_queue has no lock around
   check-then-spawn; monitor + PTB handlers both call it): 30-round
   interleaved sweep (content+status, 0.25s windows) shows FACADE
   LEDGER LEAK under worker cancellation mid-dispatch. Mechanism:
   coalesce/merge DRAIN sibling tasks out of the shards (their
   put_nowait already counted +1 on _unfinished); the compensating
   task_done calls run in the DISPATCH path AFTER the drain
   (message_queue.py:823/831, dropped compensation; merge
   compensation); a worker cancelled between drain and compensation
   skips them, so _unfinished never returns to zero and the _drained
   event (join authority) never sets again for the process lifetime.
   Production corroboration: "Shutdown drain timeout: 2 queued
   task(s) remain" in the 2026-09-20 journal is this leak observed
   live. Join callers are wait_for-bounded, so the leak alone does
   not stop DELIVERY; it corrupts the join signal until restart.

   RETRACTED (2026-09-27, before any commit): the merge leak does
   not exist. Merged siblings ARE compensated via
   dispatch_state.extra_task_done, settled in _dispatch_with_retry's
   finally (message_queue.py:1006). My sweep's cancellations landed
   inside THAT finally's window, and my first fix double-compensated
   (ValueError: task_done called too many times proved the original
   accounting right). Code reverted, test removed, nothing shipped.
   The coalesce drop compensation (dispatch-path, after the lock's
   atomic return) stands as correct by the same analysis.

   Remaining real candidate for the 7h silence: a worker alive but
   parked forever on one await. The extra_task_done finally gives a
   NEW window worth instrumenting: cancellation between the drain
   (inside _merge_content_tasks) and the finally compensation is
   handled, but a HANG (not cancel) of process_content_task between
   them leaves the ledger high and the worker wedged with zero
   sends - the exact signature. So the hunt narrows to: what can
   hang _process_content_task / process_status_update mid-flight in
   production with every HTTP timeout at 10s? Next: entry tracing
   (pyteman rulesets now firing on coroutine targets) around those
   two functions in the full-chain harness.

## Root cause found and fixed (2026-09-27)

The 7h-silent wedge is the _PriorityGroupScheduler waiter-corpse bug
(c803e2a9, committed 2026-09-26 08:09; service swapped onto it
08:12 per the journal; freeze began 09:34, about 82 minutes of
production exposure). Mechanism, traced end to end and verified
experimentally (tools/diagnostics/task43: limiterstack.py,
limiterstorm2.py, corpseasym.py):

- acquire() parks a future in one of two deques. A requester cancelled
  while parked left its cancelled future in the deque (the handler's
  old comment "the pump never saw us; nothing to clean" is wrong).
- The pump pops each future in FIFO order and BURNS a real token on a
  corpse: `await self._limiter.acquire()` runs before the done-check,
  so each corpse costs one token, 3s under flood saturation (group
  bucket 20/60), with ZERO log lines.
- Verified numbers: 60 cancelled parked waiters froze the background
  lane for 185.7s while an interactive send was served in 2.5s;
  worker alive, zero logs, pump alive. This is the incident
  fingerprint: /screenshot (interactive lane) worked while queue
  delivery starved (background lane), 09:34-16:40, offset frozen
  exactly.
- Incidence sources in production (all verified reachable): burst at
  the end of the operator's interactive session 09:14-09:34 (arrow-key
  debounce cancels in status_bar_actions, bash-capture cancels, draft
  TTL aborts cancelling parked draft flushes whose payloads carry
  chat_id, join-budget expiry), plus draft abort on every completed
  assistant turn under flood saturation.

Fix (this turn): acquire()'s CancelledError handler removes the
waiter from its deque before re-raising; the pump's done-check stays
as a lost-race backstop and no longer carries the token-burn branch.
Removal exposed a second latent path (found by /simplify round +
pumpautopsy.py probe): with corpses actually removed, total waiter
cancellation while the pump awaits its token leaves both deques empty
at wake time and the pump died on popleft(); guarded with an
empty-deque re-check so the pump exits cleanly. Red-green verified:
new regression test
test_cancelled_waiter_burst_leaves_no_corpses fails on old code
(both without corpse removal and without the pump guard), passes on
fixed; post-fix probes show corpses_in_deque=0, background
service 5.7s (was 185.7s), interactive 2.5s unchanged, pump-kill
respawn unchanged.

Honest residual: the corpus of corpses observed in the frozen window
must have been replenished for 7h (an isolated burst drains at
3s/corpse); the restart destroyed the in-memory deques, so the exact
replenisher mix over 09:34-16:40 is unrecoverable. The fix removes
the scheduler's vulnerability to ALL of them (a cancelled waiter no
longer lingers), so no replenishment rate can sustain a wedge in this
class. Known bound, accepted deliberately (code-review 2026-09-27):
the cancellation-path cleanup is a deque.remove, O(n) per cancelled
waiter, quadratic under a mass-cancellation storm of thousands of
parked waiters; the scan is C-level identity comparisons on a cold
path, and the storm size that would make it hurt is the storm the fix
itself defuses. Revisit only if a probe ever shows scheduler-cleanup
time mattering. Deployment on both bridges follows the DoD.

Battery note: parallel worksteal runs flaked 3/9 (19-failure burst on
the first run, two single-test flakes with different names); every
failing name passes in isolation and serial is fully green 7573/7573,
so the flakes are attributed to the known-flaky worksteal runner
under machine load, not this change (clean tree is not immune
upstream either).

## Definition of done

Reproduction harness + ruleset in repo (or as a documented script if
too synthetic for the suite), root cause named with mechanism, fix
with regression test, battery, deploy both bridges.
