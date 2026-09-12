---
id: TASK-31
title: Contextual variant picker (zai vs claude) at session creation
status: Open
assignee: []
created_date: '2026-09-07 11:20'
updated_date: '2026-09-07 11:20'
labels: []
dependencies: []
---

## Description

User request 2026-09-07: new sessions created from Telegram (and
reopened ones that relaunch an agent) always launched official Claude
Code, never zai. Root cause: providers/claude.py hardcodes
launch_command="claude"; herdr just executes the string ccgram passes.
SHORT-TERM FIX SHIPPED (config-only): CCGRAM_CLAUDE_COMMAND=zai in
~/.ccgram/.env (backup made); resolve_launch_command already supports
the override upstream, verified live (resolve + YOLO flag). All claude
launches now go through the zai wrapper (bridge restarted 11:16).

THE FEATURE (deferred): contextual choice at /new time. Design: zai
registered as a first-class provider (fork-only providers/zai.py
subclassing ClaudeProvider with launch_command="zai"); the /new
provider picker is registry-driven so a registered provider appears
for free, and provider_name persistence in window_state makes
resume/recovery relaunch the same variant with zero store changes.
Ripples: _YOLO_FLAGS entry, cc_commands projects dir (zai mirror),
detect_provider_from_command basename, has_yolo_mode. Lighter shape:
variant sub-step persisting a "claude@zai" composite.

Watch: with the global override, resume of sessions ORIGINALLY created
as official claude also relaunches via zai; --resume reads from the
wrapped binary's projects dir (the zai mirror), so old official-claude
sessions may not resume cleanly. If the user hits this, the picker
feature becomes urgent.

PROVIDER SHIPPED 2026-09-07 (commit in fork/main, deploy 4.10.4.dev33):
ZaiProvider registered fork-side (providers/zai.py, subclass of
ClaudeProvider, identity-only override). It now appears in the /new
provider picker and /agent override; provider_name persistence makes
resume/recovery relaunch zai. Global env default
(CCGRAM_CLAUDE_COMMAND=zai) stays as the fallback when no variant is
chosen. Battery 7083.

UPSTREAM ASSESSMENT (user asked): worth OFFERING, low controversy, but
the fork shape is zai-specific (hardcoded wrapper). The generic
upstream pitch: config-declared provider VARIANTS
(e.g. CCGRAM_PROVIDER_VARIANTS="claude:zai=..."), discovered and
selectable in the existing picker, default unchanged. Additive,
opt-in, no default change: passes the user's
"particularly uncontroversial" filter IF the user ever wants to
open it. NOT opened: standing approval rule.
