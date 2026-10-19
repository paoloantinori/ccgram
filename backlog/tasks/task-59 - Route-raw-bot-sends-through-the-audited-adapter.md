# Task 59: Route raw-bot sends through the audited adapter

Status: done (2026-10-18)
Filed: 2026-10-19 (code-review finding on the task-58 audit)

## Problem

The task-58 delivery audit covers the TelegramClient adapter methods, but
real outbound content also flows through the RAW bot, invisible to the
audit:

- `DraftStream` (telegram_draft.py:341/439/443): streamed assistant text
  (message_routing.py:144) and tool batches (tool_batch.py:393,
  force_legacy=True) send via `self._bot.send_message` and
  `do_api_request("sendMessageDraft")` directly.
- `bot.py:228`: the shutdown banner via `application.bot.send_message`.

For those sends the task-58 ambiguity remains: dispatched, receipt
settled, no trace either way. The streamed-draft final message is exactly
the message class of the 2026-10-19 incident.

## Fix direction

Thread the adapter (or an audit hook) into DraftStream: it receives the
raw bot via `unwrap_bot(client)` because it needs PTB-only draft APIs;
either give the adapter a `do_api_request` passthrough so DraftStream can
take the adapter, or emit the same `telegram send ok` line at the three
DraftStream send sites and the banner site. Prefer the adapter passthrough
(one audit point) if it does not grow the Protocol awkwardly.

## Resolution

Call-site instrumentation (the adapter-passthrough alternative would have
widened the TelegramClient Protocol for no audit payoff: the draft-API
pushes are ephemeral previews with no message id, and the persisted sends
already had plain send_message sites to instrument). audit_send extracted
to a module function in telegram_client; DraftStream._start_legacy and
_send_final_message call it (kind=draft); the shutdown banner calls it
(kind=banner) inside a suppress so a failed audit cannot turn a clean
stop into a crash. DraftStream.abort emits a compensating
"telegram draft deleted" trace so an aborted legacy fallback message
does not read as a delivery. Code-review round 2 findings all closed
(banner try, lazy import hoisted, delegator inlined, __all__, import
grouping, final-send thread assertion).
