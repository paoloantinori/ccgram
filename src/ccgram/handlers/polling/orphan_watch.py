"""Self-healing for session-orphaned topic bindings.

The 2026-10-28 incident (hermes-fleet on the Mac) left topics mute for two
days: the multiplexer window id is stable across session churn, but the
session_map entry for it died (a cleanup sweep removed it when the session
id went away, or the hook never fired for the container agent). A live
bound topic then pointed at a window with no session_map entry, so the
monitor read nothing and nothing alerted.

This watch rides the 60s topic-check gate and closes that gap. For every
bound window it compares the raw session_map file against the live window
listing; when the entry is missing (or invalid) while the window is still
live, the binding is session-orphaned. Candidates come from the window's
cwd-derived project directory under the Claude projects root (hookless
providers own their re-registration path in transcript discovery), plus a
remembered-session fallback searched by uuid across the whole projects
root. When exactly one fresh, unclaimed candidate exists the watch relinks
the entry to it, seeds the monitor offset at EOF (never replay), and posts
ONE notice in the topic through the direct interactive path, never the
delivery queue. Ambiguous or transcript-less orphans get the notice
without the relink. Idempotent by construction: a tick that finds the
entry present and matching does nothing.
"""

import asyncio
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import structlog

from ...config import config
from ...hooks.state_files import StateFileValidationError, parse_session_map_entry
from ...multiplexer.base import WindowRef, canonical_window_id
from ...providers import detect_provider_from_transcript_path
from ...session_map import (
    read_session_map_raw,
    raw_session_map_entry,
    session_map_prefix,
    session_map_sync,
    strip_session_map_prefix,
)
from ...session_monitor import get_active_monitor
from ...session_query import iter_bound_topics
from ...telegram_client import TelegramClient
from ...window_state_ports import identity_state
from ..messaging_pipeline.message_sender import safe_send

logger = structlog.get_logger()

# A transcript counts as a live relink candidate only while it is being
# written (or was written this recently). Historical sessions pile up in
# the same project directory and must never compete with the current one;
# a live-but-idle agent writes nothing, so an orphan that stays quiet stays
# notice-only until its agent produces output again.
ORPHAN_CANDIDATE_FRESH_S = 900.0

RELINKED_TEXT = (
    "🔁 Session relink: topic {topic} lost its session-map entry"
    " (old session {old}). Rebound to the live session {new};"
    " new replies arrive from now on, earlier output is not replayed."
)
SKIPPED_TEXT = (
    "⚠️ Session orphan: topic {topic} lost its session-map entry"
    " (old session {old}). Relink skipped ({reason});"
    " the topic stays mute until its session map is healed."
)


@dataclass(frozen=True)
class Candidate:
    """One live transcript that may be the window's current session."""

    session_id: str
    transcript_path: str
    mtime: float
    size: int


class OrphanAction(Enum):
    """What the watch wants the driver to do for one window this tick."""

    NONE = "none"
    RELINK = "relink"
    NOTICE = "notice"


@dataclass(frozen=True)
class OrphanVerdict:
    """The decision for one window, derived only from its observations."""

    action: OrphanAction
    old_session_id: str = ""
    candidate: Candidate | None = None
    reason: str = ""
    first_detection: bool = False


@dataclass
class _Incident:
    """One open orphan incident: whether its single notice has gone out."""

    notified: bool = False


@dataclass
class OrphanBindingWatch:
    """Pure decision core: turns per-window observations into verdicts.

    ``observe`` is called once per gate tick per bound window with the raw
    file entry's session id (None when missing or invalid) and the claim-
    filtered candidate transcripts. Candidates must already exclude every
    session claimed by another live window's entry or another bound
    window's state; the core only drops the window's own entry session
    when looking for a replacement.

    An incident opens on the first orphaning verdict and closes when the
    binding heals (entry present, no contradicting candidate), when a
    relink succeeds (``resolve``), or when the window stops being bound or
    live (``forget`` / a not-live observation). The notice latch is set
    when the send is spawned and re-armed when the send fails, mirroring
    the delivery watch, so one notice goes out per incident.
    """

    candidate_fresh_s: float = ORPHAN_CANDIDATE_FRESH_S
    _incidents: dict[str, _Incident] = field(default_factory=dict)

    def observe(
        self,
        window_id: str,
        *,
        live: bool,
        entry_session_id: str | None,
        candidates: Sequence[Candidate],
    ) -> OrphanVerdict:
        """Record one observation; the verdict says what to do about it."""
        if not live:
            self._incidents.pop(window_id, None)
            return OrphanVerdict(action=OrphanAction.NONE)
        first = window_id not in self._incidents
        if entry_session_id is None:
            return self._orphan_verdict(
                window_id,
                old_session_id="",
                survivors=list(candidates),
                first=first,
            )
        if any(c.session_id == entry_session_id for c in candidates):
            # The entry's own session is alive: the binding is healthy.
            self._incidents.pop(window_id, None)
            return OrphanVerdict(action=OrphanAction.NONE)
        survivors = [c for c in candidates if c.session_id != entry_session_id]
        if not survivors:
            # Entry present, nothing fresher contradicting it: idle agent
            # or honest quiet time. Not provably orphaned, so stay quiet.
            self._incidents.pop(window_id, None)
            return OrphanVerdict(action=OrphanAction.NONE)
        return self._orphan_verdict(
            window_id,
            old_session_id=entry_session_id,
            survivors=survivors,
            first=first,
        )

    def _orphan_verdict(
        self,
        window_id: str,
        *,
        old_session_id: str,
        survivors: list[Candidate],
        first: bool,
    ) -> OrphanVerdict:
        if first:
            self._incidents[window_id] = _Incident()
        if len(survivors) == 1:
            return OrphanVerdict(
                action=OrphanAction.RELINK,
                old_session_id=old_session_id,
                candidate=survivors[0],
                first_detection=first,
            )
        if not survivors:
            reason = "no live transcript found"
        else:
            reason = f"{len(survivors)} live transcripts, cannot attribute one"
        return OrphanVerdict(
            action=OrphanAction.NOTICE,
            old_session_id=old_session_id,
            reason=reason,
            first_detection=first,
        )

    def forget(self, bound: set[str]) -> None:
        """Drop incidents for windows that are no longer bound."""
        for window_id in list(self._incidents):
            if window_id not in bound:
                del self._incidents[window_id]

    def resolve(self, window_id: str) -> None:
        """Close the incident after a successful relink."""
        self._incidents.pop(window_id, None)

    def pending_notice(self, window_id: str) -> bool:
        """Whether this incident still owes the topic its one notice."""
        incident = self._incidents.get(window_id)
        return incident is not None and not incident.notified

    def mark_notified(self, window_id: str) -> None:
        """Latch the notice; missing incident means it already closed."""
        incident = self._incidents.get(window_id)
        if incident is not None:
            incident.notified = True

    def rearm(self, window_id: str) -> None:
        """Re-arm a notice whose send could not be confirmed."""
        incident = self._incidents.get(window_id)
        if incident is not None:
            incident.notified = False


_watch = OrphanBindingWatch()
# Notice sends are fire-and-forget so a flood-retried Telegram call can
# never stall the poll cycle; the set only holds strong references.
_notice_tasks: set[asyncio.Task[None]] = set()


def reset_for_testing() -> None:
    """Drop all watch state and pending notices (test isolation)."""
    global _watch
    _watch = OrphanBindingWatch()
    _notice_tasks.clear()


def _validated_session_id(entry: Mapping[str, object] | None) -> str | None:
    """The entry's session id, or None when absent or failing validation.

    An entry the monitor would refuse (missing session_id, future schema
    version) heals nothing, so the watch treats it exactly like a missing
    entry; that mirrors ``session_map_entry_may_exist``.
    """
    if not isinstance(entry, Mapping):
        return None
    try:
        parse_session_map_entry(dict(entry))
    except StateFileValidationError:
        return None
    session_id = entry.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def _live_entry_claims(
    raw: Mapping[str, object],
    live_ids: set[str],
) -> set[str]:
    """Session ids claimed by live windows' entries.

    Entries of windows that are gone may linger (herdr never prunes them),
    and a dead window's leftover entry must not veto a relink onto the
    session that actually runs now, so only live windows' entries count.
    """
    prefix = session_map_prefix()
    claims: set[str] = set()
    for key, info in raw.items():
        if not isinstance(key, str) or not isinstance(info, Mapping):
            continue
        window_id = strip_session_map_prefix(key, prefix)
        if window_id is None or canonical_window_id(window_id) not in live_ids:
            continue
        session_id = info.get("session_id")
        if isinstance(session_id, str) and session_id:
            claims.add(session_id)
    return claims


def _fresh_candidate(path: Path, *, now: float, fresh_s: float) -> Candidate | None:
    """Build a Candidate for a non-empty transcript written within fresh_s."""
    try:
        st = path.stat()
    except OSError:
        return None
    if st.st_size <= 0 or now - st.st_mtime > fresh_s:
        return None
    return Candidate(
        session_id=path.stem,
        transcript_path=str(path),
        mtime=st.st_mtime,
        size=st.st_size,
    )


def _scan_candidates(
    projects_path: Path,
    cwd: str,
    now: float,
    fresh_s: float,
) -> list[Candidate]:
    """Fresh transcripts in the window's project directory, unfiltered.

    The directory is derived with the same encoding the session resolver
    reads with (cwd with "/" replaced by "-" under the projects root).
    Claim filtering is per window: the scan is memoized per pass and one
    window's exclusions must not poison another's view.
    """
    if not cwd:
        return []
    try:
        files = list((projects_path / cwd.replace("/", "-")).glob("*.jsonl"))
    except OSError:
        return []
    candidates = [
        candidate
        for file_path in files
        if (candidate := _fresh_candidate(file_path, now=now, fresh_s=fresh_s))
        is not None
    ]
    candidates.sort(key=lambda c: (-c.mtime, c.session_id))
    return candidates


def _candidate_for_session_id(
    projects_path: Path, session_id: str, now: float, fresh_s: float
) -> Candidate | None:
    """Locate one known session id anywhere under the projects root."""
    if not session_id:
        return None
    try:
        matches = list(projects_path.glob(f"*/{session_id}.jsonl"))
    except OSError:
        return None
    for file_path in matches:
        candidate = _fresh_candidate(file_path, now=now, fresh_s=fresh_s)
        if candidate is not None:
            return candidate
    return None


def _backup_and_write_entry(**entry_kwargs: str) -> bool:
    """Back up session_map.json, then write the entry; False aborts the relink.

    Runs in a worker thread next to the locked writer it precedes so the
    copy never blocks the poll loop.
    """
    map_file = config.session_map_file
    backup = map_file.with_name(f"{map_file.name}.orphan-relink.bak")
    try:
        shutil.copy2(map_file, backup)
    except FileNotFoundError:
        pass  # nothing on disk yet to back up
    except OSError:
        logger.warning(
            "Orphan relink deferred: session_map backup failed",
            window_id=entry_kwargs["window_id"],
            backup_path=str(backup),
        )
        return False
    session_map_sync.write_hookless_session_map(**entry_kwargs)
    return True


def _candidate_provider_name(window_id: str, candidate: Candidate) -> str:
    """Provider for a relink: transcript evidence first, stored state second."""
    return detect_provider_from_transcript_path(candidate.transcript_path) or (
        identity_state.get_provider_name(window_id) or ""
    )


async def _relink_binding(window_id: str, candidate: Candidate, cwd: str) -> bool:
    """Write the relinked entry and seed the offset; True when it landed.

    The write goes through the same locked writer the hookless providers
    use (serialize_session_map_entry owns the field template), preceded by
    a rolling backup of session_map.json like the manual cure took, and
    followed by a read-back: a write that did not land leaves the incident
    open so the next tick retries.
    """
    provider_name = _candidate_provider_name(window_id, candidate)
    entry_kwargs = dict(
        window_id=window_id,
        session_id=candidate.session_id,
        cwd=cwd,
        transcript_path=candidate.transcript_path,
        provider_name=provider_name,
    )
    session_map_sync.register_hookless_session(**entry_kwargs)
    written_ok = await asyncio.to_thread(_backup_and_write_entry, **entry_kwargs)
    if not written_ok:
        return False
    written = await read_session_map_raw()
    entry = raw_session_map_entry(written, window_id) if written is not None else None
    if _validated_session_id(entry) != candidate.session_id:
        logger.warning(
            "Orphan relink unreadable after write; will retry",
            window_id=window_id,
            session_id=candidate.session_id,
        )
        return False
    monitor = get_active_monitor()
    if monitor is not None:
        # Seeding through the monitor's own start path initializes the
        # reader's companion caches; with no monitor running, its first
        # sight of the session seeds EOF by itself.
        await monitor.seed_session_offset_at_eof(
            candidate.session_id, candidate.transcript_path, window_id, provider_name
        )
    logger.warning(
        "Relinked session-orphaned binding",
        window_id=window_id,
        session_id=candidate.session_id,
        transcript_path=candidate.transcript_path,
    )
    return True


def _notice_text(
    verdict: OrphanVerdict,
    relinked: bool,
    auto_relink: bool,
    topic: str,
    *,
    skip_reason: str = "",
) -> str:
    if relinked and verdict.candidate is not None:
        return RELINKED_TEXT.format(
            topic=topic,
            old=verdict.old_session_id or "none",
            new=verdict.candidate.session_id,
        )
    if skip_reason:
        reason = skip_reason
    elif verdict.action is OrphanAction.RELINK:
        reason = (
            "auto-relink disabled"
            if not auto_relink
            else "relink write failed, retrying"
        )
    else:
        reason = verdict.reason
    return SKIPPED_TEXT.format(
        topic=topic, old=verdict.old_session_id or "none", reason=reason
    )


def _topic_label(window_id: str, thread_id: int) -> str:
    # Lazy: the router is installed by SessionManager during bootstrap.
    from ...thread_router import thread_router

    name = thread_router.get_display_name(window_id)
    return f"{name} (topic {thread_id})" if name else f"topic {thread_id}"


async def _send_notice(
    client: TelegramClient,
    chat_id: int,
    thread_id: int,
    text: str,
    window_id: str,
) -> None:
    try:
        # Direct send, never the delivery queue: an orphaned binding has
        # no monitored session, so the queue has nothing to carry this on
        # even when it is healthy. safe_send returns None on non-retryable
        # Telegram failures, which also counts as a failed notice.
        sent = await safe_send(
            client,
            chat_id,
            text,
            message_thread_id=thread_id,
        )
        if sent is None:
            raise RuntimeError("notice send returned None")
    except Exception:
        logger.exception(
            "Orphan-watch notice send failed; will retry next pass",
            window_id=window_id,
        )
        _watch.rearm(window_id)


@dataclass
class _PassContext:
    """Pass-scoped facts computed once and shared by every window check.

    ``scans`` memoizes the unfiltered per-cwd candidate scan so windows
    sharing a directory pay for one listing, and one window's claim
    exclusions cannot poison another's view. ``relinked_sessions`` grows
    during the pass so a session claimed by an earlier relink in the same
    pass is not handed to a second window. ``topics_by_window`` carries
    every bound topic of a window so one incident notice reaches them all.
    """

    raw: Mapping[str, object]
    live_by_id: dict[str, WindowRef]
    entry_claims: frozenset[str]
    memory_claims: dict[str, str]
    topics_by_window: dict[str, list[tuple[int | None, int]]]
    now: float
    fresh_s: float
    scans: dict[str, list[Candidate]] = field(default_factory=dict)
    relinked_sessions: set[str] = field(default_factory=set)


def _pass_context(
    raw: Mapping[str, object],
    windows: Sequence[WindowRef],
    topics: list[tuple[int, int | None, int, str]],
) -> _PassContext:
    """Assemble the pass-scoped facts from one raw map and listing."""
    live_by_id: dict[str, WindowRef] = {}
    for window in windows:
        live_by_id.setdefault(canonical_window_id(window.window_id), window)
    memory_claims: dict[str, str] = {}
    topics_by_window: dict[str, list[tuple[int | None, int]]] = {}
    for _, chat_id, thread_id, window_id in topics:
        if not window_id:
            continue
        memory_sid = identity_state.get_session_id(window_id)
        if memory_sid:
            memory_claims.setdefault(canonical_window_id(window_id), memory_sid)
        topics_by_window.setdefault(canonical_window_id(window_id), []).append(
            (chat_id, thread_id)
        )
    return _PassContext(
        raw=raw,
        live_by_id=live_by_id,
        entry_claims=frozenset(_live_entry_claims(raw, set(live_by_id))),
        memory_claims=memory_claims,
        topics_by_window=topics_by_window,
        now=time.time(),
        fresh_s=_watch.candidate_fresh_s,
    )


async def check_orphan_bindings(
    client: TelegramClient, windows: Sequence[WindowRef] | None
) -> None:
    """One periodic pass: detect orphaned bindings, relink, notice.

    ``windows`` is the confirmed reconciliation listing the poll loop
    already fetched for this tick; None means it was unconfirmed, and
    absence of a window cannot be proven without it.
    """
    if not config.orphan_watch_enabled:
        return
    topics = iter_bound_topics()
    _watch.forget({window_id for _, _, _, window_id in topics})
    if not topics:
        return
    if windows is None:
        return
    raw = await read_session_map_raw()
    if raw is None:
        # Unreadable map is "unknown", not "empty": guessing orphaned here
        # would relink live sessions on a transient read failure.
        return
    ctx = _pass_context(raw, windows, topics)
    seen: set[str] = set()
    for _, _, _, window_id in topics:
        key = canonical_window_id(window_id)
        if not window_id or key in seen:
            continue
        seen.add(key)
        try:
            await _check_window(client, ctx=ctx, window_id=window_id)
        except Exception:
            logger.exception("Orphan-watch check failed", window_id=window_id)


def _claim_exclusions(
    ctx: _PassContext, window_id: str, entry_sid: str | None
) -> set[str]:
    """Sessions claimed by others: live windows' entries and bound windows' state."""
    own = canonical_window_id(window_id)
    exclude = {
        session_id for key, session_id in ctx.memory_claims.items() if key != own
    }
    exclude |= set(ctx.entry_claims)
    exclude |= ctx.relinked_sessions
    if entry_sid:
        exclude.discard(entry_sid)
    return exclude


async def _gather_candidates(
    ctx: _PassContext, window_id: str, entry_sid: str | None, cwd: str
) -> list[Candidate]:
    """Fresh, unclaimed transcripts that may be this window's session.

    Scans the cwd-derived project directory first; when the window state
    remembers a session id the file entry never got, looks for that one
    anywhere under the projects root before giving up.
    """
    exclude = _claim_exclusions(ctx, window_id, entry_sid)
    scanned = ctx.scans.get(cwd)
    if scanned is None:
        scanned = (
            await asyncio.to_thread(
                _scan_candidates,
                config.claude_projects_path,
                cwd,
                ctx.now,
                ctx.fresh_s,
            )
            if cwd
            else []
        )
        ctx.scans[cwd] = scanned
    candidates = [c for c in scanned if c.session_id not in exclude]
    memory_sid = identity_state.get_session_id(window_id)
    if (
        memory_sid
        and memory_sid != entry_sid
        and memory_sid not in exclude
        and all(c.session_id != memory_sid for c in candidates)
    ):
        fallback = await asyncio.to_thread(
            _candidate_for_session_id,
            config.claude_projects_path,
            memory_sid,
            ctx.now,
            ctx.fresh_s,
        )
        if fallback is not None:
            candidates = [*candidates, fallback]
    return candidates


async def _check_window(
    client: TelegramClient,
    *,
    ctx: _PassContext,
    window_id: str,
) -> None:
    """Detect and heal one bound window's binding against raw file truth."""
    # Lazy: topic_orchestration imports the session stack; keep it out of
    # module load so the polling package stays import-light.
    from ..topics.topic_orchestration import is_pending_creation

    if is_pending_creation(window_id):
        # A creation flow owns this window; its hook entry is simply not
        # written yet (container agents: never). Racing it here would
        # relink onto a stale transcript of a brand-new window.
        return
    ref = ctx.live_by_id.get(canonical_window_id(window_id))
    if ref is None:
        # Not live: window death is the recovery banner's domain.
        _watch.observe(window_id, live=False, entry_session_id=None, candidates=())
        return
    entry_sid = _validated_session_id(raw_session_map_entry(ctx.raw, window_id))
    cwd = ref.cwd or identity_state.get_cwd(window_id)
    candidates = await _gather_candidates(ctx, window_id, entry_sid, cwd)
    verdict = _watch.observe(
        window_id,
        live=True,
        entry_session_id=entry_sid,
        candidates=candidates,
    )
    if verdict.action is OrphanAction.NONE:
        return
    if verdict.first_detection:
        logger.warning(
            "Session-orphaned binding detected",
            window_id=window_id,
            kind="missing" if entry_sid is None else "stale",
            old_session=verdict.old_session_id,
            live_candidates=len(candidates),
        )
    # Snapshot before the relink: a successful relink resolves the
    # incident the notice latch lives on.
    should_notify = _watch.pending_notice(window_id)
    auto_relink = config.orphan_auto_relink
    skip_reason = ""
    relinked = False
    if (
        verdict.action is OrphanAction.RELINK
        and verdict.candidate is not None
        and auto_relink
    ):
        provider_name = _candidate_provider_name(window_id, verdict.candidate)
        if not identity_state.accepts_provider_observation(window_id, provider_name):
            # A manual /agent pin would refuse the entry on the monitor
            # side too: writing it would look healed while staying mute.
            skip_reason = "the window's pinned provider does not match the candidate"
            logger.warning(
                "Orphan relink skipped: provider pin mismatch",
                window_id=window_id,
                candidate_provider=provider_name,
            )
        else:
            relinked = await _relink_binding(window_id, verdict.candidate, cwd)
            if relinked:
                _watch.resolve(window_id)
                # Later windows in this same pass must not take this
                # session too: the pass-scoped claims are a snapshot.
                ctx.relinked_sessions.add(verdict.candidate.session_id)
    pairs = [
        (chat_id, thread_id)
        for chat_id, thread_id in ctx.topics_by_window.get(
            canonical_window_id(window_id), []
        )
        if chat_id is not None
    ]
    if not should_notify or not pairs:
        # No resolvable chat mapping: the notice-only incident stays owed
        # and retries once the router knows the topic's chat. A relink
        # that already succeeded has no incident left to remember the
        # debt; its journal warning is the record of that corner.
        return
    # Latch at spawn time and re-arm on failure, so an in-flight send
    # overlapping the next gate tick cannot double-notice. One latch per
    # incident, one send per topic bound to the window.
    _watch.mark_notified(window_id)
    for chat_id, thread_id in pairs:
        text = _notice_text(
            verdict,
            relinked,
            auto_relink,
            _topic_label(window_id, thread_id),
            skip_reason=skip_reason,
        )
        task = asyncio.create_task(
            _send_notice(client, chat_id, thread_id, text, window_id)
        )
        _notice_tasks.add(task)
        task.add_done_callback(_notice_tasks.discard)
