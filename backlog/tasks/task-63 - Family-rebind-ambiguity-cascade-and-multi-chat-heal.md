# Task 63: family-rebind ambiguity cascade and multi-chat heal-once

Status: open (recorded 2026-10-31, from the code review of the sibling-guard fix)

## The cascade

Every conservative refusal of the family rebind (unknown sibling provider,
live same-family sibling, ambiguity) falls through to a NEW topic. Once
that duplicate's window churns, `find_family_match` sees two dead
same-family bindings with different old_window_ids and refuses as
ambiguous FOREVER: every later reopen adds another duplicate and the heal
never fires again for that family.

Reachable wedge today: a live hookless sibling whose provider is written
nowhere (no hook for the map, unrecognized launcher for foreground
detection) blocks every same-cwd reopen conservatively, feeding the
cascade with each churn.

## The multi-chat shape

One window bound in two chats heals at most one chat ever: the rebind
dedups binding rows by old_window_id and heals family[0] by iteration
order; the second chat's topic is then sibling-blocked while the rebound
window lives, and ambiguous after churn (same cascade).

## Direction to evaluate

- A preference rule instead of refusal when 2+ dead same-family bindings
  exist (most recently dead, or the one whose topic the user last used).
- Blocked reopens reusing the dead topic WITHOUT binding it to the new
  window (post a pointer notice) instead of creating a duplicate, when
  the only blocker is a conservative unknown.
- Multi-chat: rebind every binding row that dedups to the matched window
  id, not just the first.
