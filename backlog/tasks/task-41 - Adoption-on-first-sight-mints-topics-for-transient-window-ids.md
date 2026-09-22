---
id: TASK-41
title: Adoption on first sight mints topics for transient window ids
status: In Progress
assignee: []
created_date: '2026-09-22 11:20'
updated_date: '2026-09-22 11:20'
labels: [incident, fork, robustness]
dependencies: [TASK-40]
---

## Incident (2026-09-22, Mac, planner pane recreation)

The planner pane was recreated (close + fresh workspace + agent start,
user-authorized). Timeline from the bridge log and session_map:

- 10:37:46 the hook fired with the REAL session id (602bb556) and wrote
  map entry herdr:herdr-session-v1-3e5b330d... (cwd planner).
- 10:37:51 the bridge's listing-based discovery saw a DIFFERENT digest,
  herdr-session-v1-bb4be0f8..., for the same pane: a transient session
  identity that herdr publishes for a few seconds at agent start before
  settling on the real composite.
- Adoption fired on first sight for bb4be0f8 and auto-created topic
  17216 ('Claude > planner > 1 > p1'). The transient died seconds
  later; bb4be0f8 never appears in session_map at all. The topic is
  orphaned on creation.

Root cause split (user question, 2026-09-22): the TRIGGER is
herdr-side (a volatile session identity at agent start); the
VULNERABILITY is ccgram's (any listing-eligible unbound window is
adopted on first sight, so any backend reporting a short-lived window
identity mints a topic that dies with it). ccgram must be robust to
transient identities from any backend.

Related but distinct: the fold did NOT relink the old planner topic
16674 because the fold key is (cwd, provider) and the previous
planner session was recorded as codex while the new one is claude.
That refusal is by design.

## Fix

Adoption debounce in _emit_unbound_window_events: an unbound window
becomes adoptable only after its id has survived
_ADOPT_AFTER_STABLE_S (15s) of consecutive listings; an id absent
from a cycle is pruned, so a flap restarts its clock. The
hook-attested path (_emit_known_unbound_window_events) intentionally
bypasses the debounce: the hook writes real session ids and that path
is already gated on live-listing presence, so genuinely new hook
sessions get their topic immediately. Tests: TestAdoptionDebounce
(young window not adopted, survivor adopted, flap restarts the
clock); existing eligibility tests keep pre-debounce semantics via a
zeroed constant. The herdr boundary audit caught the first draft's
comment using the adapter-private term; reworded.

## Definition of done

Battery + lint + pyright green; code-review high on the diff; commit
with gates; push mine/fork/main; deploy bird and verify the service;
Mac rides the next cc-config redeploy. Upstream contribution only
after explicit user approval (candidate: the incident is upstream
behavior with real evidence).
