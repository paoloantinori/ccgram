---
id: TASK-47
title: Numbered-list message falsely rendered as choice UI (selection scraper false positive)
status: Open
assignee: []
created_date: '2026-09-29 19:15'
updated_date: '2026-09-29 19:15'
labels: [incident, herdr, interactive-ui, parsing]
dependencies: []
---

## Incident (2026-09-29, maintainer report)

Telegram showed a choice UI (navigation buttons + quick-pick buttons) on
a Claude message that was plain text followed by a numbered list.
/screenshot confirmed no actual choice prompt in the terminal. Journal:
two "Sending interactive UI" sends at 18:30:44 and 18:34:30 (window
e06e7f2c, adopted at the 18:30 restart). events.jsonl contains ZERO
AskUserQuestion/ExitPlanMode/request_user_input events, so the hook path
is excluded: the trigger was the terminal-scraping detector.

## Root cause (reproduced offline, 2026-09-29)

The catch-all SelectionUI pattern in terminal_parser.py anchors on ANY
line starting with "❯ " or "› " (top regex `^\s*[❯›]\s`, anchor_last)
and accepts ANY indented numbered item as the bottom
(`^\s+\d+\.\s`, added for /remote-control which has no footer). Claude
message content routinely contains both shapes in one capture: a `›`
blockquote/expandable-quote line or an echoed `❯ git ...` command,
with a markdown ordered list further down. The span between them is
extracted as a selection UI; parse_direct_choices then turns the
numbered items into quick-pick buttons. Repro (both fire):

    ["Here is the plan:", "", "› the current branch is ...", "",
     "Choose one:", " 1. First", " 2. Second", " 3. Third",
     "─────", "❯", status lines...]          -> SelectionUI (false)

    ["...", "❯ git log --oneline -3", "abc1234 fix", "",
     "Options:", " 1. First", " 2. Second"]  -> SelectionUI (false)

Intervals explained: the false pair must coexist in one capture with
the glyph line last, which most messages lack. Also noted: pyte pads
display lines to full width, so the idle input box "❯" matches the top
regex too (bare "❯" does not, padded does).

## Fix direction (recommended)

Two tightenings on the catch-all, preserving /remote-control:
1. Require real content after the cursor glyph: a genuine selection
   cursor renders the option text next to "❯"; the idle input box is
   empty. Top regex becomes `^\s*[❯›]\s+\S`.
2. Bound the anchor's distance from the pane bottom (a real prompt
   sits a handful of lines above the footer; message content can be
   far above): skip the pattern when the last glyph line is more than
   ~15 lines above the last non-empty line.

Regression tests: the two repro cases above must parse as None; the
existing /remote-control and compact-selection fixtures must keep
matching.

## Definition of done

Repro as unit tests (red on current code), fix green, no regression in
the selection-detection suite, gates, deploy both bridges.
