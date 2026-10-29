"""Family rebind at adoption: a reopened workspace reuses its dead topic."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ccgram.handlers.topics import family_rebind
from ccgram.handlers.topics.family_rebind import (
    FamilyBinding,
    find_family_match,
    maybe_rebind_family_topic,
)
from ccgram.handlers.topics.topic_orchestration import handle_new_window
from ccgram.multiplexer.base import WindowRef
from ccgram.session_monitor import NewWindowEvent, SessionMonitor
from ccgram.telegram_client import FakeTelegramClient
from ccgram.thread_router import ThreadRouter

_OLD = "herdr-session-v1-old"
_NEW = "herdr-session-v1-new"
_CWD = "/repo"
_CHAT = -100200
_THREAD = 42
_USER = 7


def _binding(
    window_id: str = _OLD,
    *,
    cwd: str = _CWD,
    provider: str = "claude",
) -> FamilyBinding:
    return FamilyBinding(
        user_id=_USER,
        chat_id=_CHAT,
        thread_id=_THREAD,
        old_window_id=window_id,
        cwd=cwd,
        provider=provider,
    )


class TestFindFamilyMatch:
    def test_single_dead_same_family_binding_matches(self) -> None:
        match = find_family_match(_CWD, "claude", [_binding()])
        assert match is not None
        assert match.old_window_id == _OLD

    def test_two_dead_candidates_match_none(self) -> None:
        assert (
            find_family_match(_CWD, "claude", [_binding("@old-a"), _binding("@old-b")])
            is None
        )

    def test_two_bindings_same_old_window_match_first(self) -> None:
        # One logical window carries one topic per chat (the multi-chat
        # adoption shape): the binding rows dedup to one family member
        # and the rebind may fire, instead of refusing as ambiguous.
        twin = FamilyBinding(
            user_id=_USER,
            chat_id=-100201,
            thread_id=43,
            old_window_id="@old-a",
            cwd=_CWD,
            provider="claude",
        )
        assert (
            find_family_match(_CWD, "claude", [_binding("@old-a"), twin]).old_window_id
            == "@old-a"
        )

    def test_provider_mismatch_matches_none(self) -> None:
        assert find_family_match(_CWD, "claude", [_binding(provider="codex")]) is None

    def test_unknown_new_provider_matches_none(self) -> None:
        assert find_family_match(_CWD, "", [_binding()]) is None

    def test_dead_binding_without_provider_is_not_a_family(self) -> None:
        # An unattributable dead binding cannot prove a same-agent family.
        assert find_family_match(_CWD, "claude", [_binding(provider="")]) is None


class _Harness:
    """Real router and monitor behind the module seams, orphan-watch style."""

    def __init__(self, monkeypatch, tmp_path, *, raw: dict | None = None):
        self.router = ThreadRouter(
            schedule_save=lambda: None, has_window_state=lambda _wid: False
        )
        self.raw = raw if raw is not None else {}
        self.projects = tmp_path / "projects"
        self.projects.mkdir()
        self.monitor = SessionMonitor(
            projects_path=self.projects,
            state_file=tmp_path / "monitor_state.json",
        )
        self.cwds: dict[str, str] = {}
        self.providers: dict[str, str] = {}

        monkeypatch.setattr(family_rebind, "thread_router", self.router)
        monkeypatch.setattr(
            "ccgram.handlers.topics.topic_orchestration.thread_router",
            self.router,
        )
        # session_query's lazy router import resolves the two read seams.
        monkeypatch.setattr("ccgram.thread_router.thread_router", self.router)
        monkeypatch.setattr(
            family_rebind,
            "identity_state",
            SimpleNamespace(
                get_cwd=lambda wid: self.cwds.get(wid, ""),
                get_provider_name=lambda wid: self.providers.get(wid),
            ),
        )

        async def read_raw():
            return self.raw

        monkeypatch.setattr(family_rebind, "read_session_map_raw", read_raw)
        monkeypatch.setattr(family_rebind, "get_active_monitor", lambda: self.monitor)
        monkeypatch.setattr(
            "ccgram.handlers.topics.topic_orchestration.session_manager",
            MagicMock(),
        )
        monkeypatch.setattr(
            "ccgram.handlers.topics.topic_orchestration._auto_detect_provider",
            AsyncMock(),
        )

    def bind(self, window_id: str, *, user_id: int = _USER, thread_id: int = _THREAD):
        self.router.bind_thread(user_id, thread_id, window_id, chat_id=_CHAT)

    def transcript(self, session_id: str, *, size: int = 4096):
        project_dir = self.projects / _CWD.replace("/", "-")
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / f"{session_id}.jsonl"
        path.write_bytes(b"x" * size)
        return path

    def entry(self, window_id: str, session_id: str, transcript_path: str) -> None:
        self.raw[f"ccgram:{window_id}"] = {
            "schema_version": 1,
            "session_id": session_id,
            "cwd": _CWD,
            "window_name": "repo",
            "transcript_path": transcript_path,
            "provider_name": "claude",
        }


@pytest.fixture
def harness(monkeypatch, tmp_path):
    return _Harness(monkeypatch, tmp_path)


def _event(window_id: str = _NEW, cwd: str = _CWD) -> NewWindowEvent:
    return NewWindowEvent(
        window_id=window_id, session_id="", window_name="repo", cwd=cwd
    )


def _ref(window_id: str, *, cwd: str = _CWD, eligible: bool = True) -> WindowRef:
    return WindowRef(
        window_id=window_id, window_name="repo", cwd=cwd, topic_eligible=eligible
    )


def _create_bot() -> AsyncMock:
    bot = AsyncMock()
    topic = MagicMock()
    topic.message_thread_id = 77
    bot.create_forum_topic.return_value = topic
    return bot


class TestFamilyRebindFlow:
    async def test_dead_binding_same_cwd_reuses_topic(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        transcript = harness.transcript("s-new", size=4096)
        harness.entry(_NEW, "s-new", str(transcript))
        client = FakeTelegramClient()

        adopted = await handle_new_window(_event(), client, live_windows=[_ref(_NEW)])

        assert adopted is True
        assert client.call_count("create_forum_topic") == 0
        assert client.call_count("send_message") == 1
        call = client.last_call("send_message")
        assert call is not None
        assert call.kwargs["message_thread_id"] == _THREAD
        assert _OLD in call.kwargs["text"]
        assert _NEW in call.kwargs["text"]
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _NEW
        seeded = harness.monitor.state.get_session("s-new")
        assert seeded is not None
        assert seeded.last_byte_offset == 4096

    async def test_second_pass_after_rebind_is_inert(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        transcript = harness.transcript("s-new")
        harness.entry(_NEW, "s-new", str(transcript))
        client = FakeTelegramClient()
        listing = [_ref(_NEW)]

        assert await handle_new_window(_event(), client, live_windows=listing) is True
        assert await handle_new_window(_event(), client, live_windows=listing) is True

        assert client.call_count("create_forum_topic") == 0
        assert client.call_count("send_message") == 1

    async def test_hookless_rebind_notifies_pending_session(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        # No session_map entry for the new id; the provider comes from the
        # window state the adoption flow's auto-detection already wrote.
        harness.providers[_NEW] = "claude"
        client = FakeTelegramClient()

        adopted = await maybe_rebind_family_topic(
            _event(), client, live_windows=[_ref(_NEW)]
        )

        assert adopted is True
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _NEW
        call = client.last_call("send_message")
        assert call is not None
        assert "has not registered" in call.kwargs["text"]

    async def test_concurrent_same_family_rebinds_serialize(self, harness) -> None:
        # Two reopened windows from one family in a single batch: only the
        # first may take the dead topic, the second must fall through to a
        # new topic instead of stealing the binding back.
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        # No session_map entries here, so both new windows resolve their
        # provider from the window state auto-detection wrote.
        harness.providers[_NEW] = "claude"
        harness.providers["w2"] = "claude"
        client = FakeTelegramClient()

        first, second = await asyncio.gather(
            maybe_rebind_family_topic(_event(), client, live_windows=[_ref(_NEW)]),
            maybe_rebind_family_topic(_event("w2"), client, live_windows=[_ref("w2")]),
        )

        assert (first, second) == (True, False)
        assert client.call_count("send_message") == 1
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _NEW

    async def test_two_dead_candidates_create_a_new_topic(self, harness) -> None:
        harness.bind("@old-a")
        harness.bind("@old-b", thread_id=43)
        harness.cwds.update({"@old-a": _CWD, "@old-b": _CWD})
        harness.providers.update({"@old-a": "claude", "@old-b": "claude"})
        bot = _create_bot()

        adopted = await handle_new_window(_event(), bot, live_windows=[_ref(_NEW)])

        assert adopted is True
        bot.create_forum_topic.assert_called_once()
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == "@old-a"

    async def test_live_old_binding_is_not_rebound(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        bot = _create_bot()

        adopted = await handle_new_window(
            _event(), bot, live_windows=[_ref(_OLD), _ref(_NEW)]
        )

        assert adopted is True
        bot.create_forum_topic.assert_called_once()
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _OLD

    async def test_provider_mismatch_creates_a_new_topic(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "codex"
        bot = _create_bot()

        adopted = await handle_new_window(_event(), bot, live_windows=[_ref(_NEW)])

        assert adopted is True
        bot.create_forum_topic.assert_called_once()
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _OLD

    async def test_ineligible_new_window_falls_through(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        bot = _create_bot()

        adopted = await handle_new_window(
            _event(), bot, live_windows=[_ref(_NEW, eligible=False)]
        )

        assert adopted is True
        bot.create_forum_topic.assert_called_once()
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _OLD

    async def test_unconfirmed_listing_answers_false(self, harness) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        client = FakeTelegramClient()

        adopted = await maybe_rebind_family_topic(_event(), client, live_windows=None)

        assert adopted is False
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _OLD

    async def test_unreadable_map_answers_false(self, harness, monkeypatch) -> None:
        harness.bind(_OLD)
        harness.cwds[_OLD] = _CWD
        harness.providers[_OLD] = "claude"
        client = FakeTelegramClient()

        async def unreadable():
            return None

        monkeypatch.setattr(family_rebind, "read_session_map_raw", unreadable)

        adopted = await maybe_rebind_family_topic(
            _event(), client, live_windows=[_ref(_NEW)]
        )

        assert adopted is False
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _OLD

    async def test_healthy_system_skips_the_map_read(
        self, harness, monkeypatch
    ) -> None:
        # The known-unbound retry path re-fires adoption every poll; a
        # system with no dead bindings must not pay a file read per pass.
        reads = {"n": 0}

        async def read_raw():
            reads["n"] += 1
            return {}

        monkeypatch.setattr(family_rebind, "read_session_map_raw", read_raw)
        client = FakeTelegramClient()

        adopted = await maybe_rebind_family_topic(
            _event(), client, live_windows=[_ref(_NEW)]
        )

        assert adopted is False
        assert reads["n"] == 0

    async def test_fold_before_adoption_neither_creates_nor_rebinds(
        self, harness
    ) -> None:
        # reconcile_window_aliases has already folded the binding onto the
        # new id, exactly as it leaves state when it wins the race.
        harness.bind(_NEW)
        harness.cwds[_NEW] = _CWD
        harness.providers[_NEW] = "claude"
        client = FakeTelegramClient()

        adopted = await handle_new_window(_event(), client, live_windows=[_ref(_NEW)])

        assert adopted is True
        assert client.call_count("create_forum_topic") == 0
        assert client.call_count("send_message") == 0
        assert harness.router.chat_thread_bindings[(_USER, _CHAT, _THREAD)] == _NEW
