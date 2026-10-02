# ccgram (fork)

Fork of alexei-led/ccgram on `fork/main`; remotes: `mine`/`fork` =
paoloantinori/ccgram (push target), `upstream` = alexei-led/ccgram,
`botjkeee`/`devinyan` = contributor mirrors. Commit style: conventional
commits, lowercase, no close keywords.

## Deploy contract (the 2026-10-02 incident)

The bridge runs on BOTH bird and the Mac (one poller per chat), installed
as a uv tool. The fork's features (reactions, topic icons, ccbot-style
short topic names, `/names`) live OUT-OF-TREE in the `ccgram-ext`
package, loaded through the extension seam (`src/ccgram/extensions.py`).

**A plain `uv tool install . --force` SILENTLY DROPS the extension.**
Always deploy through `~/data/repo/personal/cc-config/ccgram-bridge-deploy.sh`,
which installs `--with` the ext, restarts the service, and FAILS unless
the journal shows `extension loaded:` after the restart (the loader also
logs a `no extensions loaded` warning since 2026-10-02).

Manual form, if the script is unreachable:

- bird: `cd ~/data/repo/apps/ccgram && uv tool install . --force --with ~/data/repo/apps/ccgram-ext && systemctl --user restart ccgram.service`
- mac: `ssh mac` then same with `/opt/homebrew/bin/uv`, paths `~/data/repo/personal/ccgram{,-ext}`, restart via `launchctl kickstart -k gui/$(id -u)/com.user.ccgram`.

## Topic naming contract

`CCGRAM_TOPIC_EMOJI=off` (set in `~/.ccgram/.env` on both machines)
silences the core's automatic title renamer; the extension's one-shot
ccbot names own the titles, and `/names dry-run|apply` are the manual
controls. The flag is honored in `update_topic_emoji` (tests in
tests/ccgram/handlers/status/test_topic_emoji_gate.py): if renames come
back during state transitions, that gate is the first suspect. The
`/sync` command force-refreshes titles through the same naming chain
either way. The provider label in topic names resolves the zai variant
from the transcript root (`handlers/provider_display.py`).

## Repo rules

- Run `uv run pytest tests/ccgram -q` and `uv run ruff check src/ tests/`
  before committing; pyright on touched files.
- Fork features go in ccgram-ext via the seam, never in upstream-hot
  core files; the core delta stays at the loader plus the two
  message-queue emits (design: docs/extension-seam.md).
- NEVER propose the seam or fork features upstream without explicit user
  agreement first (standing instruction 2026-08-31).
- Local task tracking: backlog/tasks/ with a task-N file per task; mark
  done in-file when completed.
