# Task 62: verify-backoff backport strip discipline

Status: open (recorded 2026-10-31, from the altitude review of the five-fix backport)

## Context

fork/main's `transcript_reader.py` predates upstream #359 (92b77fdc, "start a
session from one typed line"), which added a READ-layer startup replay bound:
`_startup_clamped`, `_startup_sessions`, `_startup_replay_checked`,
`_replay_allowed`, `_clamp_startup_replay`, `allow_replay`, `_clamped_floor`,
and the `config` import for `startup_replay_max_bytes`.

The fork's answer to the same eternal-replay incident family is DELIVERY-layer
(task-60's auto replay-cap trigger, skip barriers, watermarks). The two are not
composed today.

## Rule for backports from pr/prefix-verify-cost (or its merged shape)

Strip list when porting transcript_reader fixes: the #359 symbols above, the
clamp pops in the probe and read-reset paths, the `probe_clamped` snapshot
param, the `or session_id in self._startup_clamped` rebuild-gate clause, the
clamp-aware rebuild-failure rollback, and the session-id-refresh clamp
migration. Everything else ports byte-identical; the five-fix backport
(2026-10-31) validated the list with a shadow-package proof (8 regression
tests fail on the pre-backport source).

Keep `_poll_already_seen` even though the fork alone does not need it for
PLR0915: mirroring upstream's shape in this file shrinks the next merge's
conflict surface, and merge-resolution drift is this fork's documented
dominant loss mode (task-60, extension seam 2026-10-02, seam ordering
2026-10-04).

## Decision owed at the next upstream merge (task-61 follow-up)

#359 will arrive in a periodic merge. Then decide compose-or-replace: read-layer
clamp (#359) vs delivery-layer caps (fork). Until then every backport re-derives
the strip from this file.
