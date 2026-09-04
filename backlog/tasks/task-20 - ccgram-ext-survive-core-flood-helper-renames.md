---
id: TASK-20
title: ccgram-ext: survive core flood-helper renames
status: Done
assignee: []
created_date: '2026-09-04 19:30'
updated_date: '2026-09-04 19:30'
labels: []
dependencies: []
---

## Description

icons.py imported the private #206 helpers (_flood_paused/_pause_renames_for_flood) at module level: an upstream rename would have killed the whole extension at import (reactions included). Replaced with delegation + local 300s cooldown fallback, both branches tested. Commit 923cdcf, deployed with the icons port.
