---
id: TASK-184
title: Bound restart replay and unfreeze delivery watermarks (three-layer fix)
status: Done
assignee: []
created_date: '2026-10-28 21:55'
updated_date: '2026-10-28 21:55'
labels:
  - kind/bug
  - kind/reliability
dependencies: []
references: []
priority: high
ordinal: 100
---

## Incident (2026-10-28, third of the class: 08-30, 10-25, 10-28)

A deploy restart replayed ~2200 messages (19 MB across 10 sessions). Root
cause chain, file:line verified: a terminally failed send (flood budget
exhausted, message_queue.py:952-959/1213-1215) settles its receipt FAILED
and settled_prefix (delivery_contract.py:101) stops there FOREVER: one
failed message fenced the session's watermark while delivery behind it
kept working (journal: "Delivery wedge suspected" from Oct 25 23:25).
At restart, the uncommitted range replayed. The cap missed it because
bird's env had CCGRAM_REPLAY_CAP_MB=4 above each 1-3.6 MB gap.

## Fix (fork/main 0c397d30, deployed both bridges 2026-10-28 evening)

Layer 1: terminally failed receipts older than
CCGRAM_FAILED_RECEIPT_GRACE_S (default 300s, 0 = old permanent fence)
retire as a deliberate skip (WARNING journalled, /history reaches the
bytes) and settled receipts behind them commit the same cycle. Layer 2:
restart-cap holes closed (re-keyed adoption now cap-judged; the explicit
replay_from_start flag is never capped, a bare offset-0 watermark is).
Layer 3: a wedge persisting past CCGRAM_DELIVERY_WATCH_ESCALATE_MIN
(default 60 min) journals every 60s pass and sends ONE direct maintainer
notice naming session, gap, and the restart consequence. Both bridges'
env tightened to CCGRAM_REPLAY_CAP_MB=1 (backups kept). Suite 8222
(28 new tests), /simplify 3 reviewers, /code-review high (4/5 applied).

## Honest limits

Failed bytes past grace become at-most-once (journalled; /history
reaches them). A fully wedged queue still delivers nothing: the fix
makes it loud in 60s and bounds the restart, it does not force
progress. The pending_tools fence (outstanding tool result) still
freezes a session's watermark by design. Follow-up ideas declined as
scope: in-process redelivery of failed bytes; cross-module notice
unification with orphan_watch.

## Review round (fix/task184-review)

Five findings from a high-effort review of 0c397d30..4f6447bf, all
addressed. F1: skip-retirement no longer strands a tool-delivery
fence, whose release receipt it just dropped (watermark froze again);
the fence releases in the same commit pass, including the corner where
retirement empties the session's whole receipt list. F2: the cap-check
sequence is fully inside per-session containment again. F3+F4:
TranscriptReader.enter_tracking is the single tracking-entry seam
(provider resolves once per session per cycle; the cap judges exactly
the offset the read resumes from); the monitor's duplicated gate+adopt
preamble is deleted, observes_window_provider removed and
adopt_tracking_for_file re-privatized. F5: the tautological
failed_at-narrowing conjunct in retire_aged_failures is gone.
Suite 8225 (3 new fence-retirement tests, red-proven), /simplify 4
reviewers (one real corner gap found and fixed), /code-review high
(3/6 applied, 3 declined with reasons in the commit message).
