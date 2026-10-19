# Task 58: Delivery audit log for successful Telegram sends

Status: done (2026-10-19)
Filed: 2026-10-19, from the anti-vocale missing-delivery incident (TASK-128
filone; maintainer report via av-mac).

## Problem

Successful sends logged nothing anywhere: only failures left a trace. When
the maintainer reported two lost messages (recap + decision list, Mac
bridge, 2026-10-19 06:11-06:41 CEST), the bridge-side chain was exonerated
at every observable stage (read, dispatch, no drops, no task exceptions,
receipts settled as delivered), but the actual send could not be confirmed
or refuted: absence of an error line is not proof of delivery. The whole
diagnosis stayed circumstantial for lack of one positive send trace.

## Fix

`PTBTelegramClient.send_message` logs an INFO audit line on every
successful send with chat_id, thread_id, the returned message_id, and the
text length. The adapter is the choke point for every send that goes
through the client seam, so the line covers the queue worker, status
updates, replies, panels, and file delivery with one site.

## Coverage after review

- Audited: send_message, send_photo, send_document, send_voice (the whole
  adapter send surface). Content never enters the record (metadata only,
  pinned by a leak-guard test); requires CCGRAM_LOG_LEVEL <= INFO.
- Not covered: raw-bot senders outside the adapter (DraftStream streamed
  text and tool batches, the shutdown banner) -> task-59.

## Follow-ups

- The pending live discriminator of the 2026-10-19 incident: whether the
  maintainer received the injected "DIAG-OK 2026-10-19T05:18:05Z" message.
  With this audit line deployed, any recurrence shows the message_id
  Telegram accepted, narrowing loss to after-accept (client-side, deleted,
  wrong destination) versus never-accepted.
- The chronic "Retaining unrecognized session_map key" warnings (old
  herdr:wN:t1 keys, one per poll cycle since 4.11.x) are unrelated noise
  worth a separate cleanup task.
