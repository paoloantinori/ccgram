---
id: TASK-45
title: Early warning for silent delivery wedges (frozen offset while transcript grows)
status: In Progress
assignee: []
created_date: '2026-09-27 17:05'
updated_date: '2026-09-28 10:12'
labels: [incident-prevention, fork, monitoring]
dependencies: []
---

## Problem

The 2026-09-26 wedge (TASK-43) froze delivery for 7 hours before
anyone noticed; the operator only discovered it because replies
stopped arriving. Nothing in the bridge said "this window's delivery
offset has not advanced while its transcript kept growing".

## Proposal

A cheap liveness signal in the existing status polling loop, no new
tasks or subprocesses: for each tracked session, compare the delivery
offset against the transcript size; if the transcript has grown by
more than a threshold (say 64 KB) while the offset stayed unchanged
for longer than a grace period (say 120s of confirmed activity), post
ONE warning line to the journal and a one-time notice in the topic
(deduped per window per incident). The scheduler fix removes the
known cause; this catches any future silent wedge class in minutes
instead of hours.

Design constraints: reuse monitor state (byte offsets already
tracked); the notice must not go through the delivery queue itself (a
wedged queue must not swallow its own alarm; send via the direct
interactive path).

Sizing guess: small; touches the polling coordinator plus one helper
and two tests. Run the full gates if it grows beyond that.

## Implementation (2026-09-28)

handlers/polling/delivery_watch.py: pure DeliveryGapWatch decision
core (alert once per stuck incident, re-arm when the watermark
advances or the gap shrinks) + check_delivery_wedges wired LAST in
the existing 60s topic_check gate in periodic_tasks (a raise cannot
skip the peer tasks). Signal: the session's DURABLE DELIVERY
WATERMARK (new session_state_ports.get_delivery_watermark, the
monitor's settled-receipt boundary, tracked_session.last_byte_offset)
against the transcript size. The first draft read the user read
offset via a session_query wrapper; /simplify's altitude round caught
that this is the WRONG signal and the wrapper was removed:
message_routing stamps the read offset at ENQUEUE time (before
delivery) and /history paging writes it too, so it keeps moving while
delivery is dead. The watermark is the number that actually froze at
60.5 MB during the incident. Transcript path and fence state come
from the same projection (the port returns the TrackedSession's own
file_path so gap arithmetic never mixes files, code-review finding;
the full session resolver would glob and parse megabytes of JSONL per
stale window per pass). Bindings via new
session_query.iter_bound_topics (handler-layering audit bans new
singleton imports).

Known limit (accepted, code-review 2026-09-28): the rule detects a
TOTAL freeze (the TASK-43 class). A slow-drip degradation that still
settles one receipt per pass while the backlog grows is not alarmed
by design; the gap-only alternative would false-alarm on any large
backlog being legitimately drained at the group rate. If slow-drip
ever bites, the signal to add is drain rate, not this watch.

The alarm rides safe_send under interactive_priority (direct path,
never the delivery queue) as a fire-and-forget task (a flood-retried
send must never stall the poll cycle), plus a journal warning: the
alarm survives a wedged queue and even a wedged Telegram path.
reset_for_testing is wired into bootstrap alongside the peer caches.
Knob: CCGRAM_DELIVERY_WATCH_GAP_KB (default 256, 0 disables), same
shape as CCGRAM_REPLAY_CAP_MB.

Thresholds DEVIATE from the proposal on purpose: 256 KB / 300s
instead of 64 KB / 120s. A long streaming thinking block grows the
transcript without any complete message settling a receipt; 64 KB /
120s would page the operator on that benign burst. 256 KB / 300s
still alarms on any real wedge of the TASK-43 class (1.8 MB
unsettled, frozen 7h) within about five to six minutes.
