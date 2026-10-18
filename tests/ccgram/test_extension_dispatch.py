"""Extension commands must outrank the forward catch-all in PTB dispatch.

PTB runs at most one handler per group: the first registered whose filters
match claims the update. ``create_bot`` must therefore register extension
handlers BEFORE ``register_all`` installs the command-forwarding catch-all,
or every extension command (/names, /icons) is forwarded to the agent and
comes back as "Unknown command". Live regression: the 2026-10-04 seam
restoration reordered the two calls; /names apply in a group-filtered topic
failed on 2026-10-18.

The app harness mirrors tests/integration/conftest.py's make_ptb_app (real
Application, ``_do_post`` stubbed so getMe never leaves the process); the
factory itself is not reused because its conftest is scoped to the
integration suite, and this regression belongs to the default battery the
deploy contract runs.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Chat, Message, MessageEntity, Update, User
from telegram.ext import CommandHandler, filters

from ccgram import bot as bot_module, extensions

FAKE_COMMAND = "names"

_GET_ME_RESPONSE = {
    "id": 1,
    "first_name": "Bot",
    "is_bot": True,
    "username": "testbot",
}


@pytest.fixture()
async def dispatch_app(monkeypatch):
    """(application, extension_command, forward) from a real create_bot.

    The entry-point scan is patched before the build so a fake /names
    extension rides the real seam; filters.ALL makes the forward catch-all
    match any command, the worst case for extension precedence. The forward
    catch-all is mocked at the registry's import site BEFORE registration
    (what registry wires is its own reference), and the transport is
    stubbed so initialization needs no network.
    """
    fake_command = AsyncMock(name="extension_command")
    forward = AsyncMock(name="forward")

    def register(api) -> None:
        api.register_ptb_handler(CommandHandler(FAKE_COMMAND, fake_command), "message")

    class _EP:
        name = "fake-names"

        @staticmethod
        def load():
            return register

    monkeypatch.setattr(
        "ccgram.extensions.entry_points",
        lambda group=None: [_EP()],
    )
    monkeypatch.setattr("ccgram.handlers.registry.forward_command_handler", forward)
    monkeypatch.setattr(bot_module, "_group_filter", filters.ALL)
    application = bot_module.create_bot()

    try:
        async with AsyncExitStack() as stack:
            stack.enter_context(
                patch.object(
                    type(application.bot),
                    "_do_post",
                    AsyncMock(return_value=_GET_ME_RESPONSE),
                )
            )
            await stack.enter_async_context(application)
            yield application, fake_command, forward
    finally:
        extensions.reset_for_testing()


def _command_update(bot, text: str) -> Update:
    """A command Update with the bot_command entity PTB requires."""
    name = text.split()[0]
    message = Message(
        1,
        datetime.now(UTC),
        Chat(-100123, "supergroup"),
        from_user=User(42, "u", False),
        text=text,
        message_thread_id=7,
        entities=[MessageEntity("bot_command", 0, len(name))],
    )
    message.set_bot(bot)
    return Update(1, message=message)


async def test_extension_command_outranks_the_forward_catch_all(dispatch_app):
    application, fake_command, forward = dispatch_app
    update = _command_update(application.bot, f"/{FAKE_COMMAND} apply")

    await application.process_update(update)

    fake_command.assert_awaited_once()
    forward.assert_not_awaited()


async def test_unknown_command_still_reaches_the_forward_catch_all(dispatch_app):
    application, fake_command, forward = dispatch_app
    update = _command_update(application.bot, "/definitelyunknown")

    await application.process_update(update)

    forward.assert_awaited_once()
    fake_command.assert_not_awaited()
