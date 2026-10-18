# Task 56: Extension commands shadowed by the forward catch-all since 2026-10-04

Status: done (2026-10-18)
Reported: 2026-10-18 live: `/names apply` in a Mac-hosted topic answered
"Unknown command: /names. Did you mean /name?"

## Root cause

The 2026-10-04 seam restoration (9d878698, after the v4.14 merge) rewired
`load_extensions(application.add_handler)` AFTER `register_all`, dropping
both the order and the "MUST run before register_all" comment that 27163ee5
(2026-09-14) carried. PTB dispatches at most one handler per group and the
first registered wins, so the command-forwarding catch-all
(`MessageHandler(filters.COMMAND ...)` in register_all) claimed every
extension command in any chat passing the group filter, forwarding it to
the agent. Verified empirically: with the chat passing the filter,
forward matched /names at position #28 before the extension handler at
#36; third seam-loss incident (after 2026-10-02 and the v4.14 merge).

## Fix

bot.py: load_extensions before register_all again, comment restored with
the mechanism and the incident. Regression test
tests/ccgram/test_extension_dispatch.py drives the real create_bot
through PTB process_update (extension via the real seam, forward mocked at
registry's import site, transport stubbed) and pins BOTH directions:
extension commands outrank the catch-all, unknown commands still reach it.

## Deploy

Both bridges 2026-10-18 (deploy contract script): extension loaded and
service restarted on each (bird journal, Mac ~/Library/Logs/ccgram.log,
new pid 16463). Live /names confirmation pending the maintainer's retry
in the affected topic (only the Telegram user can send it).
