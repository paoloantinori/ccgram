"""Reaction-triggered custom actions (TASK-7): hermes-style plugins.

A reaction on a bot-sent content message can trigger a configurable
action: a screenshot of the window that produced the message, a
text-to-speech rendering of the message posted back as a voice note, or
any toolbar key/text action. The emoji -> action mapping lives in the
same ``~/.ccgram/toolbar.toml`` as a ``[reactions]`` table, so custom
integrations have one config surface.

Inert by default: no ``[reactions]`` table means the handler subscribes
to nothing and does nothing.
"""

from __future__ import annotations

import io
import asyncio
import time
from collections import OrderedDict
from typing import NamedTuple
from typing import TYPE_CHECKING

import structlog
from telegram import Update
from telegram.error import TelegramError

from ..config import config as app_config
from ..telegram_client import PTBTelegramClient
from ..tts import TtsAudio, TtsSynthesisError, get_synthesizer
from ..tts.openai import _RATE_LIMITED_STATUS as _RATE_LIMITED
from ..tts.openai import OpenAITtsSynthesizer
from ..multiplexer import multiplexer as tmux_manager
from ..screenshot import text_to_image
from .messaging_pipeline.message_sender import rate_limit_send_message, send_kwargs
from .toolbar.toolbar_keyboard import get_toolbar_config

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = structlog.get_logger()

# Bounded LRU: only recent bot messages are reaction-triggerable, with
# their text and topic (the Bot API's reaction update carries neither).
_MAX_TRACKED = 500
_TRACK_TTL_SECONDS = 3600.0


class _TrackedEntry(NamedTuple):
    window_id: str
    ts: float
    text: str
    thread_id: int | None


_tracked: OrderedDict[tuple[int, int], _TrackedEntry] = OrderedDict()


def track_sent_message(
    chat_id: int,
    message_id: int,
    window_id: str,
    text: str = "",
    thread_id: int | None = None,
) -> None:
    """Record a bot-sent content message as reaction-triggerable."""
    key = (chat_id, message_id)
    _tracked[key] = _TrackedEntry(window_id, time.monotonic(), text[:2000], thread_id)
    _tracked.move_to_end(key)
    while len(_tracked) > _MAX_TRACKED:
        _tracked.popitem(last=False)


def _lookup(chat_id: int, message_id: int) -> _TrackedEntry | None:
    """Return the tracked entry for a message, or None."""
    key = (chat_id, message_id)
    entry = _tracked.get(key)
    if entry is None:
        return None
    if time.monotonic() - entry[1] > _TRACK_TTL_SECONDS:
        _tracked.pop(key, None)
        return None
    return entry


def _reaction_emojis(mr) -> set[str]:
    """Emoji newly ADDED by this update (delta, not the full set).

    Premium users can hold several reactions at once: adding a second
    emoji must not re-fire the action attached to one already set.
    """
    if mr is None:
        return set()
    new = {getattr(r, "emoji", None) for r in (mr.new_reaction or ())}
    old = {getattr(r, "emoji", None) for r in (mr.old_reaction or ())}
    return {e for e in new - old if isinstance(e, str)}


async def handle_reaction_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Dispatch reaction-triggered actions for tracked bot messages.

    The handler is subscribed unconditionally; inertness is an early
    return (cheap in-memory guards first, cached config only after).
    """
    mr = update.message_reaction
    if mr is None or mr.user is None:
        return
    if not app_config.is_user_allowed(mr.user.id):
        return
    tracked = _lookup(mr.chat.id, mr.message_id)
    if tracked is None:
        return
    reaction_map = get_toolbar_config().reaction_map
    if not reaction_map:
        return  # feature off
    resolved = _resolve_action(reaction_map, mr)
    if resolved is None:
        return
    emoji, action = resolved
    window_id, _ts, message_text, thread_id = tracked
    logger.info(
        "reaction trigger",
        emoji=emoji,
        action=action,
        window_id=window_id,
        chat_id=mr.chat.id,
    )
    client = _client(context)
    try:
        if action == "screenshot":
            await _action_screenshot(client, mr.chat.id, window_id, thread_id)
        elif action == "speak":
            await _action_speak(client, mr.chat.id, message_text, thread_id)
        else:
            await _action_toolbar(client, mr.chat.id, window_id, action, thread_id)
    except TelegramError as exc:
        logger.warning("reaction action failed", action=action, error=str(exc))


def _resolve_action(reaction_map: dict[str, str], mr) -> tuple[str, str] | None:
    """First mapped (emoji, action) among the newly added reactions."""
    for emoji in sorted(_reaction_emojis(mr)):
        name = reaction_map.get(emoji)
        if name:
            return emoji, name
    return None


def _client(context: ContextTypes.DEFAULT_TYPE):
    return PTBTelegramClient(context.bot)


async def _action_screenshot(
    client, chat_id: int, window_id: str, thread_id: int | None = None
) -> None:
    """Render the window's pane and post the PNG in the same topic."""
    pane_text = await tmux_manager.capture_pane(window_id, with_ansi=True)
    if not pane_text:
        await rate_limit_send_message(
            client, chat_id, "⚠️ nothing to capture", **send_kwargs(thread_id)
        )
        return
    image_bytes = await text_to_image(pane_text)
    await client.send_document(
        chat_id=chat_id,
        document=image_bytes,
        filename="screenshot.png",
        **send_kwargs(thread_id),
    )


async def _clear_progress(client, chat_id: int, progress) -> None:
    """Delete the synthesizing indicator once the outcome is known."""
    if progress is None:
        return
    try:
        await client.delete_message(chat_id=chat_id, message_id=progress.message_id)
    except TelegramError as exc:
        logger.debug("could not clear progress message", error=str(exc))


async def _action_speak(
    client, chat_id: int, message_text: str, thread_id: int | None = None
) -> None:
    """Render the reacted message's text to speech; post a voice note.

    Reuses the tts seam: the globally configured synthesizer
    (CCGRAM_TTS_*) when set, else the LAN OpenAI-compatible endpoint
    from ``[reactions.speak] url`` (model/voice/api_key options
    optional). Delivery matches the queue's TTS voice path.
    """
    speak_cfg = get_toolbar_config().reaction_speak
    url = speak_cfg.get("url", "")
    timeout = float(speak_cfg.get("timeout", "240"))
    progress = await rate_limit_send_message(
        client, chat_id, "🔊 synthesizing…", **send_kwargs(thread_id)
    )

    def _synth(model: str) -> OpenAITtsSynthesizer:
        # The key falls back to the whisper env var: same LAN service, one
        # credential to keep current instead of two copies drifting apart.
        api_key = speak_cfg.get("api_key", "") or app_config.whisper_api_key
        return OpenAITtsSynthesizer(
            api_key=api_key,
            model=model,
            voice=speak_cfg.get("voice", "alloy"),
            base_url=url,
            response_format=speak_cfg.get("response_format", "opus"),
            # LAN engines can cold-start the model on the first request
            # after idle (30-90s observed); give them room.
            timeout=timeout,
        )

    try:
        audio: TtsAudio | None = None
        if url:
            primary = speak_cfg.get("model", "tts-1")
            fallback = speak_cfg.get("fallback_model", "")
            try:
                audio = await _synth(primary).synthesize(message_text)
            except TtsSynthesisError as exc:
                retryable = "Timeout" in str(exc) or exc.status_code == _RATE_LIMITED
                if not fallback or not retryable:
                    raise
                # Cold start: the first attempt often pays the model load.
                # Rate limit: the backend sent Retry-After; honor it before
                # the retry. The fallback model is fast and lower quality,
                # and it loses the cloned voice (preset fallback); the
                # alternative is delivering nothing.
                if exc.retry_after:
                    await asyncio.sleep(min(exc.retry_after, 30.0))
                logger.warning(
                    "speak retry on fallback model",
                    primary=primary,
                    fallback=fallback,
                    error=str(exc),
                )
                audio = await _synth(fallback).synthesize(message_text)
        else:
            synth = get_synthesizer()
            audio = await synth.synthesize(message_text) if synth else None
    except (TtsSynthesisError, ValueError) as exc:
        # The exception message already carries its context ("TTS failed:
        # ..."); prefixing again produced "TTS failed: TTS failed:".
        logger.warning("speak action failed", error=str(exc))
        await _clear_progress(client, chat_id, progress)
        await rate_limit_send_message(
            client, chat_id, f"⚠️ {exc}", **send_kwargs(thread_id)
        )
        return
    await _clear_progress(client, chat_id, progress)
    if audio is None:
        await rate_limit_send_message(
            client,
            chat_id,
            "⚠️ no TTS configured (CCGRAM_TTS_* or [reactions.speak] url)",
            **send_kwargs(thread_id),
        )
        return
    voice = io.BytesIO(audio.data)
    voice.name = audio.filename
    await client.send_voice(chat_id=chat_id, voice=voice, **send_kwargs(thread_id))


async def _action_toolbar(
    client,
    chat_id: int,
    window_id: str,
    action_name: str,
    thread_id: int | None = None,
) -> None:
    """Run a toolbar key/text action by name.

    Actions typed ``builtin`` are rejected: their handlers need a
    CallbackQuery; map reactions to ``screenshot``/``speak`` instead.
    """
    action = get_toolbar_config().actions.get(action_name)
    if action is None or action.action_type not in ("key", "text"):
        await rate_limit_send_message(
            client,
            chat_id,
            f"⚠️ reaction action '{action_name}' not found or not key/text",
            **send_kwargs(thread_id),
        )
        return
    enter = action.action_type == "text"
    ok = await tmux_manager.send_keys(
        window_id, action.payload, enter=enter, literal=action.literal or enter
    )
    if not ok:
        await rate_limit_send_message(
            client, chat_id, "⚠️ window not found", **send_kwargs(thread_id)
        )
