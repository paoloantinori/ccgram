"""Read-only session resolution — free functions wrapping session_resolver.

Provides handler modules with direct access to session resolution without
importing SessionManager. Follows the same decoupling pattern as window_query.py.

Key functions:
  resolve_session_for_window: find ClaudeSession for a tmux window
  find_users_for_session: find users bound to a session
  get_recent_messages: read paginated message history
  resolve_chat_id: resolve the delivery chat for a polling topic without a
      direct handler import of the thread-router singleton

Each wrapper imports ``session_resolver`` lazily on purpose: handlers
that only need read-only resolution (the whole point of this module)
must not pay the singleton's tmux + JSONL discovery costs at module
load.  Hoisting the import would also re-establish the indirect
session_resolver ↔ SessionManager dependency this projection exists
to avoid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session_resolver import ClaudeSession


def iter_bound_topics() -> list[tuple[int, int | None, int, str]]:
    """(user_id, chat_id, thread_id, window_id) for every bound topic."""
    # Lazy: the router is installed by SessionManager during bootstrap.
    from .thread_router import thread_router

    return list(thread_router.iter_thread_bindings_with_chat())


def resolve_chat_id(user_id: int, thread_id: int | None = None) -> int:
    """Resolve a topic's delivery chat for handlers subject to the layering audit."""
    # Lazy: the router is installed by SessionManager during bootstrap.
    from .thread_router import thread_router

    return thread_router.resolve_chat_id(user_id, thread_id)


async def resolve_session_for_window(window_id: str) -> "ClaudeSession | None":
    """Resolve the Claude session for a tmux window, or None if not found."""
    # Lazy: session_resolver constructed per-call so tests can stub it
    from .session_resolver import session_resolver

    return await session_resolver.resolve_session_for_window(window_id)


def find_users_for_session(
    session_id: str,
) -> list[tuple[int, str, int, int | None]]:
    """Return list of (user_id, window_id, thread_id, chat_id) for all bound users."""
    # Lazy: session_resolver constructed per-call so tests can stub it
    from .session_resolver import session_resolver

    return session_resolver.find_users_for_session(session_id)


async def get_recent_messages(
    window_id: str,
    *,
    start_byte: int = 0,
    end_byte: int | None = None,
) -> tuple[list[dict], int]:
    """Get user/assistant messages for a window's session.

    Returns (messages, total_count). Supports byte-range filtering.
    """
    # Lazy: session_resolver constructed per-call so tests can stub it
    from .session_resolver import session_resolver

    return await session_resolver.get_recent_messages(
        window_id, start_byte=start_byte, end_byte=end_byte
    )


def resolve_window_for_topic(user_id: int, thread_id: int, chat_id: int) -> str | None:
    """Resolve an exact user/chat/topic binding through the routing read seam."""
    # Lazy: the router is installed by SessionManager during bootstrap.
    from .thread_router import thread_router

    return thread_router.resolve_window_for_thread(user_id, thread_id, chat_id)


def binding_matches_window(
    user_id: int, thread_id: int | None, chat_id: int | None, window_id: str
) -> bool:
    """Whether a topic is still bound to the window, legacy and alias aware.

    The chat-scoped map is checked first and the legacy chat-less map
    accepts too, so a binding recorded before chat scoping does not read
    as a rebind; the window id converges through ``resolve_window_alias``
    because callers hold the id frozen at arm time. Deliberately
    session-agnostic: a barrier stays valid while the TOPIC binding
    holds, even if the window's session rolled over underneath it.
    """
    # Lazy: the router is installed by SessionManager during bootstrap.
    from .thread_router import thread_router

    # Lazy: same bootstrap-time wiring as the router import above.
    from .window_resolver import resolve_window_alias

    canonical = resolve_window_alias(window_id)
    return (
        thread_router.resolve_window_for_thread(user_id, thread_id, chat_id)
        == canonical
        or thread_router.resolve_window_for_thread(user_id, thread_id) == canonical
    )
