# Task 61: Merge upstream v4.17.0 (shared session core)

Status: done (2026-10-23)
Filed: 2026-10-23, maintainer direction: "vai. ragiona bene pero' sul delta".

## What came in

Upstream 16 commits: #330 (Telegram + mobile unified on a shared session
core with protocol runtime and optional HTTP API), #332 (our #325
adopted: control-chars-only guard + 6 boundary tests), #334 (our #324
adopted: fail-soft probe with throttled warnings, extended to the core's
second caller), #335 (our #326 adopted: cache_positive pass-through,
extended to the core's bulk refresh), Archfit workflow, docs
consolidation, v4.17.0 tag.

## Resolution decisions (delta reasoning, per direction)

- agent_status_cache.py: his #335 adopted our implementation verbatim;
  the only delta was docstrings (his reference the new core consumers).
  Took his wholesale. Zero fork delta left on the file.
- observe.py: his base (fail-soft + throttled warning + the
  cache_positive split) plus the fork-only TASK-47 gates re-integrated
  as the _native_status_or_probe/_native_status_to_update/native_once
  seam. His unconditional returns became gated returns.
- session_monitor.py: his base plus the task-60 replay-cap restore
  (constant, method, both discovery-loop hooks, eviction, cooldown).
- bootstrap.py/cli.py: his base (protocol runtime, api server) plus the
  fork-only TASK-128 admin consumer (start/stop/reset/call + cli group).
- event_stream_monitor.py: his (docstring-only delta).
- tests: kept our seam-targeting test files; rewired his new
  session_protocol regression test to the fork seam names.
- admin.py: his _cleanup_stale_topics grew an adapter param (session
  core); bridged via the live bound service from session_resolver.
- Auto-merge kept: extension seam + ordering, one-tap parser, audit_send
  family, replay cap, TASK-47 gates, zai provider display, admin
  consumer, delivery receipts. All verified present post-merge.

## Verified

8109 passed / 23 skipped, ruff clean, pyright src 0. jsonschema now a
dev-extra dependency (upstream tests import it; uv sync --extra dev).

## Deploy

Both bridges via the contract script.
