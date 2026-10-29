---
id: TASK-186
title: test_new_window_sync leaks a real thread_router binding into sync audit tests
status: Open
assignee: []
created_date: '2026-10-29 08:05'
updated_date: '2026-10-29 08:05'
labels:
  - kind/test-isolation
dependencies: []
references: []
priority: low
ordinal: 101
---

## Finding (2026-10-29, surfaced by the TASK-185 /simplify gate)

`tests/ccgram/handlers/topics/test_new_window_sync.py::test_topic_name_falls_back_to_cwd`
wires the real orchestration against the real SessionManager and leaves a
binding `(user 12345, thread 88) -> "@6"` in the global thread router.
When `handlers/test_sync_command.py::TestSyncAuditSeparatesLivenessFromAdoption`
runs after it in the same process, that stale binding makes the audit
report a `ghost_binding` for "@6" and the test fails.

Proven pre-existing on clean fork/main (3ea09652): the pair fails with no
working-tree changes. The full suite never fires it because collection
order runs `handlers/test_sync_command.py` before `handlers/topics/`, so
the leak flows into tests that do not audit ghosts.

## Fix direction

Either give `test_new_window_sync` a SessionManager/router reset fixture
(the way `tests/conftest.py::_clear_window_store` clears window state), or
extend the sync audit test's existing save/restore fixture to also clear
`thread_bindings`/`chat_thread_bindings` it did not create.
