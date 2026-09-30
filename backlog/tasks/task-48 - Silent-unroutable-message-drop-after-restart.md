---
id: TASK-48
title: Complete assistant messages dropped silently when routing finds no topic (antiwire incident)
status: In Progress
assignee: []
created_date: '2026-09-30 07:55'
updated_date: '2026-09-30 07:55'
labels: [incident, message-loss, routing]
dependencies: []
---

## Incident (2026-09-29 19:51, maintainer report)

The antiwire coding agent produced complete assistant messages (19:51
local, verified in the transcript at bytes 1993100-2028118) and
NOTHING arrived on Telegram, while /screenshot showed the pane active.

## Forensics

- The session was tracked (monitor state), the transcript was read
  (the delivery offset advanced past the messages to 2032857), and the
  session-map entry, window state, and chat_thread_binding all exist
  and resolve correctly when queried NOW.
- events.jsonl and the journal are silent for the session and thread
  at that time: the drop left no trace.
- The only silent drop on the path is handle_new_message's
  find_users_for_session returning empty (logged at DEBUG): the
  window-session link the resolver reads was stale or absent in the
  running process at 19:51, minutes after a double restart
  (18:30 adoption process, SIGTERM 18:34 with "Shutdown drain
  timeout: 40 queued task(s) remain", successor process 18:34:21).
  The exact in-process transient is not recoverable post-hoc.

## Fix (2026-09-30)

handle_new_message routes unroutable COMPLETE assistant text through
_handle_unroutable_message, which WARNs (was DEBUG, invisible in the
journal) and drops; non-deliverable content stays DEBUG. An in-memory
30s retry was implemented and then REMOVED in review: it re-enqueued
out of per-user receive order, deduped away a distinct identical
second message, and any restart inside its window lost the message
anyway; the honest fix is the warning plus the receipt.fail follow-up
below. The class is never silent again.

## Follow-ups (2026-09-30 altitude review)

- Durability: the 30s in-memory retry loses a message to any restart
  inside its window (the incident itself involved a restart). The right
  depth is the delivery contract: an unroutable complete message should
  receipt.fail() (producer-side failure) so the watermark does not
  commit past it and the restart replays it; the TASK-29 replay cap
  already dampens the eternal-retry risk. Needs callback plumbing from
  routing back into the monitor's receipt lifecycle.
- The open question the retry does NOT answer: WHY did a bound and
  tracked session resolve empty in find_users_for_session for over an
  hour (or was it a shorter divergence)? The resolver reads in-memory
  window-state links refreshed by session_map_sync each cycle; if the
  19:51 divergence was durable rather than transient, the retry never
  recovers and the warning is the real content. Reproduce or catch it
  live via the new warning.

## Definition of done

Fix with tests (complete unroutable message warns and enqueues
nothing; non-deliverable content unchanged), gates, deploy both
bridges.
