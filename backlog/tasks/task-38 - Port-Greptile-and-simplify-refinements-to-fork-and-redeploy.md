---
id: TASK-38
title: Port the Greptile and review refinements onto fork/main and redeploy both machines
status: Done
assignee: []
created_date: '2026-09-20 22:52'
updated_date: '2026-09-21 10:40'
labels: [delivery, deploy, upstream-sync]
dependencies: []
---

## Description

The three upstream-bound branches absorbed a second hardening round that
fork/main (the production line) does not carry yet. Port and redeploy.

From the Greptile review of the PRs (all confirmed, fixed upstream):
1. PR 263: the idle-stall heuristic was unsound (an in-flight RetryAfter
   holds any count flat exactly like a wedge). Upstream now uses a 90s
   total budget (_INTERACTIVE_QUEUE_JOIN_TIMEOUT_S); the fork still has
   the 8s wait_for from the first round, which breaks order on healthy
   slow drains.
2. PR 264: the watchdog is now a daemon threading.Timer armed in
   post_stop and cancelled in post_shutdown (fires even when the event
   loop is blocked synchronously); the fork still arms via
   loop.call_later from the conflict branch at 300s.
3. PR 265: config parsing falls back to the default for non-finite
   values (inf/nan) with parametrized tests; the fork helper lacks the
   math.isfinite guard.

From the /simplify pass on the port commit (08381e5a):
4. _skip_is_current becomes a one-liner delegating to
   _skip_rebind_verdict (deletes the duplicated body; semantics
   provably identical), docstrings corrected (None also when the
   validator is absent, and the expiry docstring still describes the
   pre-conservatism behavior).
5. Unify the tolerant float parsers: move _env_float into config.py,
   use it for the deadline knob (restores the invalid-value warning the
   port dropped), keep _AUTOSKIP_RETRY_S on it.
6. Add the missing knob tests in test_config.py (default, override,
   floor, invalid, non-finite), matching every other float knob's
   coverage.

Definition of done: fork suite green (make test equivalent), ruff and
pyright clean, commit with gates markers, push mine/fork/main, redeploy
bird (uv tool reinstall from ~/data/repo/apps/ccgram plus systemctl --
user restart ccgram) and Mac (pull, uv sync --all-extras, launchctl
kickstart -k gui/501/com.user.ccgram; delegate to the cc-config agent),
then verify the Starting line and a clean log tail on both.

## Progress

- Port commit 1a35099b (Gates: /simplify 3-agent pass applied; code-review
  high findings from the PR previews applied; pytest 7324 passed; ruff+pyright
  clean) plus 71668fb7 (gate-exempt lint marker). Pushed: HEAD == mine/fork/main.
- Bird deploy verified 2026-09-21: uv tool venv carries
  _INTERACTIVE_QUEUE_JOIN_TIMEOUT_S = 90.0 (message_routing.py:42),
  threading.Timer watchdog (bot.py:89,218), math.isfinite guard
  (config.py:64); service restarted clean (23:05 Sep 20, again 06:08 and
  06:59 Sep 21, all clean systemd stops, no watchdog firing). Journal
  warnings are agent-side (one session's prompt-too-long through the
  litellm fallback chain) and transient DNS at 09:49, not bridge defects.
- Mac redeploy: confirmed done by the ccgram-mac agent on 2026-09-21
  (checkout 71668fb7, uv tool install --force --with the ccgram-ext
  checkout; verified 4.11.3.dev30+dev active, extension loaded: main,
  bindings intact). Mac is on the 90s-budget build, not the 8s one.
- Closed 2026-09-21 10:40: all DoD items verified on both machines.
