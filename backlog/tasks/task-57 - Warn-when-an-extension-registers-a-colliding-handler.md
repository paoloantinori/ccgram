# Task 57: Warn when an extension registers a colliding handler

Status: done (2026-10-22)
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

## Resolution (2026-10-22)

register_ptb_handler warns (never rejects, per the seam isolation
contract) naming the extension and the command. Review hardening folded
in the same commit: COMMAND_NAMES now derives from the hoisted
COMMAND_SPECS table (a production guard no longer depends on a test
sentinel), the warning carries the extension name, a group-0
CallbackQueryHandler through the seam also warns (core installs exactly
one unfiltered callback dispatcher; an extension one, registered first,
would deaden every core inline keyboard), extensions.py moved to
structlog (the %-style "extension loaded" line now keeps its name in the
record while preserving the deploy-contract grep string), and the lazy
import comment states the real reason (the seam's own import-lightness,
not bot.py's cold start).

## Code-review round (2026-10-22), closed additively

- The remaining %-style calls converted to kw-style (one module, one
  convention; the deploy grep string preserved).
- Multi-command CommandHandler test pins the per-name warning.
- Skipped with reasons: broad MessageHandler(filters.COMMAND) takeover
  not warned (filter introspection is fragile; documented residual here),
  and the core-ImportError-funnelled-as-extension-failure scenario
  (unreachable on the boot path: bot.py imports registry at module top
  before the seam can run).

## Acceptance

- Registering CommandHandler("send", ...) through the seam logs a warning.
- Registering CommandHandler("names", ...) logs nothing.
- Unit test on the seam.
