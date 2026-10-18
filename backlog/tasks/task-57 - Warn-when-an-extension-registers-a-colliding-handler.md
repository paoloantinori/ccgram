# Task 57: Warn when an extension registers a colliding handler

Status: open
Filed: 2026-10-18 (code-review finding on the task-56 fix)

## Problem

With load_extensions running before register_all (task-56), extension
handlers get first claim over EVERY group-0 built-in, not just the
forward catch-all: explicit commands (/send, /sync, ...), the unfiltered
CallbackQueryHandler dispatcher, text/photo/voice handlers. The seam
(`ExtensionApi.register_ptb_handler`) accepts any handler with no
collision check, so a future ccgram-ext registration that overlaps a
built-in silently kills the core handler, in the same silent-shadowing
class as task-56 but with no log and no test.

No overlap exists today (ccgram-ext registers /names, /icons, and a
MessageReactionHandler), so this is latent, not live.

## Fix direction

In `ExtensionApi.register_ptb_handler`, when the handler is a
CommandHandler whose command name is one of the built-in command specs
(registry.COMMAND_NAMES or equivalent), log a warning naming both sides.
Keep it a warning, not a rejection: extensions are the user's own and may
deliberately override.

## Acceptance

- Registering CommandHandler("send", ...) through the seam logs a warning.
- Registering CommandHandler("names", ...) logs nothing.
- Unit test on the seam.
