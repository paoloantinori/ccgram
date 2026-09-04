"""Extension seam loader tests (docs/extension-seam.md)."""

from __future__ import annotations

import asyncio

import pytest

from ccgram import extensions as ext


@pytest.fixture(autouse=True)
def _reset():
    ext.reset_for_testing()
    yield
    ext.reset_for_testing()


class _FakeEp:
    def __init__(self, name, obj, broken=False):
        self.name = name
        self._obj = obj
        self._broken = broken

    def load(self):
        if self._broken:
            raise RuntimeError("boom")
        return self._obj


class TestLoad:
    def test_registers_handler_update_type_and_listeners(self):
        added = []
        seen = {}

        def register(api):
            api.register_ptb_handler("HANDLER", "message_reaction")
            api.on("message.delivered", seen.setdefault)
            api.on("message.delivered", lambda **kw: seen.update(kw))

        def fake_eps(group):
            assert group == ext.ENTRY_POINT_GROUP
            return [_FakeEp("ext1", register)]

        orig = ext.entry_points
        ext.entry_points = fake_eps
        try:
            assert ext.load_extensions(added.append) == 1
        finally:
            ext.entry_points = orig
        assert added == ["HANDLER"]
        assert ext.resolved_allowed_updates(["message"]) == [
            "message",
            "message_reaction",
        ]
        # Duplicate claims (e.g. "message" for a CommandHandler) dedup.
        ext._registered_update_types.add("message")
        assert ext.resolved_allowed_updates(["message", "callback_query"]) == [
            "message",
            "callback_query",
            "message_reaction",
        ]

    def test_broken_extension_isolated(self):
        def fake_eps(group):
            return [_FakeEp("bad", None, broken=True)]

        orig = ext.entry_points
        ext.entry_points = fake_eps
        try:
            assert ext.load_extensions(lambda h: None) == 0
        finally:
            ext.entry_points = orig


class TestEmit:
    def test_sync_listener_receives_payload(self):
        got = {}
        ext._listeners["message.delivered"] = [lambda **kw: got.update(kw)]
        ext.emit("message.delivered", chat_id=1, message_id=2)
        assert got == {"chat_id": 1, "message_id": 2}

    async def test_async_listener_scheduled(self):
        got = []

        async def listener(**kw):
            got.append(kw["message_id"])

        ext._listeners["e"] = [listener]
        ext.emit("e", message_id=5)
        await asyncio.sleep(0)
        assert got == [5]

    async def test_raising_listener_does_not_block(self):
        got = []

        def bad(**kw):
            raise ValueError("nope")

        ext._listeners["e"] = [bad, lambda **kw: got.append(True)]
        ext.emit("e")
        await asyncio.sleep(0)
        assert got == [True]

    def test_no_listeners_noop(self):
        ext.emit("nobody.home", anything=1)
