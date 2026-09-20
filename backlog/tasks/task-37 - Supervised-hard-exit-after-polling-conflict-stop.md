---
id: TASK-37
title: Supervised hard exit after polling-conflict stop (root fix for the not-initialized zombie)
status: Open
assignee: []
created_date: '2026-09-20 09:10'
updated_date: '2026-09-20 09:10'
labels: [lifecycle, zombie, mac]
dependencies: []
---

## Description

On sustained getUpdates Conflict, `_error_handler` (bot.py) calls
`application.stop_running()` and logs "stopping so the service supervisor
can restart ccgram". The exit path AFTER that depends on PTB's shutdown
completing: main.py only reaches `raise SystemExit(1)` when `run_polling`
returns. When the shutdown sequence wedges (observed on the Mac:
1,247 "This HTTPXRequest is not initialized" lines while the process stayed
alive; the 2026-09-19 guard workaround in ~/.local/bin/ccgram-ensure kills
on that signature), the process lives on with a torn-down HTTP client while
the monitor and queues keep producing sends that all fail silently: the
bridge is mute but looks healthy to any pgrep.

Fix: when `record_conflict` trips the shutdown request, arm a supervised
hard exit: a task that waits (order of 60s) and, if the process is still
alive, saves monitor state best-effort and calls os._exit(1). The
supervisors (systemd Restart=on-failure on bird, the launchd guard on the
Mac) both already handle a dead process correctly; the zombie exists only
in the alive-but-wedged middle state. Test: simulate the shutdown request;
the watchdog task schedules os._exit via an injectable clock/exit hook.

## Review outcome (2026-09-20, code-review high)

Shipped plus review hardening: the window is 300s because a HEALTHY PTB
teardown legitimately runs 150-210s (unbounded update-queue join plus a
rate-limited goodbye send) and a 120s timer killed non-wedged drains; the
callback now runs the best-effort monitor state save the doc mandated; the
timer arms once per episode (post-grace conflicts repeat). Residual,
accepted: a user stop during the window exits 1 rather than the signal
code, so restart.sh may restart a deliberately stopped service; bounded to
the 300s window and preferable to the zombie.
