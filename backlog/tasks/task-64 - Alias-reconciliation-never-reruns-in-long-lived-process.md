# Task 64: alias reconciliation never re-runs in a long-lived process

Status: open (recorded 2026-11-01, from the Mac reboot outage)

## Incident

Mac reboot + macOS upgrade at 16:41 CET 2026-11-01. herdr restored the panes
under new workspace ids; one agent's derived target changed
(e5656f13... superseded by ed13e6b3... for session 3ed37a33, local_ai).
The bridge (started 16:43) kept the OLD bindings live: forwards still worked
(the send path resolves by session value), but the monitor never re-tracked
the session, so replies never reached the maintainer's topic for ~3 hours.
At 20:14, immediately after a process restart, the boot reconciliation
migrated e5656f13 -> ed13e6b3, updated the session map, started tracking, and
the topic delivered again within 33 seconds.

## The gap

`_unique_window_aliases` / `reconcile_window_aliases` reconciled at BOOT, but
the long-lived process never re-ran it for this supersession even though the
agent restored minutes later. The retained-key warning loop (5/sec, now
throttled) ran constantly, so the map re-read path was alive; the ALIAS
migration path was not.

## Direction to evaluate

- Re-run alias reconciliation when a live listing shows a superseded id that
  a binding still references (event-driven or on the periodic topic check).
- The retained legacy keys (w7:t1 family) never match anything in the current
  format: consider surfacing them once at boot as actionable state (doctor /
  audit already reports legacy_herdr) instead of per-cycle retention scans.

## Operational note

Until fixed, the runbook for "topic silent after reboot/upgrade with agent
restored": restart the bridge once the agents are back (kill the pid; the
LaunchDaemon KeepAlive respawns; boot reconciliation rebinds). Verified
2026-11-01: topic 21397 delivering again after restart.
