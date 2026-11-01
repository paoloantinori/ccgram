"""The retained-legacy-key warning fires once, not per sync cycle."""

from structlog.testing import capture_logs

from ccgram import utils as ccgram_utils
from ccgram.session_map import SessionMapSync
from ccgram.thread_router import ThreadRouter, install_thread_router
from ccgram.window_state_store import WindowStateStore, install_window_store


def _wire_sync() -> SessionMapSync:
    install_window_store(
        WindowStateStore(
            schedule_save=lambda: None,
            on_hookless_provider_switch=lambda _wid: None,
        )
    )
    install_thread_router(
        ThreadRouter(schedule_save=lambda: None, has_window_state=lambda _wid: True)
    )
    return SessionMapSync(schedule_save=lambda: None)


async def test_retained_key_warning_fires_once_per_window(
    tmp_path, monkeypatch
) -> None:
    """The monitor re-syncs the map every cycle; the warning must not repeat.

    Measured on the Mac bridge after a reboot: 5 warnings per second for
    hours because every sync re-logged the full retained set. The throttle
    suppresses the immediate repeat; the periodic sweep bounds a suppressed
    entry's life, so the warning resurfaces eventually without a reset.
    """
    from ccgram.config import config

    monkeypatch.setattr(config, "multiplexer_name", "herdr", raising=False)
    ccgram_utils._throttle_state.clear()
    sync = _wire_sync()
    raw = {
        "herdr:w7:t1": {
            "session_id": "s-legacy",
            "cwd": "/repo",
            "window_name": "repo",
            "transcript_path": str(tmp_path / "t.jsonl"),
            "provider_name": "claude",
        }
    }

    with capture_logs() as logs:
        await sync.load_session_map(raw)
        await sync.load_session_map(raw)
        await sync.load_session_map(raw)

    retained = [
        e for e in logs if "Retaining unrecognized session_map key" in e["event"]
    ]
    assert len(retained) == 1, retained
    assert "herdr:w7:t1" in retained[0]["event"]
    ccgram_utils._throttle_state.clear()
