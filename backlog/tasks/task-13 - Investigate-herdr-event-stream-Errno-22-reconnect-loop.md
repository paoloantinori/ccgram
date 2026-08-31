---
id: TASK-13
title: Investigate herdr event stream Errno 22 reconnect loop
status: Done
assignee: []
created_date: '2026-08-31 07:56'
updated_date: '2026-08-31 08:55'
labels: []
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Observed during TASK-11 diagnosis (2026-08-30): the herdr event-stream consumer logs "herdr event stream error: [Errno 22] Invalid argument" repeatedly (10x in 4 minutes in a debug boot; reconnect loop with backoff keeps re-firing). Suspects: reader loop racing socket teardown in herdr_events.open_socket_stream (asyncio stream read after transport close gives EINVAL), the reconnect not draining/cancelling the previous stream cleanly in EventStreamMonitor, or a herdr-side events.subscribe protocol quirk. Investigate: journal frequency/correlations, code path, local reproduction against the live socket; fix with gates.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
DIAGNOSIS COMPLETE (2026-08-31 10:15 CEST):

**Errno 22: transient, era-correlated, not reproducible, handled correctly.** All 236 occurrences fall inside the single 13:14:45-15:12 DEBUG boot of 2026-08-30 (exactly 2/min for 117 min) — the stress era right after the eternal-replay incident (1382-task backlog grind, heavy pane-subprocess load, flood penalties). At info level the line (logger.debug in herdr.py watch_events) is invisible, so journal silence since proves nothing; but live reproduction today against the same socket found ZERO errors across every plausible path: (1) steady consume 180s: 12 healthy subscribe cycles (~1 per 15s), 91 events, 0 OSError, 0 EOF; (2) mapping-drift probe: pane_to_window/tab_to_windows stable 30/30 one-second resolves (the digest re-key theory is FALSE for the current agent population); (3) supervisor-style mid-readline cancellation 30x: 0 OSError (the await-wait_closed-during-GeneratorExit theory is false too). The reconnect loop (backoff reset on sentinel, healthy-refresh without penalty) behaved as designed; each transient failure cost ~30s of stream coverage, self-healed. No code defect identified for the EINVAL itself; plausible residual: rapid open/close under daemon stress. If it recurs, grab a debug boot with traceback at the logger.debug site (one-line instrumentation) before it clears.

**Adjacent real finding (efficiency, by design):** the watch loop re-subscribes every ~15s (5s idle timeout + per-event mapping checks) and each sentinel re-primes with one agent_status subprocess per watched pane: measured 376 _resolve_event_targets + 90 agent_status in 180s (~2.6 herdr calls/s sustained, ~12 of 376 resolves are cycle/event checks, the rest re-prime internals). The mapping is stable, so the idle-timer refresh is pure overhead at current scale. Improvement options (behavior change, needs design + gates): subscribe by tab instead of per-pane, lengthen/drop the idle refresh (rely on mapping-change + supervisor set-change restarts), or cache re-prime results across cycles. Filed as decision, not done.

Repro scripts: /tmp/repro_herdr_stream.py, /tmp/repro_herdr_outcomes.py (outcome histogram), plus the inline cancel-path probe.

FIX IMPLEMENTED AND DEPLOYED (2026-08-31, TASK-13 option (b) + review corrections):

watch_events now re-primes only after coverage loss: transport drop, server EOF, first connection, or a pane MOVE (detected by a mapping check in the idle-timeout branch; silence alone proves nothing for a moved pane whose events go to a subscription we never held). Unchanged-mapping idle refreshes skip the per-pane agent_status forks (the measured ~2.6 herdr calls/s at 17 bound windows). Idle interval 5s to 30s (digest moves still caught in ~2s by the supervisor set-change restart); a dedicated _STREAM_ACK_TIMEOUT=5s keeps hung-handshake recovery on the old bound.

Gate-found corrections (all applied with tests): the mapping-change refresh now DELIVERS its triggering event under the pre-refresh mapping (the terminal-event guard; it was dropped untranslated, and with the skip nothing would recover it); the ack-phase timeout takes the transport-failure path, not the healthy-refresh path (which erased the still-pending first-connect prime); server EOF no longer leaks RuntimeError('async generator raised StopAsyncIteration') from a bare anext (anext(stream, None) + graceful backoff).

Tests: 6 in test_herdr_backend.py (skip-after-idle, reprime-after-drop, EOF-graceful, idle-reprimes-on-move, mapping-change-delivers-event, hung-ack-refresh) + _MovingPaneRunner/_hang_forever/_count_agent_status helpers. architecture.md herdr bullet updated. Remaining known cost (own task if wanted): the per-event _resolve_event_targets mapping check (~one agent-list snapshot per event) is now the dominant stream subprocess cost.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Diagnosed (Errno 22: transient, era-correlated with the 2026-08-30 stress window, not reproducible via steady/churn/cancel paths, handled correctly by the reconnect loop) and fixed the adjacent efficiency defect it surfaced: reprime-after-coverage-loss-only with move detection, idle 30s, dedicated 5s ack timeout, EOF-graceful handling; three gate-found corrections applied with discriminating tests (pre-refresh event delivery, ack-phase transport path, first-connect prime preservation). 6730 tests green. Deployed 2026-08-31.
<!-- SECTION:FINAL_SUMMARY:END -->
