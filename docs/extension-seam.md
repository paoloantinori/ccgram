# Extension seam (fork-local, designed for upstream offering)

Goal: features live OUTSIDE the core repo (package `ccgram-ext`, separate
repo `~/data/repo/apps/ccgram-ext`), loaded by the core via standard
Python entry points. Core carries ONE small loader; after that, new fork
features cost zero core-file conflicts.

## Core contract (v1, all of it)

New module `src/ccgram/extensions.py` (fork-only file):

- `load_extensions(add_handler)`: scans entry points group
  `ccgram.extensions`, resolves each to `register(api)`, wraps every call
  in try/except + logger.error (one broken extension never blocks boot).
- `ExtensionApi` given to each `register`:
  - `register_ptb_handler(handler, update_type: str)`: adds the PTB
    handler and records the update type for the allowed_updates merge.
  - `on(event: str, listener)`: subscribe to a core domain event.
    Listeners may be sync or async; async ones are scheduled
    (ensure_future), never awaited inline; every listener call is isolated (exception -> logger.warning, delivery
    never blocked).
- `resolved_allowed_updates(base: list[str]) -> list[str]`: base plus
  extension-registered update types.
- `emit(event: str, **payload)`: fire an event; no-op with no listeners.

Core integration points (the ENTIRE permanent merge debt):

1. `bot.py` `create_bot()`: `load_extensions(application.add_handler)` after the core
   handler registration (before post_init: allowed_updates is captured by
   run_polling before post_init runs).
2. `main.py`: `allowed_updates=resolved_allowed_updates([...])` (the base
   literal stays; extensions contribute theirs).
3. `message_queue.py`: two `emit("message.delivered", chat_id=, message_id=,
   window_id=, text=, thread_id=)` calls at the delivery sites (fresh send
   and edit-convert) replacing any feature-specific tracking.
4. `window_launch_service.py`: one `emit("topic.bound", user_id=, chat_id=,
   thread_id=, window_id=, window_name=, cwd=)` after the creation bind.

Domain events (v1): `message.delivered` (queue delivery sites) and
`topic.bound` (window_launch_service, after the creation bind). Events are
observation hooks: payload fields are add-only; listeners must tolerate extras.

## ccgram-ext (separate repo)

- pyproject declares `[project.entry-points."ccgram.extensions"]
  main = "ccgram_ext:register"`.
- Contains: reaction-triggered actions (issue #195) and topic identity
icons (issue #197), both upstream not-planned. Reactions:
  PTB MessageReactionHandler + own LRU fed by `message.delivered`, own
  reading of the `[reactions]` / `[reactions.speak]` sections from the
  same `~/.ccgram/toolbar.toml`, self-contained OpenAI-compatible TTS
  client (response_format / timeout / Retry-After on 429; core tts/ stays
  upstream-shape).
- Imports from ccgram: config, telegram_client, message_sender helpers,
  the multiplexer proxy, screenshot renderer. Nothing else.
- Tests live in ccgram-ext.

## Deployment

`uv tool install . --force --with ~/data/repo/apps/ccgram-ext`: the entry
point travels with the package metadata; presence + config = active.
Core without the ext installed: loader finds nothing, feature inert.

## Upstream offering (later, not now)

Once proven in production: offer the loader (extensions.py + the three
integration lines) as a PR, framed as the delimited seam HE scopes.
Not before evidence exists.
