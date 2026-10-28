"""Session-orphan self-healing: pure decision core and wiring."""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from ccgram.handlers.polling import orphan_watch
from ccgram.handlers.polling.orphan_watch import (
    Candidate,
    OrphanAction,
    OrphanBindingWatch,
    check_orphan_bindings,
)
from ccgram.session_monitor import SessionMonitor
from ccgram.telegram_client import FakeTelegramClient

_NOW = 10_000_000.0


@pytest.fixture(autouse=True)
def _fresh_watch():
    """Isolate the module watch between tests."""
    orphan_watch.reset_for_testing()
    yield
    orphan_watch.reset_for_testing()


def _candidate(session_id: str, mtime: float = 1.0) -> Candidate:
    return Candidate(
        session_id=session_id,
        transcript_path=f"/projects/-repo/{session_id}.jsonl",
        mtime=mtime,
        size=128,
    )


class TestOrphanBindingWatch:
    def watch(self) -> OrphanBindingWatch:
        return OrphanBindingWatch()

    def test_missing_entry_with_one_candidate_relinks(self) -> None:
        w = self.watch()
        verdict = w.observe(
            "@1", live=True, entry_session_id=None, candidates=[_candidate("s2")]
        )
        assert verdict.action is OrphanAction.RELINK
        assert verdict.candidate is not None and verdict.candidate.session_id == "s2"
        assert verdict.first_detection

    def test_missing_entry_without_candidates_notices(self) -> None:
        w = self.watch()
        verdict = w.observe("@1", live=True, entry_session_id=None, candidates=[])
        assert verdict.action is OrphanAction.NOTICE
        assert "no live transcript" in verdict.reason

    def test_missing_entry_with_two_candidates_is_ambiguous(self) -> None:
        w = self.watch()
        verdict = w.observe(
            "@1",
            live=True,
            entry_session_id=None,
            candidates=[_candidate("s2"), _candidate("s3")],
        )
        assert verdict.action is OrphanAction.NOTICE
        assert "2 live transcripts" in verdict.reason

    def test_stale_entry_relinks_to_fresh_candidate(self) -> None:
        w = self.watch()
        verdict = w.observe(
            "@1", live=True, entry_session_id="s1", candidates=[_candidate("s2")]
        )
        assert verdict.action is OrphanAction.RELINK
        assert verdict.old_session_id == "s1"

    def test_healthy_entry_own_session_alive_is_quiet(self) -> None:
        w = self.watch()
        verdict = w.observe(
            "@1", live=True, entry_session_id="s1", candidates=[_candidate("s1")]
        )
        assert verdict.action is OrphanAction.NONE

    def test_stale_entry_with_no_fresh_candidate_stays_quiet(self) -> None:
        # An idle agent writes nothing: absence of evidence is not an orphan.
        w = self.watch()
        verdict = w.observe("@1", live=True, entry_session_id="s1", candidates=[])
        assert verdict.action is OrphanAction.NONE

    def test_not_live_observation_clears_the_incident(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        assert w.pending_notice("@1")
        w.observe("@1", live=False, entry_session_id=None, candidates=[])
        assert not w.pending_notice("@1")

    def test_recovery_after_orphan_ends_the_incident(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        verdict = w.observe(
            "@1", live=True, entry_session_id="s2", candidates=[_candidate("s2")]
        )
        assert verdict.action is OrphanAction.NONE
        assert not w.pending_notice("@1")

    def test_second_detection_is_not_first(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        verdict = w.observe("@1", live=True, entry_session_id=None, candidates=[])
        assert verdict.action is OrphanAction.NOTICE
        assert not verdict.first_detection

    def test_mark_notified_latches_until_resolved(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        assert w.pending_notice("@1")
        w.mark_notified("@1")
        assert not w.pending_notice("@1")

    def test_rearm_restores_the_owed_notice(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        w.mark_notified("@1")
        w.rearm("@1")
        assert w.pending_notice("@1")

    def test_resolve_closes_the_incident(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        w.resolve("@1")
        assert not w.pending_notice("@1")

    def test_forget_prunes_unbound_windows(self) -> None:
        w = self.watch()
        w.observe("@1", live=True, entry_session_id=None, candidates=[])
        w.observe("@2", live=True, entry_session_id=None, candidates=[])
        w.forget({"@2"})
        assert set(w._incidents) == {"@2"}


class _FakeSync:
    """In-memory stand-in for the session_map persistence pair."""

    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.registered: list[dict] = []
        self.written: list[dict] = []

    def register_hookless_session(self, **kwargs) -> None:
        self.registered.append(kwargs)

    def write_hookless_session_map(self, **kwargs) -> None:
        self.written.append(kwargs)
        key = f"ccgram:{kwargs['window_id']}"
        self.raw[key] = {
            "schema_version": 1,
            "session_id": kwargs["session_id"],
            "cwd": kwargs["cwd"],
            "window_name": "repo",
            "transcript_path": kwargs["transcript_path"],
            "provider_name": kwargs["provider_name"],
        }


def _write_transcript(
    projects_dir, cwd: str, session_id: str, *, age_s: float = 0.0, size: int = 4096
):
    project_dir = projects_dir / cwd.replace("/", "-")
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    path.write_bytes(b"x" * size)
    stamp = _NOW - age_s
    os.utime(path, (stamp, stamp))
    return path


def _entry(session_id: str, transcript_path: str) -> dict:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "cwd": "/repo",
        "window_name": "repo",
        "transcript_path": transcript_path,
        "provider_name": "claude",
    }


class _Harness:
    """Point the watch at synthetic bindings, map, listing, and monitor."""

    def __init__(self, monkeypatch, tmp_path, raw: dict):
        from ccgram.config import config

        harness = self

        def harness_memory(window_id):
            return harness.memory_sessions.get(window_id)

        self.raw = raw
        self.projects = tmp_path / "projects"
        self.projects.mkdir()
        self.map_file = tmp_path / "session_map.json"
        self.map_file.write_text(json.dumps(raw))
        self.sync = _FakeSync(raw)
        self.monitor = SessionMonitor(
            projects_path=self.projects,
            state_file=tmp_path / "monitor_state.json",
        )
        self.topics: list[tuple[int, int | None, int, str]] = [(7, -100200, 42, "@1")]
        self.windows: list = [
            SimpleNamespace(window_id="@1", window_name="repo", cwd="/repo")
        ]
        self.pending: set[str] = set()
        self.memory_sessions: dict[str, str] = {}

        monkeypatch.setattr(config, "orphan_watch_enabled", True)
        monkeypatch.setattr(config, "orphan_auto_relink", True)
        monkeypatch.setattr(config, "claude_projects_path", self.projects)
        monkeypatch.setattr(
            orphan_watch, "iter_bound_topics", lambda: list(self.topics)
        )
        monkeypatch.setattr(orphan_watch, "session_map_sync", self.sync)

        async def read_raw():
            return self.raw

        monkeypatch.setattr(orphan_watch, "read_session_map_raw", read_raw)
        monkeypatch.setattr(orphan_watch, "get_active_monitor", lambda: self.monitor)
        monkeypatch.setattr(orphan_watch, "session_map_prefix", lambda: "ccgram:")
        monkeypatch.setattr(
            orphan_watch,
            "identity_state",
            SimpleNamespace(
                get_cwd=lambda window_id: "",
                get_session_id=lambda window_id: harness_memory(window_id),
                get_provider_name=lambda window_id: "claude",
                accepts_provider_observation=lambda window_id, provider: True,
            ),
        )
        monkeypatch.setattr(orphan_watch, "time", SimpleNamespace(time=lambda: _NOW))
        monkeypatch.setattr("ccgram.session_map.session_map_prefix", lambda: "ccgram:")
        monkeypatch.setattr("ccgram.session_map.config.session_map_file", self.map_file)
        monkeypatch.setattr(
            "ccgram.handlers.topics.topic_orchestration.is_pending_creation",
            lambda window_id: window_id in self.pending,
        )
        monkeypatch.setattr(
            "ccgram.thread_router.thread_router",
            SimpleNamespace(get_display_name=lambda window_id: "repo"),
        )

    def transcript(self, session_id: str, **kwargs):
        return _write_transcript(self.projects, "/repo", session_id, **kwargs)

    async def read_map_entry(self, window_id: str):
        from ccgram.session_map import raw_session_map_entry

        return raw_session_map_entry(self.raw, window_id)


async def _flush_notice_tasks() -> None:
    while orphan_watch._notice_tasks:
        await asyncio.wait_for(
            asyncio.gather(*orphan_watch._notice_tasks, return_exceptions=True),
            timeout=5,
        )


class TestCheckOrphanBindings:
    async def test_missing_entry_relinks_notices_and_seeds_eof(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        transcript = harness.transcript("s-new", size=4096)
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert [w["session_id"] for w in harness.sync.written] == ["s-new"]
        assert harness.sync.written[0]["transcript_path"] == str(transcript)
        seeded = harness.monitor.state.get_session("s-new")
        assert seeded is not None
        assert seeded.last_byte_offset == 4096  # EOF, never zero/replay
        assert harness.map_file.with_name("session_map.json.orphan-relink.bak").exists()
        assert client.call_count("send_message") == 1
        call = client.last_call("send_message")
        assert call is not None
        assert call.kwargs["message_thread_id"] == 42
        assert "Session relink" in call.kwargs["text"]
        assert "s-new" in call.kwargs["text"]

    async def test_stale_entry_relinks_to_live_session(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        old_path = harness.transcript("s-old", age_s=3600.0)
        harness.transcript("s-new")
        harness.raw["ccgram:@1"] = _entry("s-old", str(old_path))
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert [w["session_id"] for w in harness.sync.written] == ["s-new"]
        call = client.last_call("send_message")
        assert call is not None
        assert "s-old" in call.kwargs["text"]
        assert "s-new" in call.kwargs["text"]

    async def test_two_candidates_notice_without_relink(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-a")
        harness.transcript("s-b")
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 1
        call = client.last_call("send_message")
        assert call is not None
        assert "cannot attribute" in call.kwargs["text"]

        # Second pass: still ambiguous, but the notice is one per incident.
        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()
        assert client.call_count("send_message") == 1

    async def test_no_transcript_notice_without_relink(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 1
        call = client.last_call("send_message")
        assert call is not None
        assert "no live transcript" in call.kwargs["text"]

    async def test_watch_disabled_is_inert(self, monkeypatch, tmp_path) -> None:
        from ccgram.config import config

        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        monkeypatch.setattr(config, "orphan_watch_enabled", False)
        reads = {"n": 0}

        async def read_raw():
            reads["n"] += 1
            return harness.raw

        monkeypatch.setattr(orphan_watch, "read_session_map_raw", read_raw)
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert reads["n"] == 0
        assert harness.sync.written == []
        assert client.call_count("send_message") == 0

    async def test_auto_relink_disabled_notices_only(
        self, monkeypatch, tmp_path
    ) -> None:
        from ccgram.config import config

        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        monkeypatch.setattr(config, "orphan_auto_relink", False)
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 1
        call = client.last_call("send_message")
        assert call is not None
        assert "auto-relink disabled" in call.kwargs["text"]

    async def test_second_tick_after_relink_does_nothing(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()
        assert len(harness.sync.written) == 1

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert len(harness.sync.written) == 1
        assert client.call_count("send_message") == 1

    async def test_healthy_window_is_untouched(self, monkeypatch, tmp_path) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        transcript = harness.transcript("s-live")
        harness.raw["ccgram:@1"] = _entry("s-live", str(transcript))
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 0

    async def test_pending_creation_window_is_skipped(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        harness.pending.add("@1")
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 0

    async def test_unreadable_map_skips_the_pass(self, monkeypatch, tmp_path) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")

        async def read_raw():
            return None

        monkeypatch.setattr(orphan_watch, "read_session_map_raw", read_raw)
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 0

    async def test_unconfirmed_listing_skips_the_pass(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        client = FakeTelegramClient()

        await check_orphan_bindings(client, None)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 0

    async def test_unresolved_chat_keeps_notice_owed(
        self, monkeypatch, tmp_path
    ) -> None:
        # Ambiguous orphan: the incident (and its owed notice) persists
        # until delivered, so an unresolved chat mapping retries later.
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-a")
        harness.transcript("s-b")
        harness.topics[0] = (7, None, 42, "@1")
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()
        assert client.call_count("send_message") == 0

        harness.topics[0] = (7, -100200, 42, "@1")
        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()
        assert client.call_count("send_message") == 1

    async def test_window_gone_from_listing_never_notices(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.windows = []
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        assert client.call_count("send_message") == 0

    async def test_stale_dead_window_entry_does_not_veto_relink(
        self, monkeypatch, tmp_path
    ) -> None:
        # herdr never prunes dead windows' entries. The leftover entry for
        # a window that is gone must not claim the fresh transcript away
        # from the live orphan that actually needs the relink.
        harness = _Harness(monkeypatch, tmp_path, raw={})
        dead_path = harness.transcript("s-dead", age_s=0.0)
        harness.raw["ccgram:@9"] = _entry("s-dead", str(dead_path))
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert [w["session_id"] for w in harness.sync.written] == ["s-dead"]

    async def test_other_windows_memory_claim_blocks_cross_relink(
        self, monkeypatch, tmp_path
    ) -> None:
        # Two orphaned windows in one cwd. @2 is active and its state
        # remembers its session; @1 is idle with a stale transcript.
        # Without the memory claim, @1 would hijack @2's live session.
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-1", age_s=3600.0)
        harness.transcript("s-2")
        harness.memory_sessions["@2"] = "s-2"
        harness.topics.append((7, -100200, 43, "@2"))
        harness.windows.append(
            SimpleNamespace(window_id="@2", window_name="repo2", cwd="/repo")
        )
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        relinked = {w["window_id"]: w["session_id"] for w in harness.sync.written}
        assert relinked == {"@2": "s-2"}

    async def test_one_relink_per_session_within_a_pass(
        self, monkeypatch, tmp_path
    ) -> None:
        # Both entries missing, one fresh transcript: the first window
        # relinks, and the second must not take the same session in the
        # same pass (claim snapshot otherwise goes stale mid-pass).
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        harness.topics.append((7, -100200, 43, "@2"))
        harness.windows.append(
            SimpleNamespace(window_id="@2", window_name="repo2", cwd="/repo")
        )
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        relinked = {w["window_id"]: w["session_id"] for w in harness.sync.written}
        assert relinked == {"@1": "s-new"}

    async def test_provider_pin_mismatch_skips_relink_with_reason(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-new")
        monkeypatch.setattr(
            orphan_watch.identity_state,
            "accepts_provider_observation",
            lambda window_id, provider: False,
        )
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        assert harness.sync.written == []
        call = client.last_call("send_message")
        assert call is not None
        assert "pinned provider" in call.kwargs["text"]

    async def test_second_topic_on_the_same_window_gets_the_notice(
        self, monkeypatch, tmp_path
    ) -> None:
        harness = _Harness(monkeypatch, tmp_path, raw={})
        harness.transcript("s-a")
        harness.transcript("s-b")
        harness.topics.append((8, -100200, 77, "@1"))
        client = FakeTelegramClient()

        await check_orphan_bindings(client, harness.windows)
        await _flush_notice_tasks()

        thread_ids = sorted(
            call.kwargs["message_thread_id"]
            for call in client.calls
            if call.method == "send_message"
        )
        assert thread_ids == [42, 77]
