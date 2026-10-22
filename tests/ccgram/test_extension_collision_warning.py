"""The seam warns when an extension shadows a built-in command.

Extension handlers register BEFORE the built-ins (task-56), so a
CommandHandler using a built-in name silently kills the core handler for
every chat: same silent-shadowing family as the three lost-fork-code
incidents. The seam cannot reject (extensions are the maintainer's own
and may deliberately override), but it must say so.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from structlog.testing import capture_logs
from telegram.ext import CommandHandler, MessageHandler
from telegram.ext import filters

from ccgram.extensions import ExtensionApi


def _api() -> ExtensionApi:
    return ExtensionApi(add_handler=MagicMock(), name="test-ext")


async def _noop(update, context):
    return None


def _shadow_warnings(logs) -> list:
    return [
        e
        for e in logs
        if "extension shadows the built-in command" in e.get("event", "")
    ]


def test_colliding_command_name_logs_a_warning():
    api = _api()
    with capture_logs() as logs:
        api.register_ptb_handler(CommandHandler("send", _noop), "message")

    warnings = _shadow_warnings(logs)
    assert warnings, "a colliding registration must be called out"
    entry = warnings[0]
    assert entry["command"] == "send"
    assert entry["extension"] == "test-ext"


def test_free_command_name_stays_silent():
    api = _api()
    with capture_logs() as logs:
        api.register_ptb_handler(CommandHandler("names", _noop), "message")

    assert not _shadow_warnings(logs)


def test_non_command_handler_stays_silent():
    api = _api()

    with capture_logs() as logs:
        api.register_ptb_handler(MessageHandler(filters.COMMAND, _noop), "message")

    assert not _shadow_warnings(logs)


def test_group0_callback_handler_logs_a_warning():
    from telegram.ext import CallbackQueryHandler

    api = _api()
    with capture_logs() as logs:
        api.register_ptb_handler(CallbackQueryHandler(_noop), "callback_query")

    takeover = [
        e for e in logs if "group-0 callback-query handler" in e.get("event", "")
    ]
    assert takeover, "a total callback takeover must be called out"
    assert takeover[0]["extension"] == "test-ext"


def test_multi_command_handler_warns_per_matching_name():
    api = _api()
    with capture_logs() as logs:
        api.register_ptb_handler(CommandHandler(["send", "names"], _noop), "message")

    warned = {e["command"] for e in _shadow_warnings(logs)}
    assert warned == {"send"}
