"""Raw-bot sends leave the same delivery audit as adapter sends.

Tool-batch messages are created once by DraftStream's legacy start and
then live on edits, and the shutdown banner sends through the raw
application bot: none of those passed the audited adapter, so a lost
tool-batch or banner message stayed indistinguishable from an unobserved
one (task-59, the residual blind spot of the 2026-10-19 incident class).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from structlog.testing import capture_logs

from ccgram.telegram_draft import DraftStream

from .conftest import _bot_returning


async def test_legacy_draft_start_is_audited():
    bot = _bot_returning(501)

    with capture_logs() as logs:
        draft = DraftStream(
            bot, -1004294176884, message_thread_id=38378, force_legacy=True
        )
        await draft.start("tool batch text")

    entry = [e for e in logs if e.get("event") == "telegram send ok"][0]
    assert entry["kind"] == "draft"
    assert entry["chat_id"] == -1004294176884
    assert entry["thread_id"] == 38378
    assert entry["message_id"] == 501


async def test_draft_final_send_is_audited():
    bot = _bot_returning(502)
    draft = DraftStream(bot, -100, message_thread_id=7, force_legacy=True)

    with capture_logs() as logs:
        await draft._send_final_message()

    entry = [e for e in logs if e.get("event") == "telegram send ok"][0]
    assert entry["kind"] == "draft"
    assert entry["thread_id"] == 7
    assert entry["message_id"] == 502


async def test_shutdown_banner_is_audited():
    from ccgram.bot import _send_shutdown_notification

    application = MagicMock()
    application.bot = _bot_returning(503)

    with (
        capture_logs() as logs,
        patch("ccgram.bot.config") as config,
        patch("ccgram.main._shutdown_signal", new=None),
    ):
        config.group_id = -1004294176884
        await _send_shutdown_notification(application)

    entry = [e for e in logs if e.get("event") == "telegram send ok"][0]
    assert entry["kind"] == "banner"
    assert entry["message_id"] == 503
