# Task 60: Replay-cap auto-trigger lost in a September merge (third fork loss)

Status: open
Filed: 2026-10-21, from the third eternal-replay incident (2026-10-19).

## Incident (third of the family: 2026-08-30, 2026-09-06, 2026-10-19)

12:07:52 a network ReadError failed a flush_batch ephemeral delete; at the
bounded shutdown a minute later "Shutdown drain timeout: 6239 queued task(s)
remain" left thousands of receipts unacknowledged; every restart replayed
the mass into the per-user FIFO. Five windows wedged (jellyfin 18.7 MB the
largest), watermarks frozen for hours, wedge alarms firing. No data lost:
the queue drained naturally (1230 recovery messages in ~2h20m) and the
maintainer was pointed at the manual status-bar "Jump to live" skip.

## Root cause: the auto-trigger is gone from the tree

TASK-29 (2026-09-06, commit bf4b546c, deployed 4.10.4.dev21) added the
automatic replay cap: beyond CCGRAM_REPLAY_CAP_MB (default 1) per session,
the monitor auto-fires the upstream skip barrier (freeze at EOF, purge
queued history, one notice). Today's tree has NO trace of it: no
CCGRAM_REPLAY_CAP_MB anywhere in src/ccgram (the skip-barrier API it
reused survives; only the automatic trigger sites are gone). The last
file snapshot carrying it predates the 2026-09-23 upstream wave
(#263/#265/#280) that reshaped session_monitor.py; the merge resolution
dropped the fork delta wholesale. Third silent fork loss in a merge,
after the extension seam (2026-10-02) and the seam ordering (2026-10-04).

Compounding: bird's ~/.ccgram/.env has CCGRAM_REPLAY_CAP_MB=16. Even with
the trigger alive, 16 MB per session tolerates hours of wedge before
skipping; today's other four gaps (0.4-6.8 MB) would all have been under
it. Decide whether 16 is intended; the September default was 1.

The detection layer worked: the delivery-wedge warnings (TASK-45) are
what alarmed the maintainer. The action layer is what was lost.

## Fix

1. Re-introduce the auto replay-cap trigger on the current
   session_monitor read/discovery paths (rebase the bf4b546c logic; the
   skip-barrier machinery it drives is intact and upstream-owned).
2. Regression guard so a merge cannot silently drop it again: a test
   asserting that a >cap gap at session discovery fires exactly one skip
   intent (and that CCGRAM_REPLAY_CAP_MB=0 disables it).
3. Merge-audit rule for fork load-bearing markers: after every upstream
   merge, grep for the fork's load-bearing code (extension seam + its
   ordering, replay cap, queue emits) before pushing. Candidate: extend
   tests so each marker has a test that fails when the marker disappears
   (the seam already has one since task-56; the cap gets one here).

## Acceptance

- A session loaded with a gap above the cap auto-skips at discovery with
  one notice; under the cap or cap=0 it does not.
- Battery green; the wedge from 2026-10-19's shape cannot recur unbounded.
- The env value on both bridges reviewed and recorded here.
