import asyncio
import hashlib
import json
import time
from dataclasses import replace
from tempfile import TemporaryFile
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ccgram.providers.base import HookEvent
from ccgram.session_protocol.backend import Prompt
from ccgram.session_protocol.models import Action, ProtocolError
from ccgram.session_protocol.requests import PendingHook
from ccgram.session_protocol.runtime import ProtocolRuntime


@pytest.mark.parametrize("kind", ["request.respond", "message.send"])
async def test_queued_hook_blocks_stale_actions_before_polling(
    service, backend, store, kind
):
    session = (await service.list_sessions())[0]
    backend.current_prompt = Prompt("/tmp/file\n1. Yes\n2. No", "permission")
    service.requests.observe_hook(
        session.id,
        PendingHook(
            "conv",
            "permission",
            "Edit",
            {"file_path": "/tmp/file", "content": "old"},
            time.time(),
        ),
    )
    snapshot = await service.get_session(session.id)
    data = (
        {"requestId": snapshot.open_requests[0].id, "optionId": "1"}
        if kind == "request.respond"
        else {"text": "continue", "dismissRequest": True}
    )
    with TemporaryFile() as lock:
        runtime = ProtocolRuntime(store, service, lock)
        runtime.observe_hook(
            HookEvent(
                "PermissionRequest",
                "@1",
                "conv",
                {"tool_name": "Edit", "tool_input_hash": "replacement"},
                time.time(),
            )
        )
        result, status = await service.execute(
            session.id, Action(str(uuid4()), snapshot.binding_version, kind, data)
        )
    assert status == 409 and result.outcome == "rejected"
    assert backend.sent == []


@pytest.mark.parametrize("matched", [False, True])
async def test_pending_hooks_release_only_after_transcript_processing(
    service, backend, store, tmp_path, monkeypatch, matched
):
    path = tmp_path / "transcript.jsonl"
    tool_input = {"command": "git status"}
    path.write_text(
        json.dumps(
            {
                "uuid": "tool",
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call",
                            "name": "Bash",
                            "input": tool_input,
                        }
                    ]
                },
            }
        )
        + "\n"
    )
    backend.target = replace(backend.target, transcript=path)
    session = (await service.list_sessions())[0]
    backend.current_prompt = Prompt("git status\n1. Yes\n2. No", "permission")
    stamp = time.time()
    service.requests.observe_hook(
        session.id, PendingHook("conv", "permission", "Bash", tool_input, stamp)
    )
    await service.get_session(session.id)
    original = service.requests.get(session.id)
    assert original is not None
    digest = hashlib.sha256(
        json.dumps(tool_input, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(
        "ccgram.session_protocol.runtime.asyncio.sleep",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    with TemporaryFile() as lock:
        runtime = ProtocolRuntime(store, service, lock)
        for _ in range(2):
            runtime.observe_hook(
                HookEvent(
                    "PermissionRequest",
                    "@1",
                    "conv",
                    {
                        "tool_name": "Bash",
                        "tool_input_hash": digest if matched else "missing",
                    },
                    stamp,
                )
            )
        assert not service.requests.is_current(session.id, original)
        with pytest.raises(asyncio.CancelledError):
            await runtime.poll("")
    assert service.requests.is_current(session.id, original) is matched
    if not matched:
        assert service.requests.get(session.id) is None


async def test_overflowed_hook_rolls_back_deferral(
    service, backend, store, tmp_path, monkeypatch
):
    """Dropped evidence must not brick the session until a restart.

    Incident 2026-11-09: a 10h source outage overflowed the hook queue
    575 times and every dropped hook left its session deferred forever,
    so plain messages hit 409 "Hook evidence awaits processing" until a
    manual bridge restart. Now the overflowed event's deferral is
    rolled back at drop time; the queued ones resolve in the drain.
    """
    path = tmp_path / "transcript.jsonl"
    path.touch()
    backend.target = replace(backend.target, transcript=path)
    session = (await service.list_sessions())[0]
    monkeypatch.setattr(
        "ccgram.session_protocol.runtime.asyncio.sleep",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    event = HookEvent(
        "PermissionRequest", "@1", "conv", {"tool_name": "Bash"}, time.time()
    )
    with TemporaryFile() as lock:
        runtime = ProtocolRuntime(store, service, lock)
        for _ in range(257):
            runtime.observe_hook(event)
        assert runtime.hooks.qsize() == 256  # the 257th was dropped
        with pytest.raises(asyncio.CancelledError):
            await runtime.poll("")
    assert not service.requests.has_deferred(session.id)


@pytest.fixture
def clock_store(monkeypatch):
    """A RequestStore whose TTL clock is a scoped fake.

    The module imports monotonic directly, so patching the module-local
    name scopes the fake to the code under test instead of freezing the
    stdlib clock for the whole event loop.
    """
    import ccgram.session_protocol.requests as requests_module
    from ccgram.session_protocol.events import EventHub

    store = requests_module.RequestStore(EventHub())
    clock = {"now": monotonic_now()}
    monkeypatch.setattr(requests_module, "monotonic", lambda: clock["now"])
    return store, clock


def monotonic_now() -> float:
    import time

    return time.monotonic()


async def test_source_outage_defers_then_ttl_expires(
    service, backend, store, tmp_path, monkeypatch, clock_store
):
    """A down source keeps queued deferrals, the TTL bounds the outage.

    While the source is unavailable the drain cannot process, so the
    deferral legitimately persists (the evidence is queued, not lost);
    once it outlives the TTL window it expires on its own instead of
    waiting for a manual bridge restart.
    """
    frozen_store, clock = clock_store
    path = tmp_path / "transcript.jsonl"
    path.touch()
    backend.target = replace(backend.target, transcript=path)
    session = (await service.list_sessions())[0]
    # re-anchor the service store onto the frozen clock
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        "ccgram.session_protocol.requests.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "ccgram.session_protocol.runtime.asyncio.sleep",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    monkeypatch.setattr(
        service.backend, "targets", AsyncMock(side_effect=OSError("down"))
    )
    event = HookEvent(
        "PermissionRequest", "@1", "conv", {"tool_name": "Bash"}, time.time()
    )
    with TemporaryFile() as lock:
        runtime = ProtocolRuntime(store, service, lock)
        runtime.observe_hook(event)
        with pytest.raises(asyncio.CancelledError):
            await runtime.poll("")
        assert service.requests.has_deferred(session.id) is True
        clock["now"] = (
            real_monotonic()
            + (
                __import__(
                    "ccgram.session_protocol.requests", fromlist=["x"]
                )._DEFERRED_TTL_S
            )
            + 1
        )
        assert service.requests.has_deferred(session.id) is False


def test_stale_deferral_expires(clock_store):
    """The TTL backstop: a deferral older than the window unblocks itself.

    Belt and braces for any lost-resolve path the rollbacks above do not
    cover: the poller drains within ~1s, so an unexpired stale deferral
    can only be leak residue, and it expires instead of persisting.
    """
    store, clock = clock_store
    import ccgram.session_protocol.requests as requests_module

    store.defer("s")
    assert store.has_deferred("s") is True
    clock["now"] += requests_module._DEFERRED_TTL_S + 1
    assert store.has_deferred("s") is False
    assert "s" not in store._deferred


def test_stranded_residue_expires_once_traffic_stops(clock_store):
    """A stranded reservation cannot outlive the traffic around it.

    Code review reproduced an aggregate-stamp design where one lost
    reservation plus 5s hook traffic kept the session 409-blocked at
    t+1000s. With per-reservation stamps the mid-flow deferral is
    legitimate (real evidence is in flight at the gate's granularity);
    the binding contract is what happens when the flow stops: the
    residue ages from ITS OWN last push and expires within the TTL,
    instead of surviving on a stamp refreshed by unrelated traffic.
    """
    store, clock = clock_store
    import ccgram.session_protocol.requests as requests_module

    store.defer("s")  # the reservation whose resolve is lost
    for _ in range(200):
        clock["now"] += 5.0
        store.defer("s")
        store.resolve("s")  # steady traffic, balanced each cycle
    clock["now"] += requests_module._DEFERRED_TTL_S + 1
    assert store.has_deferred("s") is False
    assert "s" not in store._deferred


def test_resolve_after_ttl_expiry_is_a_noop(clock_store):
    """Resolving a reservation whose entry already expired must not raise.

    The hook queue can still hold events reserving a deferral that the
    TTL has already popped; resolve is their balance point and runs
    outside the drain's inner except, so a KeyError there would kill the
    poll task (task-65).
    """
    store, clock = clock_store
    import ccgram.session_protocol.requests as requests_module

    store.defer("s")
    clock["now"] += requests_module._DEFERRED_TTL_S + 1
    assert store.has_deferred("s") is False
    store.resolve("s")  # the queued reservation balances against nothing
    assert "s" not in store._deferred


async def test_transient_flap_preserves_queued_tail(
    service, backend, store, tmp_path, monkeypatch
):
    """A transient observe failure must requeue the event, not drop it.

    Code review: the blanket drain guard consumed every remaining queued
    event on the first flap, destroying up to 256 evidence hooks. The
    per-event arm keeps draining for data errors only; a source flap
    puts the event back and retries next cycle, with the deferral held.
    """
    path = tmp_path / "transcript.jsonl"
    path.touch()
    backend.target = replace(backend.target, transcript=path)
    session = (await service.list_sessions())[0]
    monkeypatch.setattr(
        "ccgram.session_protocol.runtime.asyncio.sleep",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    event = HookEvent(
        "PermissionRequest", "@1", "conv", {"tool_name": "Bash"}, time.time()
    )
    with TemporaryFile() as lock:
        runtime = ProtocolRuntime(store, service, lock)
        runtime.observe_hook(event)
        flapped = {"done": False}
        real_observe = service.observe_hook

        async def flap_once(event, prefix):
            if not flapped["done"]:
                flapped["done"] = True
                raise ProtocolError(503, "backend_unavailable", "flap")
            return await real_observe(event, prefix)

        monkeypatch.setattr(service, "observe_hook", flap_once)
        with pytest.raises(asyncio.CancelledError):
            await runtime.poll("")
        # The event went back to the queue and its deferral is held.
        assert runtime.hooks.qsize() == 1
        assert service.requests.has_deferred(session.id) is True
