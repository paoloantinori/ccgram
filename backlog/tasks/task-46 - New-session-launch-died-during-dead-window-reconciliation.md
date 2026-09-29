---
id: TASK-46
title: New-session launch died during dead-window reconciliation (2026-09-29 09:11)
status: Done
assignee: []
created_date: '2026-09-29 09:30'
updated_date: '2026-09-29 09:30'
labels: [incident, herdr, recovery, launch]
dependencies: []
---

## Incident

2026-09-29 09:11: creating a new session from Telegram failed with
"Session did not register with ccgram and is gone". Single occurrence
so far.

## Evidence (journal, 09:10:50 to 09:11:18)

- 09:10:50 dead window c1e2aeef (Claude > minix_ansible_config > p1)
  shown the recovery UI.
- User acted on the recovery flow; a new window b5e1b596 was created.
- 09:11:15 the "dead" pane RESURRECTED under a new identity
  (reconciled c1e2aeef -> 2861c4d3) and ccgram deleted the old id.
- 09:11:18 wait_for_session_map_entry timed out for b5e1b596 and
  window_presence returned False: the new pane was not merely
  unregistered, it was GONE. The flow reaped it and showed the error.

## Root cause CONFIRMED (2026-09-29 forensics, live evidence)

The sibling-reconciliation hypothesis is RETRACTED. The new pane was
never killed: it is STILL ALIVE. Forensics found an orphaned herdr
workspace "wN" (minix_ansible_config) created by the 09:11 recovery
fresh flow, whose pane booted into a healthy GLM session (session
c9283cd9) that kept working for ~2 hours after ccgram declared it
gone (minix network diagnostics visible in its scrollback at 10:45).

Mechanism, end to end:
1. create_topic_target's _await_created_session_target accepted the
   TERMINAL FALLBACK record (claude terminal, session not yet
   published) and minted window_id from its digest (b5e1b596).
2. Claude published its session; herdr's record rotated
   fallback -> sessionful WITHOUT aliasing the fallback digest (the
   alias chain covers other transitions: the old pane's
   c1e2aeef -> 2861c4d3 rotation WAS aliased; the fallback rotation
   is not).
3. The recovery flow's 5s wait_for_session_map_entry expired (the
   hook writes under the sessionful key; no redirect exists to
   re-resolve the fallback id).
4. window_presence(b5e1b596) on the raw fallback digest: absent from
   the snapshot -> False.
5. Flow declared "Session did not register with ccgram and is gone",
   reaped the topic, abandoned a booting pane.

Side effect of the same morning: the user's 09:48 retry resumed the
SAME session id (c9283cd9) in a second pane (w23:p2), so two parallel
sessions of one repo ran for hours, one invisible to the bridge.

## Already refuted (2026-09-29 diagnostics)

Not a zai-configuration problem: CCGRAM_CLAUDE_COMMAND=zai resolves
through the provider registry; the wrapper is on the service PATH and
exports the zai CLAUDE_CONFIG_DIR; zai settings.json carries all
ccgram hooks (rewritten by the 2026-09-28 21:59 sync, intact); the
hook binary writes session_map from a claude-shaped payload; and a
live end-to-end probe (fresh herdr tab, pane run zai) started Claude
Code v2.1.284 on GLM-5.3 and registered within seconds.

## Fix (2026-09-29)

Root fix in the herdr adapter: _await_created_session_target now
accepts ONLY the stable session-backed identity (skips terminal
fallback matches), so creation can never mint a digest that rotates
during hook registration; discovery budget 5s -> 20s to cover real
boot under load (measured past 5s on the incident morning). The
session_map wait default went 5s -> 15s (the hook entry lands under
the key creation now holds, so this is headroom, not the fix), and
the recovery flow's explicit 5.0 was dropped in favor of the default.
A pane that never publishes a session now fails creation cleanly and
rolls back its tab+workspace instead of committing a rotating target.

Review round (2026-09-29, /simplify 4 agents + code-review) closed the
residual hole: _live_ref now stamps terminal-fallback records
topic_eligible=False, so the ADOPTION path (unbound-window discovery
after 15s) can no longer mint a topic on the same rotating digest
through a different door; the picker (list_windows filters on
eligibility) hides them too, while find_window_by_id keeps them
addressable (routability contract preserved; tests updated to observe
it there). Also: discovery poll interval 0.1s -> 0.5s (a 20s window at
0.1s meant ~200 agent.list subprocesses per slow launch), the
"terminal" kind promoted to _TERMINAL_FALLBACK_KIND used at both
sites, and resume_command's explicit timeout=5.0 dropped (three launch
flows had diverged to 15/15/5). Accepted and documented: worst-case
provisioning latency is now discovery 20s + hook wait 15s (sequential
budgets), and a genuinely dead launch on fast backends reports 10s
later than before; both trade against the false "gone" that destroyed
sessions.

Residual, deliberately NOT fixed ccgram-side (herdr upstream gap):
the fallback->sessionful rotation not carrying an alias also affects
any path that adopts a fallback-identity window into a topic; herdr
side should link those digests. Tracked as a follow-up note below.

Known residual (code-review 2026-09-29, accepted): topics still bound
to a LEGACY fallback digest (only the pre-fix adoption path could mint
those) drop out of every list_windows consumer, so /sync title
reconciliation and the adoption picker skip them silently; the
unfiltered reconciliation listing still sees them for liveness and
cleanup, and no new fallback bindings can be created, so the class
ages out. Also accepted: a genuinely-sessionless claude/codex/gemini
pane (if one ever exists; the fallback is documented as boot-gap only)
would now fail creation after 20s instead of binding via the fallback.

## Follow-ups

- herdr upstream: fallback->sessionful digest rotation should carry
  the previous digest as an alias (the c1e2aeef-style transitions
  already do); would make the whole class structurally impossible.
  Not filed with them yet (needs maintainer approval for external
  communication).
- The orphaned wN workspace pane: surfaced to the maintainer; adopt
  or close by hand (it holds ~2h of session work).

## Definition of done

Reproduced or three failed attempts to reproduce documented; if
reproduced, root cause named with mechanism and fixed with a
regression test. -- Reproduced via live forensic evidence; root cause
named with mechanism; fix + red-green regression tests in
test_herdr_backend.py; gates and deploy follow.


## Closure (2026-09-29)

Both review gates ran with all findings landed or documented; serial
battery 7596 green; deployed and verified on bird (4.11.3.dev91+dev,
started 13:01:54, zero journal errors) and Mac (4.11.3.dev91+dev,
clean startup). Commits 04cff201 + format follow-up, pushed as be7b076e.
