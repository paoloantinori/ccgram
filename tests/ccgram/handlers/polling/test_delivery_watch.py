"""Silent delivery-wedge early warning: pure decision core and wiring."""

import asyncio

from ccgram.handlers.polling import delivery_watch
from ccgram.handlers.polling.delivery_watch import (
    DeliveryGapWatch,
    check_delivery_wedges,
)
from ccgram.session_state_ports import DeliveryWatermark
from ccgram.telegram_client import FakeTelegramClient


async def _flush_alert_tasks() -> None:
    """Let fire-and-forget alert sends run to completion."""
    while delivery_watch._alert_tasks:
        await asyncio.wait_for(
            asyncio.gather(*delivery_watch._alert_tasks, return_exceptions=True),
            timeout=5,
        )


def _wire(monkeypatch, tmp_path, topics, deliveries, *, escalate_after_s=3600.0):
    """Point the watch at synthetic bindings and delivery projections.

    Returns (client, transcript); tests GROW the transcript between
    passes (the incident signature is a frozen watermark under a
    growing transcript).
    """
    transcript = tmp_path / "session.jsonl"
    transcript.write_bytes(b"x" * 4096)
    watch = DeliveryGapWatch(
        gap_threshold=1024, stuck_grace_s=300.0, escalate_after_s=escalate_after_s
    )
    monkeypatch.setattr(delivery_watch, "_watch", watch)
    monkeypatch.setattr(delivery_watch, "iter_bound_topics", lambda: topics)
    monkeypatch.setattr(delivery_watch, "get_session_id", lambda _w: "sess-1")

    def projection(window_id):
        spec = deliveries.get(window_id)
        if spec is None:
            return None
        watermark, fenced = spec
        return DeliveryWatermark(
            watermark=watermark,
            transcript_path=str(transcript),
            fenced=fenced,
        )

    monkeypatch.setattr(delivery_watch, "get_delivery_watermark", projection)
    return FakeTelegramClient(), transcript


def _alert(w: DeliveryGapWatch, *args, **kwargs) -> bool:
    """Observe and project the first-alert decision (verdicts are tuples)."""
    return w.observe(*args, **kwargs).alert


class TestDeliveryGapWatch:
    def watch(self) -> DeliveryGapWatch:
        return DeliveryGapWatch(gap_threshold=1000, stuck_grace_s=300.0)

    def test_small_gap_never_alerts(self) -> None:
        w = self.watch()
        assert not _alert(w, "@1", offset=0, size=999, now=0.0)
        assert not _alert(w, "@1", offset=0, size=999, now=1000.0)

    def test_alert_fires_once_after_grace(self) -> None:
        w = self.watch()
        assert not _alert(w, "@1", offset=0, size=2000, now=0.0)
        assert not _alert(w, "@1", offset=0, size=2050, now=299.0)
        assert _alert(w, "@1", offset=0, size=2100, now=301.0)
        assert not _alert(w, "@1", offset=0, size=2200, now=602.0)
        # Static again after the alert: quiet, no repeat either way.
        assert not _alert(w, "@1", offset=0, size=2200, now=903.0)

    def test_offset_advance_rearms(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0)
        assert _alert(w, "@1", offset=0, size=2100, now=301.0)
        assert not _alert(w, "@1", offset=2000, size=2100, now=400.0)
        # New incident: first stuck observation starts the clock, the
        # next one past the grace fires again.
        assert not _alert(w, "@1", offset=2000, size=4000, now=701.0)
        assert _alert(w, "@1", offset=2000, size=4100, now=1002.0)

    def test_gap_shrink_below_threshold_rearms(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0)
        assert _alert(w, "@1", offset=0, size=2100, now=301.0)
        # Delivery catches up: gap small again, watch quiet.
        assert not _alert(w, "@1", offset=1900, size=2000, now=400.0)
        assert not _alert(w, "@1", offset=1900, size=2000, now=900.0)

    def test_disarm_rearms_the_one_shot(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0)
        assert _alert(w, "@1", offset=0, size=2100, now=301.0)
        w.disarm("@1")
        assert _alert(w, "@1", offset=0, size=2200, now=361.0)

    def test_static_transcript_is_quiet_time(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0)
        assert not _alert(w, "@1", offset=0, size=2000, now=1000.0)
        # Growth resumes after quiet time: the grace clock restarted at
        # the last quiet observation, so the burst alone cannot fire.
        assert not _alert(w, "@1", offset=0, size=2400, now=1001.0)
        assert _alert(w, "@1", offset=0, size=2500, now=1302.0)

    def test_transcript_switch_resets_state(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0, transcript_path="/a")
        # Same window id, new transcript: the old timers must not fire.
        assert not _alert(
            w, "@1", offset=0, size=9000, now=5000.0, transcript_path="/b"
        )
        assert not _alert(
            w, "@1", offset=0, size=9100, now=5001.0, transcript_path="/b"
        )

    def test_pause_stops_the_clock(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0)
        w.pause("@1")
        # Fenced time does not count; the clock restarts on the next
        # observation and the grace applies from there.
        assert not _alert(w, "@1", offset=0, size=2100, now=400.0)
        assert not _alert(w, "@1", offset=0, size=2200, now=500.0)
        assert _alert(w, "@1", offset=0, size=2300, now=801.0)

    def test_forget_prunes_unbound_windows(self) -> None:
        w = self.watch()
        w.observe("@1", offset=0, size=2000, now=0.0)
        w.observe("@2", offset=0, size=2000, now=0.0)
        w.forget({"@2"})
        assert set(w._windows) == {"@2"}

    def test_escalation_fires_once_after_threshold_and_persists(self) -> None:
        w = DeliveryGapWatch(
            gap_threshold=1000, stuck_grace_s=300.0, escalate_after_s=600.0
        )
        w.observe("@1", offset=0, size=2000, now=0.0)
        verdict = w.observe("@1", offset=0, size=2100, now=301.0)
        assert verdict.alert
        assert not verdict.persistent
        verdict = w.observe("@1", offset=0, size=2200, now=602.0)
        assert not verdict.alert
        assert verdict.persistent
        assert verdict.escalate
        # Later passes keep journalling but never re-notify.
        for now in (663.0, 724.0):
            verdict = w.observe("@1", offset=0, size=2300, now=now)
            assert verdict.persistent
            assert not verdict.escalate
        # Recovery ends the incident and re-arms everything.
        verdict = w.observe("@1", offset=2300, size=2300, now=800.0)
        assert not verdict.alert
        verdict = w.observe("@1", offset=0, size=3300, now=900.0)
        assert not verdict.persistent
        assert not verdict.escalate

    def test_escalation_disabled_never_escalates(self) -> None:
        w = DeliveryGapWatch(
            gap_threshold=1000, stuck_grace_s=300.0, escalate_after_s=0.0
        )
        w.observe("@1", offset=0, size=2000, now=0.0)
        verdict = w.observe("@1", offset=0, size=2100, now=10_000.0)
        assert verdict.alert
        assert not verdict.persistent
        assert not verdict.escalate


class TestCheckDeliveryWedges:
    async def test_stalled_window_alerts_once_via_direct_send(
        self, monkeypatch, tmp_path
    ) -> None:
        client, transcript = _wire(
            monkeypatch,
            tmp_path,
            topics=[(7, -100200, 42, "@1")],
            deliveries={"@1": (0, False)},
        )

        # First pass: starts the stuck clock, no alert.
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 0.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 0

        # Same watermark, transcript grown, 301s later: one alert.
        transcript.write_bytes(b"x" * 8192)
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 301.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 1
        call = client.last_call("send_message")
        assert call is not None
        assert call.kwargs["message_thread_id"] == 42
        assert "Delivery stall" in call.kwargs["text"]

        # Still stuck later: no repeat.
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 602.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 1

    async def test_fenced_freeze_is_not_a_wedge(self, monkeypatch, tmp_path) -> None:
        client, transcript = _wire(
            monkeypatch,
            tmp_path,
            topics=[(7, -100200, 42, "@1")],
            deliveries={"@1": (0, True)},
        )
        # Grow the transcript every pass: the quiet-time reset must not be
        # what keeps the fenced freeze from alerting.
        for now in (0.0, 301.0, 602.0):
            transcript.write_bytes(b"x" * (4096 + int(now)))
            monkeypatch.setattr(delivery_watch.time, "monotonic", lambda n=now: n)
            await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 0

    async def test_failed_alert_send_retries_next_pass(
        self, monkeypatch, tmp_path
    ) -> None:
        client, transcript = _wire(
            monkeypatch,
            tmp_path,
            topics=[(7, -100200, 42, "@1")],
            deliveries={"@1": (0, False)},
        )
        attempts = {"n": 0}

        def flaky(**kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("telegram degraded")
            return True

        client.returns["send_message"] = flaky
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 0.0)
        await check_delivery_wedges(client)
        transcript.write_bytes(b"x" * 8192)
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 301.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert attempts["n"] == 1  # first alert failed...
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 361.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert attempts["n"] == 2  # ...and was retried next pass

    async def test_unresolved_chat_id_does_not_consume_the_alert(
        self, monkeypatch, tmp_path
    ) -> None:
        topics: list[tuple[int, int | None, int, str]] = [(7, None, 42, "@1")]
        client, transcript = _wire(
            monkeypatch,
            tmp_path,
            topics=topics,
            deliveries={"@1": (0, False)},
        )
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 0.0)
        await check_delivery_wedges(client)
        transcript.write_bytes(b"x" * 8192)
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 301.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 0
        # The chat mapping resolves; the alert fires on the next pass.
        topics[0] = (7, -100200, 42, "@1")
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 361.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 1

    async def test_unmeasurable_windows_skip(self, monkeypatch, tmp_path) -> None:
        client, _ = _wire(
            monkeypatch,
            tmp_path,
            topics=[(7, -100200, 42, "@1")],
            deliveries={"@1": None},
        )
        monkeypatch.setattr(delivery_watch.time, "monotonic", lambda: 0.0)
        await check_delivery_wedges(client)
        await _flush_alert_tasks()
        assert client.call_count("send_message") == 0
        assert delivery_watch._watch._windows == {}

    async def test_persistent_wedge_escalates_once_via_direct_send(
        self, monkeypatch, tmp_path
    ) -> None:
        """Two passes past the escalation threshold send the maintainer
        notice exactly once; every pass past it journals a WARNING (the
        2026-10-28 incident lived three days as journal noise)."""
        from structlog.testing import capture_logs

        client, transcript = _wire(
            monkeypatch,
            tmp_path,
            topics=[(7, -100200, 42, "@1")],
            deliveries={"@1": (0, False)},
            escalate_after_s=600.0,
        )
        with capture_logs() as logs:
            for now, size in ((0.0, 8192), (301.0, 12_288), (601.0, 16_384)):
                transcript.write_bytes(b"x" * size)
                monkeypatch.setattr(delivery_watch.time, "monotonic", lambda n=now: n)
                await check_delivery_wedges(client)
                await _flush_alert_tasks()

            assert client.call_count("send_message") == 2  # alert + escalation
            escalation = [
                c
                for c in client.calls
                if c.method == "send_message" and "wedge" in c.kwargs["text"]
            ]
            assert len(escalation) == 1
            assert "sess-1" in escalation[0].kwargs["text"]
            assert "replay" in escalation[0].kwargs["text"]

            # Two more passes deep into the wedge: the journal keeps
            # talking, the notice never repeats.
            for now, size in ((662.0, 20_480), (723.0, 24_576)):
                transcript.write_bytes(b"x" * size)
                monkeypatch.setattr(delivery_watch.time, "monotonic", lambda n=now: n)
                await check_delivery_wedges(client)
                await _flush_alert_tasks()
        persist_lines = [
            e["event"] for e in logs if "wedge persists" in str(e.get("event"))
        ]
        assert len(persist_lines) == 3  # the crossing pass plus both deep passes
        assert client.call_count("send_message") == 2

    async def test_escalation_send_failure_retries_next_pass(
        self, monkeypatch, tmp_path
    ) -> None:
        client, transcript = _wire(
            monkeypatch,
            tmp_path,
            topics=[(7, -100200, 42, "@1")],
            deliveries={"@1": (0, False)},
            escalate_after_s=600.0,
        )
        attempts = {"n": 0}

        def flaky(**kwargs):
            attempts["n"] += 1
            if "wedge" in kwargs["text"]:
                raise RuntimeError("telegram degraded")
            return True

        client.returns["send_message"] = flaky
        for now, size in ((0.0, 8192), (601.0, 16_384), (662.0, 20_480)):
            transcript.write_bytes(b"x" * size)
            monkeypatch.setattr(delivery_watch.time, "monotonic", lambda n=now: n)
            await check_delivery_wedges(client)
            await _flush_alert_tasks()

        assert attempts["n"] == 3  # alert + failed escalation + retry
