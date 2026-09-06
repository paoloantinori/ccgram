---
id: TASK-30
title: Round-robin fair scheduling across per-topic queues (user proposal)
status: Done
assignee: []
created_date: '2026-09-06 20:30'
updated_date: '2026-09-06 20:30'
labels: []
dependencies: []
---

## Description

User proposal 2026-09-06, after the starvation incident: topics with
few pending messages must get a chance to complete before a topic
stuck with a huge backlog. Today message_queue.py runs ONE per-user
FIFO: head-of-line blocking turns one clogged session into an outage
of every live topic of that user.

DESIGN (stage 2 after TASK-29's cap):
- Replace the single FIFO with per-(user, window/topic) queues; the
  worker cycles queues round-robin, taking a small quantum (1-3
  messages) per turn from each non-empty queue.
- Per-topic ordering stays strict FIFO (tool_use->tool_result pairing
  and status-edit ordering are per-window invariants and must hold).
- The per-user rate limiter (1.1s) stays GLOBAL: round-robin changes
  ORDER, not rate. A topic with 3 pending messages completes within
  its first rounds regardless of any sibling's backlog size.
- Merging/batching and the tool-batch state machine stay per-window
  (they already are); the worker loop and the queue structure are the
  surgery site. Tests must cover: fairness under one huge + several
  small queues; per-window order preserved; tool pairing intact.

Complementary to TASK-29: cap removes the fuel, this bounds the blast
radius. Bigger than the cap (one subsystem) but still bounded to
message_queue.py + tests.

DONE 2026-09-07 (commit 6c9c2907): _ShardedUserQueue facade, one FIFO
shard per window + round-robin picker; facade-owned unfinished ledger
as the join authority; backlog snapshot and same-window merge adapted
(review F1/F2). Stress-probed (9000 concurrent puts, dynamic shards,
zero loss, ledger balance). Live verification is this very exchange:
the ccgram topic's messages interleave fairly with any sibling backlo-
grand the deployed restart itself. Together with TASK-29's cap, both
recurrence legs of the 2026-09-06 incident are structurally closed.
