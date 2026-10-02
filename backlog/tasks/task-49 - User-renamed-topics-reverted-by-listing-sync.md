---
id: TASK-49
title: User-renamed topics reverted by listing sync within one cycle (Mac name churn)
status: Done
assignee: []
created_date: '2026-10-02 06:10'
updated_date: '2026-10-02 06:10'
labels: [incident, herdr, naming]
dependencies: []
---

## Incident (2026-10-02, maintainer screenshot + report)

Mac topics kept being renamed: after /names apply (ccgram-ext) set
clean titles, the topic was renamed three times in one minute, ending
back at the long auto title "Claude - anti-vocale > anti-vocale > p1".

## Root cause

SessionManager.set_display_name is the user-choice seam (in-tree topic
rename AND the ext /names both route through it), but the periodic
prune_stale_state pass feeds live listing names into sync_display_names
unconditionally. On herdr the live name is the auto-stamped
"Provider > workspace > tab > pane" prefix, which NEVER equals a user
choice, so every 60s cycle reverted the display name and the next
emoji flip re-stamped the long title. Permanent fight on herdr; on
tmux only until rename_window makes them equal.

## Fix (99deea3d, deployed dev136 both bridges)

set_display_name pins the name in the router (persisted in state.json
as window_display_pins); sync skips pinned windows in both the router
dict and the WindowState reconcile; the pin is pruned with the name
when the window dies. The raw router setter and the hook-driven launch
name stay unpinned, so auto naming at creation is unchanged. Red-green
pin tests at both levels (router + SessionManager sync). Also: dod.sh
now includes the tts extra (upstream merge brought src/ccgram/tts;
pyright needs edge-tts installed or the stamp cannot be issued).
