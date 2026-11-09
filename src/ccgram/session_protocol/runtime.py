"""Shared lifecycle for the in-process session protocol core."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from pathlib import Path
from typing import IO

from ..event_reader import read_new_events
from ..multiplexer.base import Multiplexer
from ..providers.base import HookEvent
from .backend import MultiplexerSessionBackend
from .models import ProtocolError
from .service import LocalSessionService
from .store import ProtocolStore

logger = logging.getLogger(__name__)


# Bound on per-event drain retries: a transient source flap recovers
# within a few poll cycles; a permanent per-event failure must not
# occupy a queue slot and a deferral forever.
_DRAIN_RETRY_MAX = 5


class ProtocolRuntime:
    def __init__(
        self,
        store: ProtocolStore,
        service: LocalSessionService,
        lock: IO[bytes],
        *,
        prefix: str = "",
    ) -> None:
        self.store = store
        self.service = service
        self.lock = lock
        self.prefix = prefix
        self.task: asyncio.Task[None] | None = None
        self._listener_cleanup: Callable[[], Awaitable[None]] | None = None
        self.hooks: asyncio.Queue[tuple[HookEvent, tuple[str, ...], int]] = (
            asyncio.Queue(256)
        )

    def set_listener_cleanup(
        self, cleanup: Callable[[], Awaitable[None]] | None
    ) -> None:
        self._listener_cleanup = cleanup

    def observe_hook(self, event: HookEvent) -> None:
        # A remote observer never blocks the Telegram monitor or its receipts.
        sessions = self.service.defer_hook(event, self.prefix)
        try:
            self.hooks.put_nowait((event, sessions, 0))
        except asyncio.QueueFull:
            # The evidence is lost, so the deferral it reserved must be
            # rolled back: a dropped hook may not brick the session until
            # a restart (incident 2026-11-09). Approvals fall back to
            # their pre-event state.
            self.service.resolve_hook(sessions)
            logger.error(
                "Protocol hook queue full; dropped hook evidence, deferral rolled back"
            )

    async def poll(self, prefix: str) -> None:
        while True:
            try:
                await self.service.refresh()
                while not self.hooks.empty():
                    event, sessions, attempt = self.hooks.get_nowait()
                    try:
                        await self.service.observe_hook(event, prefix)
                    except ProtocolError, OSError:
                        # ProtocolError covers both a transient source
                        # flap and a permanent per-event failure (an
                        # unreadable transcript raises the same 503), so
                        # transience cannot be decided by type: retry a
                        # bounded number of cycles, then drop the event
                        # with its deferral released rather than churn at
                        # 1 Hz on a slot forever.
                        if attempt + 1 >= _DRAIN_RETRY_MAX:
                            self.service.resolve_hook(sessions)
                            logger.warning(
                                "Dropping hook evidence for %s after %d "
                                "failed observations",
                                event.event_type,
                                _DRAIN_RETRY_MAX,
                                exc_info=True,
                            )
                            continue
                        logger.warning(
                            "Hook observation failed; retrying next cycle "
                            "(attempt %d/%d)",
                            attempt + 1,
                            _DRAIN_RETRY_MAX,
                            exc_info=True,
                        )
                        try:
                            self.hooks.put_nowait((event, sessions, attempt + 1))
                        except asyncio.QueueFull:
                            self.service.resolve_hook(sessions)
                            logger.error(
                                "Protocol hook queue full on retry; dropped "
                                "hook evidence, deferral rolled back"
                            )
                        break
                    except Exception:  # noqa: BLE001
                        # A per-event failure (e.g. malformed transcript
                        # data) must not kill the drain loop (task-65):
                        # log and keep draining.
                        logger.warning("Hook observation failed", exc_info=True)
                    # Every defer is balanced by exactly one resolve,
                    # whatever the observation outcome.
                    self.service.resolve_hook(sessions)
            except ProtocolError, OSError:
                logger.warning("Session protocol source unavailable", exc_info=True)
            await asyncio.sleep(1)

    async def close(self) -> None:
        try:
            if self._listener_cleanup is not None:
                await self._listener_cleanup()
        finally:
            try:
                if self.task is not None:
                    self.task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self.task
            finally:
                self.store.close()
                self.lock.close()


async def start_runtime(
    multiplexer: Multiplexer,
    directory: Path,
    command_dir: str,
    prefix: str,
    *,
    recovered_targets: list[tuple[str, str]] | None = None,
) -> ProtocolRuntime:
    """Create the shared core, recover fresh hooks, and start its poller."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_dir = Path.home() / ".cache" / "ccgram" / "locks"
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = lock_dir / f"protocol-{multiplexer.capabilities.name}.lock"
    resources = ExitStack()
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        lock = os.fdopen(fd, "a+b")
        resources.callback(lock.close)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "A session protocol core is already using this multiplexer backend"
            ) from exc
        store = ProtocolStore(directory / "protocol.sqlite3")
        resources.callback(store.close)
        for previous, current in recovered_targets or []:
            store.retarget(previous, current)
        service = LocalSessionService(
            MultiplexerSessionBackend(multiplexer, command_dir), store
        )
        runtime = ProtocolRuntime(store, service, lock, prefix=prefix)
    except BaseException:
        resources.close()
        raise
    resources.pop_all()
    try:
        await service.refresh()
        # Recover only fresh observations. Old hooks never recreate approvals.
        events_file = directory / "events.jsonl"
        offset = (
            max(0, events_file.stat().st_size - 65536) if events_file.exists() else 0
        )
        events, _ = await read_new_events(events_file, offset)
        for event in events:
            await service.observe_hook(event, prefix)
        await service.refresh()
        runtime.task = asyncio.create_task(
            runtime.poll(prefix), name="ccgram-session-protocol"
        )
    except BaseException:
        await runtime.close()
        raise
    return runtime
