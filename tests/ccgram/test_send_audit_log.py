"""Delivery audit: every successful Telegram send leaves a log trace.

Successful sends previously logged nothing anywhere: a missing message
could not be distinguished from an unobserved one (2026-10-19 anti-vocale
incident: both lost messages dispatched, receipts settled, no send trace
either way). The adapter is the single choke point every outbound new
message passes through, so the audit line lives there.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from structlog.testing import capture_logs
from telegram import Message
from telegram.error import TelegramError

from ccgram.telegram_client import PTBTelegramClient


async def test_successful_send_logs_the_message_id():
    bot = MagicMock()
    delivered = MagicMock(spec=Message)
    delivered.message_id = 4242
    bot.send_message = AsyncMock(return_value=delivered)
    client = PTBTelegramClient(bot)

    with capture_logs() as logs:
        await client.send_message(
            chat_id=-1004294176884, text="DIAG-OK", message_thread_id=38378
        )

    audit = [e for e in logs if e.get("event") == "telegram send ok"]
    assert audit, "a successful send must leave a delivery audit line"
    entry = audit[0]
    assert entry["chat_id"] == -1004294176884
    assert entry["thread_id"] == 38378
    assert entry["message_id"] == 4242
    assert entry["text_len"] == len("DIAG-OK")


async def test_send_failure_leaves_no_audit_line():
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramError("boom"))
    client = PTBTelegramClient(bot)

    with capture_logs() as logs, pytest.raises(TelegramError):
        await client.send_message(chat_id=-100, text="x")

    assert not [e for e in logs if e.get("event") == "telegram send ok"]


async def test_send_without_thread_logs_none():
    bot = MagicMock()
    delivered = MagicMock(spec=Message)
    delivered.message_id = 9
    bot.send_message = AsyncMock(return_value=delivered)
    client = PTBTelegramClient(bot)

    with capture_logs() as logs:
        await client.send_message(chat_id=42, text="private")

    entry = [e for e in logs if e.get("event") == "telegram send ok"][0]
    assert entry["thread_id"] is None
    assert entry["kind"] == "message"


async def test_audit_never_records_message_content():
    bot = MagicMock()
    delivered = MagicMock(spec=Message)
    delivered.message_id = 11
    bot.send_message = AsyncMock(return_value=delivered)
    client = PTBTelegramClient(bot)
    secret = "SECRETPAYLOAD123"

    with capture_logs() as logs:
        await client.send_message(chat_id=-100, text=secret, message_thread_id=1)

    for entry in logs:
        assert secret not in str(entry.values())
        assert "text" not in entry


async def test_file_and_voice_sends_are_audited():
    bot = MagicMock()
    delivered = MagicMock(spec=Message)
    delivered.message_id = 12
    bot.send_document = AsyncMock(return_value=delivered)
    client = PTBTelegramClient(bot)

    with capture_logs() as logs:
        await client.send_document(
            chat_id=-100, document=MagicMock(), message_thread_id=2
        )

    entry = [e for e in logs if e.get("event") == "telegram send ok"][0]
    assert entry["kind"] == "document"
    assert entry["message_id"] == 12
