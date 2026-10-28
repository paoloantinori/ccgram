"""Silent delivery-wedge early warning.

The 2026-09-26 incident (TASK-43) froze delivery for seven hours with
zero log lines; the operator noticed only because replies stopped
arriving. This watch turns that failure mode into a five-minute alarm:
it compares each bound window's durable delivery watermark (the
monitor's settled-receipt boundary) against its transcript size, and
when a large gap stops advancing it warns in the journal and posts ONE
notice in the topic. The notice is sent through the direct interactive
path, never the delivery queue: a wedged queue must not swallow its
own alarm.

A wedge that outlives the escalation threshold (2026-10-28 incident:
three days at journal-noise level) stops being quiet by design: every
gate pass journals a WARNING and ONE direct maintainer notice names the
session, the gap, and the restart-replay consequence.

The watermark is the correct signal, not the user read offset: the
read offset stamps at enqueue time and on /history paging, so it keeps
moving while delivery is dead (message_routing.py routes and stamps
even when the worker is frozen). The watermark freezes precisely
because receipts stop settling.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import structlog

from ...config import config
from ...session_query import iter_bound_topics
from ...session_state_ports import get_delivery_watermark, get_session_id
from ...telegram_client import TelegramClient
from ..messaging_pipeline.message_sender import safe_send

logger = structlog.get_logger()

# Transcript bytes that must be undelivered before the gap counts as a
# wedge candidate; below this a stalled watermark is normal quiet time.
# Generous on purpose: a long streaming thinking block grows the
# transcript without any complete message settling a receipt, and that
# benign burst must not page the operator. Sourced from
# CCGRAM_DELIVERY_WATCH_GAP_KB, where 0 disables the watch.
GAP_THRESHOLD_BYTES = config.delivery_watch_gap_bytes
# How long a qualifying gap must stay frozen before the alarm fires.
# The check rides the 60s periodic gate, so this is five to six
# observations, not a timer.
STUCK_GRACE_S = 300.0
# How long the same wedge must persist before escalation: a WARNING
# journal line on every gate pass plus ONE direct maintainer notice.
# The 2026-10-28 incident kept a wedge at journal-noise level for three
# days; past this threshold silence is never the steady state. Sourced
# from CCGRAM_DELIVERY_WATCH_ESCALATE_MIN (minutes), where 0 disables
# escalation (the first topic alert still fires after STUCK_GRACE_S).
# Deliberately not clamped to the grace: an operator may want the
# maintainer notice BEFORE the five-minute topic alert, and escalation
# firing first is harmless (the alert follows on its own clock).
ESCALATE_AFTER_S = config.delivery_watch_escalate_s

ALERT_TEXT = (
    "⚠️ Delivery stall detected: {gap_kb:.0f} KB of output has not"
    " been delivered for over {stuck:.0f}s. If replies look missing, restart"
    " the bridge to clear the stall."
)

ESCALATION_TEXT = (
    "🚨 Delivery wedge on session {session_id} has persisted for"
    " {minutes:.0f} minutes with {gap_kb:.0f} KB undelivered. Fix the wedge"
    " before restarting: an untreated restart either replays this backlog or"
    " skips it past the per-session replay cap (CCGRAM_REPLAY_CAP_MB), so"
    " live-view history can be lost either way. Check the journal for"
    " 'Delivery wedge persists' lines."
)


class WatchVerdict(NamedTuple):
    """One observation's outcome for the wiring to act on."""

    alert: bool
    escalate: bool
    persistent: bool
    stuck_s: float


@dataclass
class _WindowWatch:
    last_offset: int | None = None
    stuck_since: float | None = None
    alerted: bool = False
    transcript_path: str = ""
    size_at_stuck: int = 0
    escalated: bool = False


@dataclass
class DeliveryGapWatch:
    """Pure decision core: turns watermark/size observations into alarms.

    observe() is called once per periodic check per bound window. An
    alert fires at most once per incident, and an escalation fires at
    most once per incident once the wedge has outlived
    ``escalate_after_s``; the incident ends when the watermark advances
    or the gap shrinks below the threshold, either of which re-arms the
    window.
    """

    gap_threshold: int = GAP_THRESHOLD_BYTES
    stuck_grace_s: float = STUCK_GRACE_S
    escalate_after_s: float = ESCALATE_AFTER_S
    _windows: dict[str, _WindowWatch] = field(default_factory=dict)

    def observe(
        self,
        window_id: str,
        offset: int,
        size: int,
        now: float,
        *,
        transcript_path: str = "",
    ) -> WatchVerdict:
        """Record one observation; ``.alert`` says the alarm fires now."""
        state = self._windows.setdefault(
            window_id,
            _WindowWatch(last_offset=offset, transcript_path=transcript_path),
        )
        if transcript_path and state.transcript_path != transcript_path:
            # Same window, new session transcript: the old incident's
            # timers and latch describe a different file.
            state = _WindowWatch(last_offset=offset, transcript_path=transcript_path)
            self._windows[window_id] = state

        gap = max(size - offset, 0)
        if gap < self.gap_threshold or offset != state.last_offset:
            # Healthy movement, or nothing worth alarming about: the
            # previous incident (if any) is over.
            state.last_offset = offset
            state.stuck_since = None
            state.size_at_stuck = size
            state.alerted = False
            state.escalated = False
            return WatchVerdict(False, False, False, 0.0)

        if state.stuck_since is None:
            state.stuck_since = now
            state.size_at_stuck = size
            return WatchVerdict(False, False, False, 0.0)
        # The incident signature is a FROZEN watermark under a GROWING
        # transcript; a static transcript is quiet time, not a stall.
        # Quiet time also restarts the grace clock, so a brief burst
        # after a long quiet stretch cannot fire a premature notice.
        if size <= state.size_at_stuck:
            state.stuck_since = now
            state.size_at_stuck = size
            return WatchVerdict(False, False, False, 0.0)
        stuck = now - state.stuck_since
        alert = False
        if stuck >= self.stuck_grace_s and not state.alerted:
            state.alerted = True
            alert = True
        persistent = self.escalate_after_s > 0 and stuck >= self.escalate_after_s
        escalate = False
        if persistent and not state.escalated:
            state.escalated = True
            escalate = True
        return WatchVerdict(alert, escalate, persistent, stuck)

    def forget(self, bound: set[str]) -> None:
        """Drop state for windows that are no longer bound."""
        for window_id in list(self._windows):
            if window_id not in bound:
                del self._windows[window_id]

    def disarm(self, window_id: str) -> None:
        """Re-arm a window whose one-shot alert could not go out."""
        state = self._windows.get(window_id)
        if state is not None:
            state.alerted = False

    def disarm_escalation(self, window_id: str) -> None:
        """Re-arm a window whose one-shot escalation could not go out."""
        state = self._windows.get(window_id)
        if state is not None:
            state.escalated = False

    def pause(self, window_id: str) -> None:
        """Stop the stall clock without ending any incident."""
        state = self._windows.get(window_id)
        if state is not None:
            state.stuck_since = None


_watch = DeliveryGapWatch()
# Alert sends are fire-and-forget so a flood-retried Telegram call can
# never stall the poll cycle; the set only holds strong references.
_alert_tasks: set[asyncio.Task[None]] = set()


def reset_for_testing() -> None:
    """Drop all watch state and pending alerts (test isolation)."""
    global _watch
    _watch = DeliveryGapWatch()
    _alert_tasks.clear()


async def check_delivery_wedges(client: TelegramClient) -> None:
    """One periodic pass: measure every bound window, alarm on stalls."""
    if _watch.gap_threshold <= 0:
        return
    now = time.monotonic()
    topics = iter_bound_topics()
    _watch.forget({window_id for _, _, _, window_id in topics})
    for user_id, chat_id, thread_id, window_id in topics:
        delivery = get_delivery_watermark(window_id)
        if delivery is None or delivery.watermark < 0:
            # Not yet tracked: the monitor has not parsed anything to
            # settle a receipt for.
            continue
        if delivery.fenced:
            # Backlog-skip barrier or pending-tools fence: the monitor
            # freezes commits on purpose; that is not a wedge, and fence
            # time must not count toward the stall grace.
            _watch.pause(window_id)
            continue
        try:
            size = Path(delivery.transcript_path).stat().st_size
        except OSError:
            continue
        verdict = _watch.observe(
            window_id,
            delivery.watermark,
            size,
            now,
            transcript_path=delivery.transcript_path,
        )
        gap = max(size - delivery.watermark, 0)
        if verdict.persistent:
            logger.warning(
                "Delivery wedge persists: transcript growing, watermark frozen",
                user_id=user_id,
                window_id=window_id,
                session_id=get_session_id(window_id),
                gap_bytes=gap,
                stuck_s=round(verdict.stuck_s, 1),
            )
        if verdict.escalate:
            _spawn_notice(
                client,
                chat_id,
                thread_id,
                ESCALATION_TEXT.format(
                    session_id=get_session_id(window_id) or "unknown",
                    minutes=verdict.stuck_s / 60,
                    gap_kb=gap / 1024,
                ),
                window_id,
                rearm=_watch.disarm_escalation,
            )
        if not verdict.alert:
            continue
        logger.warning(
            "Delivery wedge suspected: transcript growing, watermark frozen",
            user_id=user_id,
            window_id=window_id,
            gap_bytes=gap,
            stuck_grace_s=_watch.stuck_grace_s,
        )
        _spawn_notice(
            client,
            chat_id,
            thread_id,
            ALERT_TEXT.format(gap_kb=gap / 1024, stuck=_watch.stuck_grace_s),
            window_id,
            rearm=_watch.disarm,
        )


def _spawn_notice(
    client: TelegramClient,
    chat_id: int | None,
    thread_id: int | None,
    text: str,
    window_id: str,
    *,
    rearm: Callable[[str], None],
) -> None:
    """Fire-and-forget one direct wedge notice, one-shot per latch.

    An unresolved chat mapping must not consume the one-shot: re-arm and
    retry once the router knows the topic's chat. The send is decoupled
    from the poll loop, so a flood-retried Telegram call can never stall
    a cycle; the set only holds strong references.
    """
    if chat_id is None:
        rearm(window_id)
        return
    task = asyncio.create_task(
        _send_notice(client, chat_id, thread_id, text, window_id, rearm=rearm)
    )
    _alert_tasks.add(task)
    task.add_done_callback(_alert_tasks.discard)


async def _send_notice(
    client: TelegramClient,
    chat_id: int,
    thread_id: int | None,
    text: str,
    window_id: str,
    *,
    rearm: Callable[[str], None],
) -> None:
    try:
        # Direct send, never the delivery queue: the queue is the thing
        # under suspicion and must not carry its own alarm. safe_send
        # returns None on non-rate-limit Telegram failures (only
        # RetryAfter raises), so a None answer is also a failed notice.
        # A notice that times out after delivery is retried and can be
        # posted twice: the duplicate is the accepted side of the
        # retry-on-any-unconfirmed-send trade-off.
        sent = await safe_send(client, chat_id, text, message_thread_id=thread_id)
        if sent is None:
            raise RuntimeError("direct notice send returned None")
    except Exception:
        # RetryAfter propagates from safe_send once the limiter's budget
        # is spent, and a wedged system often has Telegram degraded too;
        # the notice must retry on a later pass instead of dying as an
        # unretrieved task exception.
        logger.exception(
            "Delivery-wedge notice send failed; will retry next pass",
            window_id=window_id,
        )
        rearm(window_id)
