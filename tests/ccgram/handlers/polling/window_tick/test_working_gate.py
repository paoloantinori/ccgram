"""The working-agent gate at the status-resolution seam (TASK-47).

A selection-shaped region on a WORKING pane is Claude Code's queued-input
block (messages typed mid-turn), not a prompt. Both scrapers' results pass
through ``_resolve_status``, so one suppression there covers the strategy
parse and the provider parse alike, falling through to the native working
status instead of latching a false interactive state.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers.polling.window_tick import observe
from ccgram.handlers.polling.window_tick.observe import _resolve_status
from ccgram.multiplexer import agent_status_cache
from ccgram.multiplexer.base import AgentStatus
from ccgram.providers.base import StatusUpdate


@pytest.fixture(autouse=True)
def _clear_status_cache():
    agent_status_cache.reset()
    yield
    agent_status_cache.reset()


_WINDOW = SimpleNamespace(pane_width=100, pane_height=40)
_INTERACTIVE = StatusUpdate(
    raw_text="queued block",
    display_label="SelectionUI",
    is_interactive=True,
    ui_type="SelectionUI",
)
_WORKING = AgentStatus(state="working", agent="claude")


def _provider(return_value):
    provider = SimpleNamespace(
        capabilities=SimpleNamespace(
            uses_pyte_status_parsing=True, uses_pane_title=False
        ),
        parse_terminal_status=lambda *a, **k: return_value,
    )
    return provider


def _mux(*, native=True, supports_event_stream=True, agent_status=None) -> MagicMock:
    mux = MagicMock()
    mux.capabilities = SimpleNamespace(
        native_agent_status=native, supports_event_stream=supports_event_stream
    )
    mux.agent_status = agent_status or AsyncMock(return_value=None)
    return mux


async def test_working_status_suppresses_strategy_interactive() -> None:
    # Stream backend, warm cache: the gate suppresses without probing.
    agent_status_cache.set_status("w1", _WORKING)
    mux = _mux(agent_status=AsyncMock(return_value=_WORKING))
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w1", "pane", _WINDOW)
    assert result is not None and not result.is_interactive
    assert result.display_label == "working"
    mux.agent_status.assert_not_awaited()


async def test_working_status_suppresses_provider_interactive() -> None:
    agent_status_cache.set_status("w2", _WORKING)
    mux = _mux(agent_status=AsyncMock(return_value=_WORKING))
    with (
        patch.object(observe, "tmux_manager", mux),
        patch.object(observe, "_parse_with_pyte", return_value=None),
        patch.object(observe, "_get_provider", return_value=_provider(_INTERACTIVE)),
    ):
        result = await _resolve_status("w2", "pane", _WINDOW)
    assert result is not None and not result.is_interactive


async def test_idle_status_keeps_interactive() -> None:
    agent_status_cache.set_status("w3", AgentStatus(state="idle"))
    mux = _mux(agent_status=AsyncMock(return_value=AgentStatus(state="idle")))
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w3", "pane", _WINDOW)
    assert result is not None and result.is_interactive


async def test_probe_only_gate_ignores_stale_cached_working() -> None:
    # TASK-54: on a probe-only backend nothing refreshes a cached
    # "working"; the gate must re-probe instead of trusting it for the
    # full 90s positive TTL, so a working->idle transition lets a real
    # prompt through within one probe.
    agent_status_cache.set_status("w4", _WORKING)
    mux = _mux(
        supports_event_stream=False,
        agent_status=AsyncMock(return_value=AgentStatus(state="idle")),
    )
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w4", "pane", _WINDOW)
    assert result is not None and result.is_interactive
    mux.agent_status.assert_awaited()


async def test_probe_only_gate_honors_fresh_working_probe() -> None:
    agent_status_cache.set_status("w4", AgentStatus(state="idle"))
    mux = _mux(
        supports_event_stream=False, agent_status=AsyncMock(return_value=_WORKING)
    )
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w4", "pane", _WINDOW)
    assert result is not None and not result.is_interactive


async def test_cold_cache_probes_and_suppresses_on_working() -> None:
    # Cold cache: the probe runs once and its "working" answer suppresses.
    mux = _mux(agent_status=AsyncMock(return_value=_WORKING))
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w1", "pane", _WINDOW)
    assert result is not None and not result.is_interactive
    mux.agent_status.assert_awaited_once_with("w1")


async def test_raising_probe_fails_open_and_keeps_interactive() -> None:
    # A backend probe error (e.g. herdr transport failure raising
    # HerdrError, a RuntimeError) must not break the tick: the gate
    # answers "not working" and the interactive status stands.
    mux = _mux(agent_status=AsyncMock(side_effect=RuntimeError("socket dead")))
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w2", "pane", _WINDOW)
    assert result is not None and result.is_interactive


async def test_backend_without_native_status_keeps_interactive_without_probing():
    # The native_agent_status gate: a backend without the capability must
    # never probe and never suppress (even with a poisoned cache).
    agent_status_cache.set_status("w5", _WORKING)
    mux = _mux(native=False, agent_status=AsyncMock(return_value=_WORKING))
    with (
        patch.object(observe, "_parse_with_pyte", return_value=_INTERACTIVE),
        patch.object(observe, "_get_provider", return_value=_provider(None)),
        patch.object(observe, "tmux_manager", mux),
    ):
        result = await _resolve_status("w5", "pane", _WINDOW)
    assert result is not None and result.is_interactive
    mux.agent_status.assert_not_awaited()
