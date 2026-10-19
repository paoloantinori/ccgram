# Task 59: Route raw-bot sends through the audited adapter

Status: open
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

## Acceptance

- A streamed assistant message and a tool-batch final message each leave
  a `telegram send ok` line with message_id.
- The shutdown banner leaves one.
- No Protocol change without checking the F1 boundary rules.
