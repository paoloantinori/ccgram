# Normalize session cwd at the state boundary

From the 2026-10-03 upstream review of the upload-path fix (task-51):
the absolute-cwd invariant is enforced in ONE consumer of view.cwd
(file_handler._resolve_upload_dir) while the cwd is written unvalidated
at the state boundary and served raw to every handler.

## Evidence (from the review pass on commit 090dd3ba)

- hook.py persists str(normalized.cwd) unvalidated.
- identity_state.get_identity serves it to every consumer.
- Consumers taking view.cwd raw include restore_command.py,
  send_command.py, status_bar_actions.py, toolbar_callbacks.py,
  shell_context.py: the same tilde or relative cwd breaks each of them
  separately (e.g. restore_command silently reports no directory).
- Tilde expansion at the consumer is also ambiguous: the right home is
  only knowable where the cwd is recorded, not in the bridge process.

## Design sketch

Normalize once where the cwd is persisted (window_state_store /
identity_state boundary): expand tilde against the session owner's
home at write time, reject or absolute-ize relative forms there, and
let every consumer trust an absolute sane cwd (boundary discipline).
The per-handler guard in file_handler stays as defense in depth or is
removed once the boundary guarantees the invariant.

## Verification bar

Unit tests at the store/identity boundary for every cwd form (absolute,
tilde, relative, control chars); a sweep asserting every view.cwd
consumer survives a malformed legacy state entry; regression: the
upload notification still carries an absolute path.

## Status

Open. Candidate follow-up upstream contribution after task-51's PR
lands; do not bundle into it (the upstream PR stays minimal on
purpose).
