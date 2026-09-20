---
id: TASK-34
title: Bound the interactive-path queue.join() that freezes the whole monitor loop
status: Open
assignee: []
created_date: '2026-09-20 09:10'
updated_date: '2026-09-20 09:10'
labels: [delivery, stall, interactive]
dependencies: []
---

## Description

User report 2026-09-20: Telegram stops showing new agent output relatively
often; the only working view is a /screenshot (a different code path), and
delivery stays dead after it. Correlates with auto-approvals, subagents,
background bashes, and input requests that resolve on their own.

Root cause (code, fork/main 866eedf1): when a transcript message is a
tool_use of an interactive tool, `handle_new_message`
(handlers/messaging_pipeline/message_routing.py:194) does
`await queue.join()` with NO timeout, then sleeps 0.3s, then captures the
pane. `handle_new_message` runs inline in the monitor's SEQUENTIAL dispatch
loop (session_monitor.py:1050 awaits the callback per message). One
non-draining per-user queue therefore freezes the dispatch of EVERY session:
no reads, no sends, no watermark commits, all topics mute until restart.
Queues legitimately drain slowly while Telegram flood control holds them
(1 msg/s class with per-message retry budgets), which is exactly the state a
bash/subagent burst creates; an interactive tool_use arriving in that window
(the auto-approve/superseded-input cases emit AskUserQuestion/ExitPlanMode
tool_use entries) parks the loop on the join for as long as the queue is
backed up, or forever if any single dispatch never completes (per-user lock
contention at message_queue.py:581/657, dead-topic cooldowns, transport
wedges). Same family as the 2026-09-06 incident where "the status bar was
starved too" (see the TASK-29 comment in session_monitor.py).

Fix: bound the wait (`asyncio.wait_for(queue.join(), _INTERACTIVE_JOIN_TIMEOUT_S)`,
order of 5-10s, warn on timeout and proceed), so an interactive UI can
reorder against pending messages but can never freeze the global dispatch.
Test: a queue with an item whose task_done never arrives; the interactive
dispatch path must return within the timeout and the monitor must keep
dispatching later messages.

## Review outcome (2026-09-20, code-review high)

Shipped with the bounded join. FOLLOW-UP (review finding, accepted as
design debt): the 8s cap still taxes the global sequential dispatch once
per interactive event while a HEALTHY backlog drains (per-user facade
ledger, one sequential worker, up to 300s retry budget: a 20-message burst
drains 20-62s), and a prompt sent after a timed-out join can flash and
vanish when the backlog delivers and clears the interactive message. The
durable fix is structural: per-window join scope or concurrent dispatch.
Not blocking: bounded beats unbounded, and the flash is cosmetic.
