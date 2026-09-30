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

## CONFIRMED with live artifact (2026-09-29 evening, maintainer screenshot)

The screenshot of the incident pane (anti-vocale agent on the Mac)
shows the false-positive source: Claude Code's QUEUED-INPUT block,
the highlighted rendering of messages typed while the agent is
mid-turn:

    > 1. Avendo imparato che il telefono da numeri diversi, ...
      2. Se ffmpeg da risultati migliori, ...

The first queued line matches the catch-all's cursor anchor
(`^\s*[❯›]\s`) and the second matches its numbered-item bottom
(`^\s+\d+\.\s`). The trigger flow is the bridge's core interaction:
user sends a Telegram message while the agent works, ccgram types it
into the pane, Claude Code queues it with the > rendering, the polling
scraper reads the queue block as a selection prompt. This is why the
false UI appears "sometimes": it needs a mid-turn message whose queued
text contains a numbered-item-shaped line below a glyph line.

The artifact RETRACTS two of the fix direction's tightenings: the
queued line HAS content after the glyph, and it sits a few lines above
the footer. The remaining honest discriminator is agent run-state:
the pane showed the spinner (agent working); a working agent cannot
be simultaneously asking a selection (a real prompt pauses the turn).
ccgram already has native agent_status (herdr push cache +
cold-cache fallback). FIX: gate the interactive scraping on
non-working agent status; keep the pattern tightenings as
defense-in-depth where they still apply (empty-input-box anchor).

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

## Fix direction (revised after artifact)

Primary: gate interactive-UI scraping on the agent's native run-state
(only scrape when NOT working). A working agent showing a
selection-shaped region is queued input, not a prompt.
Secondary (defense-in-depth on the catch-all): require content after
the cursor glyph (`^\s*[❯›]\s+\S`; the padded empty input box must
not anchor).

Regression tests: the two repro cases above must parse as None; the
existing /remote-control and compact-selection fixtures must keep
matching.

## Fix (2026-09-30)

Implemented after the artifact and two review rounds:
agent_status_cache gains agent_working(window_id); interactive
interpretation is suppressed at observe._resolve_status (covers BOTH
the strategy parse and the provider parse, which the first cut missed)
while the agent WORKS, falling through to the native working status;
pane_has_interactive_prompt returns False for a working agent, which
breaks the dismissal-confirmation loop that rejected every text retry.
Deliberately NOT gated (review findings): _capture_interactive_content
(the funnel for hook-authoritative dispatch; a scraped-status veto
must not suppress hook ground truth, and a stale working entry during
a push-stream drop would hide real prompts), and the non-active pane
scan (window-level status cannot speak for a sibling pane in
multi-pane windows; that hole needs per-pane status and stays open
upstream of this fix). Unknown status keeps scraping, so tmux and
cold-cache moments are unchanged; Claude's real AskUserQuestion and
ExitPlanMode arrive through the transcript tool_use path, not the
scraper. The catch-all's cursor anchor now requires content after the
glyph (the pyte-padded idle input box can no longer anchor). Gates:
seam-level gate tests red-green verified against the patched-out
helper; pyright clean on the changed files.

## Follow-on incident (same day)

The false latch did not just show buttons: text messages to the topic
were REJECTED in a loop (dismissal confirmation re-ran the same broken
detector). The confirmation gate above fixes that; the rejection
itself is by design once a REAL prompt holds.

## Follow-ups (2026-09-30 altitude review)

- The gates read herdr's push-cache status; on tmux (upstream default)
  agent_working is constant False and the class stays live. The
  backend-independent discriminator is co-presence of an active spinner
  line on the same screen (parse_status_block already extracts it);
  design it before contributing this fix upstream.
- Gate placement per review: suppression lives at observe._resolve_status
  (covers strategy AND provider scrapers) plus the non-active pane scan;
  the capture helper under the hook path is deliberately NOT gated (a
  scraped-status veto must not suppress hook-authoritative dispatch).

## Definition of done

Repro as unit tests (red on current code), fix green, no regression in
the selection-detection suite, gates, deploy both bridges.
