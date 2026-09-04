"""Extension seam: load out-of-tree feature packages via entry points.

Fork-local (see ``docs/extension-seam.md``). Packages in the same
environment declare::

    [project.entry-points."ccgram.extensions"]
    main = "my_package:register"

and expose ``register(api: ExtensionApi) -> None``. The core's entire
commitment is this module plus the four integration lines documented in
the design note; everything else a feature needs it takes through the
``ExtensionApi`` surface or ccgram's public modules.

Isolation rules: a broken ``register`` logs and never blocks boot; a
listener that raises is logged and never blocks the emitting path.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from importlib.metadata import entry_points
from typing import Any, Callable

from telegram.ext import BaseHandler

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "ccgram.extensions"

Listener = Callable[..., Any]

_registered_update_types: set[str] = set()
_listeners: dict[str, list[Listener]] = {}


class ExtensionApi:
    """The registration surface handed to each extension."""

    def __init__(self, add_handler: Callable[[BaseHandler], None]) -> None:
        self._add_handler = add_handler

    def register_ptb_handler(self, handler: BaseHandler, update_type: str) -> None:
        """Register a PTB handler and claim its update type.

        ``update_type`` lands in ``allowed_updates`` (run_polling filters
        to the listed types, so an unlisted handler would never fire).
        """
        self._add_handler(handler)
        _registered_update_types.add(update_type)

    def on(self, event: str, listener: Listener) -> None:
        """Subscribe to a core domain event (sync or async listener)."""
        _listeners.setdefault(event, []).append(listener)


def load_extensions(add_handler: Callable[[BaseHandler], None]) -> int:
    """Discover and register every installed extension. Returns the count.

    Called once from ``create_bot()`` (before ``run_polling`` captures
    allowed_updates). Each entry point resolves to ``register(api)``.
    """
    count = 0
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register = ep.load()
            register(ExtensionApi(add_handler))
            count += 1
            logger.info("extension loaded: %s", ep.name)
        except Exception:  # noqa: BLE001  # one bad package never blocks boot
            logger.exception("extension failed to load: %s", ep.name)
    return count


def resolved_allowed_updates(base: list[str]) -> list[str]:
    """Merge extension-claimed update types into the base list.

    Order-preserving dedup: an extension may legitimately claim an update
    type the base already lists (a CommandHandler claims "message"), and
    getUpdates should receive each type once.
    """
    merged = [*base, *_registered_update_types]
    return list(dict.fromkeys(merged))


def emit(event: str, **payload: Any) -> None:
    """Fire a domain event; sync listeners run, async ones are scheduled.

    Delivery code calls this inline, so listeners must never block: async
    listeners are handed to the running loop instead of awaited here, and
    every failure is contained.
    """
    for listener in _listeners.get(event, ()):
        try:
            result = listener(**payload)
            if inspect.isawaitable(result):
                # ensure_future takes any Awaitable (create_task does not).
                asyncio.ensure_future(result)
        except Exception:  # noqa: BLE001  # listener bugs never block emit
            logger.warning("extension listener failed: %s", event, exc_info=True)


def reset_for_testing() -> None:
    """Clear all extension state between tests."""
    _registered_update_types.clear()
    _listeners.clear()
