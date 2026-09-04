# CLAUDE.md

ccgram: Telegram bot that bridges Telegram Forum topics to AI coding agent sessions (Claude Code, Codex, Gemini, Pi) via tmux or herdr multiplexers. Each topic is bound to one multiplexer window running one agent session.

Tech stack: Python 3.14, python-telegram-bot, uv. This checkout is a working fork: branch `port-4.6` = upstream main (alexei-led/ccgram) + our additive features. Keep it rebased onto upstream; divergence is only our features, never rewrites of his code.

## Common Commands

```bash
make test                              # Full unit suite (must be green before commit)
make lint                              # ruff + lazy-import contract (must pass)
make typecheck                         # pyright, needs PYRIGHT_PYTHON_FORCE_VERSION=latest
make fmt                               # ruff format (CI enforces format; always run before commit)
scripts/dod.sh --reviewed              # FULL DoD gate: battery + review attestation -> deploy stamp
```

**Deploy (bird bridge)**: the PreToolUse hook (`.claude/hooks/deploy-gate.sh`) blocks `uv tool install` and every `systemctl restart ccgram` form (plain, sudo, --user, .service) unless a fresh DoD stamp exists for the current HEAD. The stamp only comes from `scripts/dod.sh --reviewed` and expires in 30 minutes; any commit invalidates it. **Never deploy without running it. Never bypass the hook.**

Deploy command (the `--with` is REQUIRED; without it the reactions feature installs nowhere and dies silently):

```bash
uv tool install . --force --with /home/pantinor/data/repo/apps/ccgram-ext
```

After restart, verify the journal shows `extension loaded: main` (no line = the ext did not ship) and that bindings counts survived (see State files).

## Definition of Done (per task)

1. Full battery green: `make test`, `make lint`, `make typecheck`, format check.
2. `/simplify` run on the task's diff (apply findings or note skips).
3. `/code-review` high run on the diff; findings above threshold fixed.
4. Only then: commit, `scripts/dod.sh --reviewed`, deploy.

## Extension seam (fork features live out of tree)

Core carries ONE loader (`src/ccgram/extensions.py`) plus three integration lines (bot.py `load_extensions`, main.py `resolved_allowed_updates`, two `emit("message.delivered", ...)` in message_queue). Everything else fork-side lives in the separate repo `~/data/repo/apps/ccgram-ext` (package `ccgram-ext`, entry-point group `ccgram.extensions`, currently: reaction-triggered actions). Design: `docs/extension-seam.md`.

- New fork features go in ccgram-ext, never in files upstream actively develops.
- The `[reactions]` / `[reactions.speak]` sections of `~/.ccgram/toolbar.toml` are consumed by the ext, not by core. No table = feature inert.
- The `[topic-icons]` section in toolbar.toml is DORMANT config: the identity-icon feature (#197) was not re-ported after the v4.9 reset. Do not assume it works.

## Core Design Constraints

- **1 Topic = 1 Window = 1 Session**: routing keyed by multiplexer window id. On herdr, window ids are `herdr-session-v1-<digest>` session digests (NOT tab/pane ids); the herdr backend is the anti-corruption layer that owns all id translation. Upstream shares this model since v4.9.x (guarded session identity, `WindowRef.topic_eligible` verdict).
- **Delivery is at-least-once with incremental watermarks**: the transcript byte offset is a *delivered watermark*. Receipts settle per message; settled receipt prefixes commit incrementally (not queue-idle-only, since #205/#207). Failed sends leave receipts unsettled; a restart replays rather than loses.
- **No message truncation** at parse layer; splitting only at send layer (4096 limit).
- **Layering invariants are enforced by test**: handlers use the `TelegramClient` Protocol (never raw PTB bot), singletons only via sanctioned seams, in-function imports need a `# Lazy:` marker. Enforcers include `test_multiplexer_boundary.py`, `test_query_layer_only_for_handlers.py`, `test_window_state_access_audit.py`, `test_session_state_ports_audit.py`, `test_no_tty_outside_backend.py`.

## Upstream flow

We file issues upstream (alexei-led/ccgram); the maintainer merges selected PRs (ours and others') and cuts frequent releases. When his releases land: cherry-pick/rebase port-4.6 onto upstream main, drop our superseded duplicates, keep our additive features and the extension seam intact (verify seam files byte-identical after every integration). Plan and status live in `backlog/docs/upstream-pr-plan.md`; work items in `backlog/tasks/` (Backlog.md format, managed via the `backlog` CLI).

**Never open a PR, issue or comment upstream without explicit user approval first.** Drafts get discussed together before anything is posted.

## State files (~/.ccgram/)

- `state.json`: chat-scoped thread bindings (`chat_thread_bindings`, keys `user:chat:thread`; the legacy `thread_bindings` key stays empty after the v4.9 migration, count the NEW key or the check false-alarms), window states, display names, `private_topic_chats`
- `session_map.json`: hook-written window->session mapping
- `monitor_state.json`: delivered watermarks (byte offsets)
- After ANY restart, verify bindings/session_map counts before trusting "service active" (see project memory: ccgram-port-4.6-incident).

## Standing deployment rules (bird)

- `AUTOCLOSE_DONE_MINUTES=0`, `AUTOCLOSE_DEAD_MINUTES=0` (autoclose once deleted topics; upstream now closes instead, we keep it off).
- `CCGRAM_VOICE_AUTOSEND=true` (upstream flag); the speak action is armed in toolbar.toml with the LAN omnivoice endpoint + pockettts fallback model.
- Never run a second poller against the same bot token (409 getUpdates).
