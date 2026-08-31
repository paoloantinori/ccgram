"""Reaction-triggered custom actions (TASK-7)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ccgram.handlers import reactions_trigger as rt
from ccgram.toolbar_config import load_toolbar_config

MOD = "ccgram.handlers.reactions_trigger"


@pytest.fixture(autouse=True)
def _clean_tracked():
    rt._tracked.clear()
    yield
    rt._tracked.clear()


def _update(
    emoji: str, chat_id: int = -100, message_id: int = 7, user_id: int = 1
) -> MagicMock:
    reaction = MagicMock()
    reaction.emoji = emoji
    mr = MagicMock()
    mr.chat.id = chat_id
    mr.message_id = message_id
    user = MagicMock()
    user.id = user_id
    mr.user = user
    mr.new_reaction = [reaction]
    upd = MagicMock()
    upd.message_reaction = mr
    return upd


class TestTracking:
    def test_track_and_lookup_roundtrip(self) -> None:
        rt.track_sent_message(-100, 7, "@0", "hello world", thread_id=42)
        entry = rt._lookup(-100, 7)
        assert entry is not None
        assert entry[0] == "@0" and entry[2] == "hello world" and entry[3] == 42

    def test_unknown_message_returns_none(self) -> None:
        assert rt._lookup(-100, 999) is None

    def test_bounded_lru(self) -> None:
        for i in range(rt._MAX_TRACKED + 10):
            rt.track_sent_message(-100, i, "@0", "t")
        assert len(rt._tracked) == rt._MAX_TRACKED


class TestConfig:
    def test_reactions_section_parsed(self, tmp_path) -> None:
        toml = tmp_path / "toolbar.toml"
        toml.write_text(
            "[reactions]\n"
            '"\U0001f4f8" = "screenshot"\n'
            '"\U0001f50a" = "speak"\n'
            "[reactions.speak]\n"
            'url = "http://tts.lan/speak"\n'
        )
        cfg = load_toolbar_config(toml)
        assert cfg.reaction_map["\U0001f4f8"] == "screenshot"
        assert cfg.reaction_map["\U0001f50a"] == "speak"
        assert cfg.reaction_speak["url"] == "http://tts.lan/speak"

    def test_no_section_means_off(self, tmp_path) -> None:
        toml = tmp_path / "toolbar.toml"
        toml.write_text('[actions.custom]\ntype = "key"\npayload = "C-c"\n')
        cfg = load_toolbar_config(toml)
        assert cfg.reaction_map == {}

    def test_unknown_action_rejected(self, tmp_path) -> None:
        toml = tmp_path / "toolbar.toml"
        toml.write_text('[reactions]\n"\U0001f44d" = "nope"\n')
        cfg = load_toolbar_config(toml)
        assert cfg.reaction_map == {}


class TestDispatch:
    async def test_mapped_reaction_runs_action(self) -> None:
        rt.track_sent_message(-100, 7, "@0", "the text")
        cfg = MagicMock()
        cfg.reaction_map = {"\U0001f4f8": "screenshot"}
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.app_config") as appcfg,
            patch(f"{MOD}._action_screenshot", new=AsyncMock()) as shot,
            patch(f"{MOD}._client"),
        ):
            appcfg.is_user_allowed.return_value = True
            await rt.handle_reaction_update(_update("\U0001f4f8"), MagicMock())
        shot.assert_awaited_once()

    async def test_unmapped_reaction_ignored(self) -> None:
        rt.track_sent_message(-100, 7, "@0", "t")
        cfg = MagicMock()
        cfg.reaction_map = {"\U0001f4f8": "screenshot"}
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.app_config") as appcfg,
            patch(f"{MOD}._action_screenshot", new=AsyncMock()) as shot,
        ):
            appcfg.is_user_allowed.return_value = True
            await rt.handle_reaction_update(_update("\U0001f44d"), MagicMock())
        shot.assert_not_awaited()

    async def test_feature_off_without_mapping(self) -> None:
        cfg = MagicMock()
        cfg.reaction_map = {}
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.app_config") as appcfg,
            patch(f"{MOD}._action_screenshot", new=AsyncMock()) as shot,
        ):
            appcfg.is_user_allowed.return_value = True
            rt.track_sent_message(-100, 7, "@0", "t", thread_id=1)
            await rt.handle_reaction_update(_update("\U0001f4f8"), MagicMock())
        shot.assert_not_awaited()

    async def test_speak_posts_voice(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {"url": "http://tts.lan/v1"}
        client = MagicMock()
        client.send_voice = AsyncMock()
        client.delete_message = AsyncMock()
        prog = MagicMock()
        prog.message_id = 3
        audio = MagicMock()
        audio.data = b"OGG"
        audio.filename = "reply.mp3"
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.OpenAITtsSynthesizer") as synth_cls,
            patch(f"{MOD}.rate_limit_send_message", new=AsyncMock(return_value=prog)),
            patch.object(rt, "_clear_progress", new=AsyncMock()),
        ):
            synth_cls.return_value.synthesize = AsyncMock(return_value=audio)
            await rt._action_speak(client, -100, "ciao", thread_id=42)
        synth_cls.assert_called_once_with(
            api_key="",
            model="tts-1",
            voice="alloy",
            base_url="http://tts.lan/v1",
            response_format="opus",
            timeout=240.0,
        )
        client.send_voice.assert_awaited_once()
        assert client.send_voice.await_args.kwargs["message_thread_id"] == 42

    async def test_speak_without_any_config_warns(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {}
        client = MagicMock()
        client.send_message = AsyncMock()
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.get_synthesizer", return_value=None),
            patch(f"{MOD}.rate_limit_send_message", new=AsyncMock()) as warn,
            patch.object(rt, "_clear_progress", new=AsyncMock()),
        ):
            await rt._action_speak(client, -100, "ciao")
        assert warn.await_count >= 1
        assert any("no TTS configured" in str(c.args[2]) for c in warn.await_args_list)


class TestScreenshotAction:
    async def test_screenshot_renders_and_sends(self) -> None:
        client = MagicMock()
        client.send_document = AsyncMock()
        mux = MagicMock()
        mux.capture_pane = AsyncMock(return_value="pane")
        with (
            patch(f"{MOD}.tmux_manager", mux),
            patch(f"{MOD}.text_to_image", new=AsyncMock(return_value=b"PNG")),
        ):
            await rt._action_screenshot(client, -100, "@0")
        mux.capture_pane.assert_awaited_once_with("@0", with_ansi=True)
        client.send_document.assert_awaited_once()
        kwargs = client.send_document.await_args.kwargs
        assert kwargs["document"] == b"PNG"


class TestDeltaResolution:
    def test_only_newly_added_emoji_fires(self) -> None:
        mr = MagicMock()
        kept = MagicMock()
        kept.emoji = "🍓"
        added = MagicMock()
        added.emoji = "👍"
        mr.new_reaction = [kept, added]
        mr.old_reaction = [kept]
        assert rt._reaction_emojis(mr) == {"👍"}

    def test_premium_second_reaction_does_not_refire(self) -> None:
        # The mapped 🍓 was already set; only an unrelated 🔥 is added, so
        # the mapped emoji is not in the delta and the action must not fire.
        mr = MagicMock()
        mapped = MagicMock()
        mapped.emoji = "🍓"
        other = MagicMock()
        other.emoji = "🔥"
        mr.new_reaction = [mapped, other]
        mr.old_reaction = [mapped]
        assert "🍓" not in rt._reaction_emojis(mr)
        assert rt._reaction_emojis(mr) == {"🔥"}


class TestTtlExpiry:
    def test_expired_entry_is_dropped(self) -> None:
        rt.track_sent_message(-100, 9, "@0", "t", thread_id=1)
        key = (-100, 9)
        window_id, ts, text, thread_id = rt._tracked[key]
        rt._tracked[key] = rt._TrackedEntry(window_id, ts - 7200, text, thread_id)
        assert rt._lookup(-100, 9) is None
        assert key not in rt._tracked


class TestSpeakOptionScalars:
    def test_numeric_timeout_accepted(self, tmp_path) -> None:
        toml = tmp_path / "toolbar.toml"
        toml.write_text(
            '[reactions]\n"🔥" = "speak"\n'
            "[reactions.speak]\n"
            'url = "http://t"\ntimeout = 60\nvoice = "x"\n'
        )
        cfg = load_toolbar_config(toml)
        assert cfg.reaction_speak["timeout"] == "60"
        assert cfg.reaction_speak["voice"] == "x"


class TestSpeakRobustness:
    async def test_timeout_retries_on_fallback_model(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {
            "url": "http://tts.lan/v1",
            "model": "omnivoice",
            "fallback_model": "pockettts",
        }
        client = MagicMock()
        client.delete_message = AsyncMock()
        client.send_voice = AsyncMock()
        prog = MagicMock()
        prog.message_id = 1
        audio = MagicMock()
        audio.data = b"OGG"
        audio.filename = "reply.opus"
        slow = MagicMock()
        fast = MagicMock()
        slow.synthesize = AsyncMock(
            side_effect=rt.TtsSynthesisError("TTS failed: ReadTimeout: ")
        )
        fast.synthesize = AsyncMock(return_value=audio)
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.OpenAITtsSynthesizer", side_effect=[slow, fast]),
            patch(f"{MOD}.rate_limit_send_message", new=AsyncMock(return_value=prog)),
            patch.object(rt, "_clear_progress", new=AsyncMock()),
        ):
            await rt._action_speak(client, -100, "ciao", thread_id=42)
        fast.synthesize.assert_awaited_once()

    async def test_non_timeout_error_does_not_retry(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {
            "url": "http://t",
            "model": "omnivoice",
            "fallback_model": "pockettts",
        }
        client = MagicMock()
        client.delete_message = AsyncMock()
        client.send_voice = AsyncMock()
        synth = MagicMock()
        synth.synthesize = AsyncMock(
            side_effect=rt.TtsSynthesisError("TTS failed: 401 nope")
        )
        prog = MagicMock()
        prog.message_id = 9
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.OpenAITtsSynthesizer", return_value=synth),
            patch(f"{MOD}.rate_limit_send_message", new=AsyncMock(return_value=prog)),
            patch.object(rt, "_clear_progress", new=AsyncMock()) as clear,
        ):
            await rt._action_speak(client, -100, "ciao")
        synth.synthesize.assert_awaited_once()
        clear.assert_awaited()

    async def test_api_key_falls_back_to_whisper_env(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {"url": "http://t"}
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.app_config") as appcfg,
            patch(f"{MOD}.OpenAITtsSynthesizer") as cls,
        ):
            appcfg.whisper_api_key = "ENVKEY"
            assert rt.app_config is appcfg
            synth = cls.return_value
            audio = MagicMock()
            audio.data = b"x"
            audio.filename = "r.opus"
            synth.synthesize = AsyncMock(return_value=audio)
            client = MagicMock()
            client.delete_message = AsyncMock()
            client.send_voice = AsyncMock()
            prog = MagicMock()
            prog.message_id = 5
            with (
                patch(
                    f"{MOD}.rate_limit_send_message", new=AsyncMock(return_value=prog)
                ),
                patch.object(rt, "_clear_progress", new=AsyncMock()),
            ):
                await rt._action_speak(client, -100, "ciao")
        cls.assert_called_once()
        assert cls.call_args.kwargs["api_key"] == "ENVKEY"


class TestSpeak429Retry:
    async def test_rate_limit_with_retry_after_retries(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {
            "url": "http://t",
            "model": "omni",
            "fallback_model": "fast",
        }
        client = MagicMock()
        client.send_voice = AsyncMock()
        client.delete_message = AsyncMock()
        slow = MagicMock()
        fast = MagicMock()
        audio = MagicMock()
        audio.data = b"x"
        audio.filename = "r.opus"
        slow.synthesize = AsyncMock(
            side_effect=rt.TtsSynthesisError(
                "TTS failed: 429 too many", status_code=429, retry_after=2.0
            )
        )
        fast.synthesize = AsyncMock(return_value=audio)
        sleeps: list[float] = []
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.OpenAITtsSynthesizer", side_effect=[slow, fast]),
            patch(
                f"{MOD}.rate_limit_send_message",
                new=AsyncMock(return_value=MagicMock(message_id=1)),
            ),
            patch.object(rt, "_clear_progress", new=AsyncMock()),
            patch(
                f"{MOD}.asyncio.sleep",
                new=AsyncMock(side_effect=lambda d: sleeps.append(d) or _a_none()),
            ),
        ):
            await rt._action_speak(client, -100, "ciao")
        assert 2.0 in sleeps
        fast.synthesize.assert_awaited_once()

    async def test_server_error_does_not_retry(self) -> None:
        cfg = MagicMock()
        cfg.reaction_speak = {
            "url": "http://t",
            "model": "omni",
            "fallback_model": "fast",
        }
        client = MagicMock()
        client.send_voice = AsyncMock()
        client.delete_message = AsyncMock()
        synth = MagicMock()
        synth.synthesize = AsyncMock(
            side_effect=rt.TtsSynthesisError("TTS failed: 500 boom", status_code=500)
        )
        with (
            patch(f"{MOD}.get_toolbar_config", return_value=cfg),
            patch(f"{MOD}.OpenAITtsSynthesizer", return_value=synth),
            patch(
                f"{MOD}.rate_limit_send_message",
                new=AsyncMock(return_value=MagicMock(message_id=1)),
            ),
            patch.object(rt, "_clear_progress", new=AsyncMock()),
            patch(f"{MOD}.rate_limit_send_message"),
        ):
            await rt._action_speak(client, -100, "ciao")
        synth.synthesize.assert_awaited_once()


async def _a_none() -> None:
    return None
