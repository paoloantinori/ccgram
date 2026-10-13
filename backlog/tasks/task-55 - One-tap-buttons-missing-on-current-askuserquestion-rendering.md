# Task 55: One-tap buttons missing on current AskUserQuestion rendering

Status: done (2026-10-13)
Reported: 2026-10-13, user on Telegram: Claude Code interview arrived without the numbered option buttons.

## Problem

Claude Code's current TUI renders the AskUserQuestion header as a decorative
"☐ <header>" line and indents a description under every option. The direct
choice parser vetoed any capture containing a bare checkbox (multi-select
guard false positive) and only consumed indented descriptions for Pi, so
single-select questions got navigation-only keyboards.

## Fix (commit 985734d)

- Multi-select guard matches a checkbox only on an option line, in any
  position (before, after the number, after the label).
- Description consumption is provider-neutral; the safety against numbered
  prose moved to menu-shaped anchors: a cursor on an option line, or a
  selection footer (verb set from codex/gemini footers, pager verb
  "continue" and editor hints excluded).
- Verified red/green against a live pane capture of a real question.

## Known limits (review round 2, deliberately accepted)

- A hypothetical multi-select renderer that puts the checkbox ONLY in the
  header would get buttons; every real renderer observed marks options.
- A menu followed by unbroken indented prose whose numbering continues the
  sequence merges the prose into the block; indistinguishable from a real
  mixed menu and fails toward extra buttons only.

## Upstream

Same bug exists upstream (feature merged from 790ba494); issue-first
contribution prepared per the standing workflow.
