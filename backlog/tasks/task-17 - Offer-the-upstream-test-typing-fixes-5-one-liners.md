---
id: TASK-17
title: Offer the upstream test-typing fixes (5 one-liners)
status: Done
assignee: []
created_date: '2026-09-04 19:30'
updated_date: '2026-09-04 19:30'
labels: []
dependencies: []
---

## Description

Commit 38c574e fixed five typing errors in upstream's OWN new tests (verified identical on pristine upstream/main: two Optional subscripts in test_text_handler.py, three _FakeWindow argument positions in test_multiplexer_tmux.py). Tiny good-faith PR, candidates to offer upstream. Blocked on the same approval rule; bundle with TASK-14/15/16 timing.

UPDATE 2026-09-06: user approved contributing ("contribuisci") after the
v4.10.3 integration confirmed the five errors still live on main. Issue
https://github.com/alexei-led/ccgram/issues/238 (CONTRIBUTING requires
issue-first), PR https://github.com/alexei-led/ccgram/pull/239 from
branch fix/test-typing-pyright (2 files, +5/-3: two non-None asserts,
three pyright ignores on the erroring argument lines only). Both texts
passed unslop before sending. Status now waits on the maintainer.
