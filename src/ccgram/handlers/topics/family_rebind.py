"""Reuse a dead binding's topic when the same workspace reopens.

Two self-healing triggers now exist for a topic whose agent went away,
and they must not be merged:

* ``orphan_watch`` (handlers/polling) heals a binding whose window id is
  still LIVE while its session_map entry died: it relinks the entry to a
  fresh transcript and seeds the monitor.
* This module heals a binding whose window id is GONE from the confirmed
  listing while a new window id appeared for the same workspace family.
  herdr derives window ids from its guarded agent session composite, so
  pane or container churn re-keys the target even though the user
  reopened the same session. Adoption would then create a duplicate
  topic ("X", "X 2", "X 3") while the old topic stayed bound to the dead
  id forever. At adoption time, exactly one dead same-family binding
  means the new window is that topic's agent back: rebind the topic,
  seed the monitor at EOF so the pre-rebind backlog is not replayed, and
  post one direct notice.

Zero or 2+ family candidates keep today's behavior (a new topic). The
alias-attested fold (``SessionManager.reconcile_window_aliases``) still
runs first in the monitor loop and remains the preferred heal; this is
the fallback for when no alias is ever attested. Both heals share the
same workspace-family notion, a (cwd, provider) pair; they differ only
in ambiguity direction, which each docstring states.

When the new window's hook entry has not landed yet, the rebind runs
without session facts and cannot seed an offset; the reopened session
then arrives through orphan_watch's relink (which seeds at EOF) or
through the ordinary first-sight path, where the restart replay cap and
its skip notice bound the backlog. Only the entry-known branch here
promises no replay at all.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from ...multiplexer.base import WindowRef, canonical_window_id
from ...session import session_manager
from ...session_map import raw_session_map_entry, read_session_map_raw
from ...session_monitor import NewWindowEvent, SessionMonitor, get_active_monitor
from ...session_query import iter_bound_topics, resolve_chat_id
from ...telegram_client import TelegramClient
from ...thread_router import thread_router
from ...window_state_ports import identity_state
from ..messaging_pipeline.message_sender import safe_send

logger = structlog.get_logger()

REBOUND_TEXT = (
    "🔁 Rebound to the reopened session in this topic"
    " (old window {old}, new window {new})."
    " Backlog up to byte {skipped} was skipped, not replayed;"
    " /history reads it."
)
REBOUND_PENDING_SESSION_TEXT = (
    "🔁 Rebound to the reopened window in this topic"
    " (old window {old}, new window {new})."
    " Its session has not registered yet; delivery starts when it does."
)


@dataclass(frozen=True)
class FamilyBinding:
    """One dead binding's owner, topic, and resolved family facts.

    Facts resolve from the persisted window state first and the raw
    session_map entry the hook left behind second: the state row outlives
    the window in state.json, and a pruned or never-written row falls
    back to the map.
    """

    user_id: int
    chat_id: int | None
    thread_id: int
    old_window_id: str
    cwd: str = ""
    provider: str = ""


def find_family_match(
    new_cwd: str, new_provider: str, bindings: Sequence[FamilyBinding]
) -> FamilyBinding | None:
    """The one dead binding from the same (cwd, provider) family, or None.

    An ambiguous workspace (two dead bindings on the same directory after
    dedup by old window id) must keep today's behavior, a new topic,
    rather than guess which topic to take over. An unknown new cwd or
    provider identifies no family. The provider compares casefolded as a
    defense; labels are canonical lowercase in practice, unlike the fold's
    exact compare over hook written entries.
    """
    if not new_cwd or not new_provider:
        return None
    seen_windows: set[str] = set()
    family: list[FamilyBinding] = []
    for binding in bindings:
        if binding.old_window_id in seen_windows:
            continue  # one topic per chat for the same window: one member
        seen_windows.add(binding.old_window_id)
        if (
            binding.cwd == new_cwd
            and binding.provider
            and binding.provider.casefold() == new_provider.casefold()
        ):
            family.append(binding)
    return family[0] if len(family) == 1 else None


def _entry_str(entry: Mapping[str, object] | None, key: str) -> str:
    if not isinstance(entry, Mapping):
        return ""
    value = entry.get(key)
    return value if isinstance(value, str) else ""


def _family_binding(
    user_id: int,
    chat_id: int | None,
    thread_id: int,
    window_id: str,
    *,
    raw: Mapping[str, object],
) -> FamilyBinding:
    """Resolve one dead binding's family facts from state, then the map.

    Liveness is already filtered; only dead bindings reach this.
    """
    entry = raw_session_map_entry(raw, window_id)
    return FamilyBinding(
        user_id=user_id,
        chat_id=chat_id,
        thread_id=thread_id,
        old_window_id=window_id,
        cwd=identity_state.get_cwd(window_id) or _entry_str(entry, "cwd"),
        provider=identity_state.get_provider_name(window_id)
        or _entry_str(entry, "provider_name"),
    )


async def _seed_monitor_at_eof(
    monitor: SessionMonitor,
    session_id: str,
    transcript_path: str,
    window_id: str,
    provider_name: str,
) -> int | None:
    """Seed the monitor at EOF; return the byte offset the topic skips.

    Seeding before the bind closes the replay window: binding first would
    let the next poll deliver the whole pre-rebind backlog into the topic.
    """
    await monitor.seed_session_offset_at_eof(
        session_id, transcript_path, window_id, provider_name
    )
    seeded = monitor.state.get_session(session_id)
    return seeded.last_byte_offset if seeded is not None else None


async def _family_decision(
    event: NewWindowEvent, windows: Sequence[WindowRef]
) -> tuple[dict[str, Any] | None, str, FamilyBinding] | None:
    """The new window's map entry, provider, and dead-family match, or None.

    Every refusal is a fail-closed pass back to today's behavior: a
    window the listing does not show as live and topic-eligible, no dead
    binding at all, an unreadable session map, or a family that is empty
    or ambiguous.
    """
    new_ref = next((w for w in windows if w.matches(event.window_id)), None)
    if new_ref is None or not new_ref.topic_eligible:
        return None
    # The cheap in-memory screen first. The known-unbound retry path
    # re-fires adoption every poll, so on a healthy system (no dead
    # bindings) the raw map read below must not run at all.
    live_keys = {canonical_window_id(w.window_id) for w in windows}
    new_key = canonical_window_id(event.window_id)
    dead = [
        (user_id, chat_id, thread_id, window_id)
        for user_id, chat_id, thread_id, window_id in iter_bound_topics()
        if canonical_window_id(window_id) not in live_keys
        and canonical_window_id(window_id) != new_key
    ]
    if not dead:
        return None
    raw = await read_session_map_raw()
    if raw is None:
        # Unreadable map is "unknown", not "empty": neither the family
        # facts nor the new entry can be trusted without it.
        return None
    new_entry = raw_session_map_entry(raw, event.window_id)
    # For the new window the hook-written entry outranks the window state
    # adoption just wrote; the dead binding's facts prefer state first,
    # because its entry is the one pruning removes.
    new_provider = (
        _entry_str(new_entry, "provider_name")
        or identity_state.get_provider_name(event.window_id)
        or ""
    )
    bindings = [
        _family_binding(user_id, chat_id, thread_id, window_id, raw=raw)
        for user_id, chat_id, thread_id, window_id in dead
    ]
    match = find_family_match(new_ref.cwd or event.cwd, new_provider, bindings)
    if match is None:
        return None
    # The family already served by a live topic? A live same-cwd window
    # means another topic owns that workspace right now: rebinding the
    # dead one would leave two same-family topics, the duplicate shape
    # this heal exists to prevent. Fall through to a new topic.
    # Lazy: thread_router is wired into session_manager which imports
    # session_monitor; hoisting forms a startup cycle.
    from ...thread_router import thread_router

    if any(
        thread_router.has_window(canonical_window_id(w.window_id))
        for w in windows
        if w.cwd == (new_ref.cwd or event.cwd)
        and canonical_window_id(w.window_id) != new_key
    ):
        return None
    return new_entry, new_provider, match


# Two same-family windows reopening in one batch would otherwise both
# match the one dead binding, and the second bind would steal the topic
# the first just rebound. The per-window adoption locks cannot see this;
# the decision plus bind below must be atomic against its siblings.
_family_rebind_lock = asyncio.Lock()


async def maybe_rebind_family_topic(
    event: NewWindowEvent,
    client: TelegramClient,
    *,
    live_windows: Sequence[WindowRef] | None,
) -> bool:
    """Adopt a dead same-family binding instead of creating a topic.

    Returns True when the event's window took over an existing topic, so
    adoption is complete and no topic may be created. ``live_windows`` is
    the confirmed listing the caller already judged eligibility with; a
    missing or unconfirmed listing answers False so adoption falls through
    to today's behavior instead of judging liveness on a second, later
    fetch that can disagree with the caller's verdict.
    """
    if thread_router.has_window(event.window_id):
        return False
    windows = live_windows
    if windows is None:
        return False
    # Lazy: topic_orchestration imports this module, so every helper this
    # module borrows from it must stay function-local (the same cycle
    # sync_command resolves).
    from .topic_orchestration import _bind_topic_to_user, _default_topic_name

    async with _family_rebind_lock:
        decision = await _family_decision(event, windows)
        if decision is None:
            return False
        new_entry, new_provider, match = decision

        session_id = _entry_str(new_entry, "session_id")
        transcript_path = _entry_str(new_entry, "transcript_path")
        monitor = get_active_monitor()
        skipped_bytes = (
            await _seed_monitor_at_eof(
                monitor, session_id, transcript_path, event.window_id, new_provider
            )
            if monitor is not None and session_id and transcript_path
            else None
        )
        _bind_topic_to_user(
            match.user_id,
            match.thread_id,
            event.window_id,
            match.chat_id,
            thread_router.get_display_name(match.old_window_id)
            or _default_topic_name(event),
        )
        session_manager.flush_state()
        logger.info(
            "Rebound dead-family topic to reopened window",
            old_window_id=match.old_window_id,
            new_window_id=event.window_id,
            user_id=match.user_id,
            thread_id=match.thread_id,
            skipped_bytes=skipped_bytes,
        )

    # resolve_chat_id always answers (stored chat, configured group, then
    # user id), so the notice follows the same delivery resolution as
    # every other notice path.
    chat_id = match.chat_id
    if chat_id is None:
        chat_id = resolve_chat_id(match.user_id, match.thread_id)
    if skipped_bytes is not None:
        text = REBOUND_TEXT.format(
            old=match.old_window_id, new=event.window_id, skipped=skipped_bytes
        )
    else:
        text = REBOUND_PENDING_SESSION_TEXT.format(
            old=match.old_window_id, new=event.window_id
        )
    try:
        await safe_send(client, chat_id, text, message_thread_id=match.thread_id)
    except Exception:  # noqa: BLE001
        # The rebind already landed; a failed notice must not unwind it.
        logger.exception(
            "Family rebind notice send failed",
            old_window_id=match.old_window_id,
            new_window_id=event.window_id,
        )
    return True
