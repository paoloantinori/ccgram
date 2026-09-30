"""Backend-neutral push-updated agent-status cache.

The herdr event-stream consumer writes the latest native ``AgentStatus`` per
window here; the status-polling layer (``observe._native_agent_status``) reads
it synchronously instead of forking a ``herdr`` subprocess every tick. This
bridges the push stream and the existing poll loop (the "augment" reconcile):
push keeps the cache fresh, the poll reads it, and a one-shot subprocess
``agent_status()`` is the cold-cache fallback.

Pure module — depends only on the seam value type (``AgentStatus``), never on a
concrete backend, so the polling layer can import it without crossing the F1
boundary (mirrors ``multiplexer.vim_state``). All access is from the single
asyncio event-loop thread, so a plain dict suffices.
"""

from __future__ import annotations

from .base import AgentStatus

_cache: dict[str, AgentStatus] = {}


def set_status(window_id: str, status: AgentStatus) -> None:
    """Record the latest push-reported agent status for *window_id*."""
    _cache[window_id] = status


def get_status(window_id: str) -> AgentStatus | None:
    """Return the cached push status for *window_id*, or None when cold."""
    return _cache.get(window_id)


def clear(window_id: str) -> None:
    """Drop the cached status for *window_id* (e.g. on window death)."""
    _cache.pop(window_id, None)


def reset() -> None:
    """Clear the whole cache (consumer shutdown; test isolation)."""
    _cache.clear()


def agent_working(window_id: str) -> bool:
    """Whether the window's agent is actively working right now.

    The interactive-UI scrapers use this to skip prompt detection while
    the agent runs: a working agent cannot be asking a selection (a real
    prompt pauses the turn), and Claude Code's queued-input block (the
    rendering of messages typed mid-turn) is exactly the
    selection-shaped region a working pane shows (TASK-47). Unknown or
    missing status (tmux, cold cache) reports False so callers keep
    their existing scraping behavior.
    """
    status = _cache.get(window_id)
    return status is not None and status.state == "working"
