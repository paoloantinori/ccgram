from __future__ import annotations

from unittest.mock import patch


def _router(calls: dict[str, str | None]) -> object:
    class _Router:
        def resolve_window_for_thread(self, user_id, thread_id, chat_id=None):
            key = f"{user_id}:{thread_id}:{chat_id}"
            return calls.get(key)

    return _Router()


def test_binding_matches_window_accepts_the_chat_scoped_binding() -> None:
    from ccgram.session_query import binding_matches_window

    router = _router({"7:4:99": "@0"})
    with (
        patch("ccgram.thread_router.thread_router", router),
        patch("ccgram.window_resolver.resolve_window_alias", side_effect=lambda w: w),
    ):
        assert binding_matches_window(7, 4, 99, "@0") is True


def test_binding_matches_window_accepts_a_legacy_chat_less_binding() -> None:
    from ccgram.session_query import binding_matches_window

    router = _router({"7:4:None": "@0"})
    with (
        patch("ccgram.thread_router.thread_router", router),
        patch("ccgram.window_resolver.resolve_window_alias", side_effect=lambda w: w),
    ):
        assert binding_matches_window(7, 4, 99, "@0") is True


def test_binding_matches_window_converges_the_armed_id_through_aliases() -> None:
    from ccgram.session_query import binding_matches_window

    router = _router({"7:4:99": "@0"})
    with (
        patch("ccgram.thread_router.thread_router", router),
        patch(
            "ccgram.window_resolver.resolve_window_alias",
            side_effect={"@old": "@0"}.get,
        ),
    ):
        assert binding_matches_window(7, 4, 99, "@old") is True


def test_binding_matches_window_rejects_a_foreign_window() -> None:
    from ccgram.session_query import binding_matches_window

    router = _router({"7:4:99": "@1", "7:4:None": "@2"})
    with (
        patch("ccgram.thread_router.thread_router", router),
        patch("ccgram.window_resolver.resolve_window_alias", side_effect=lambda w: w),
    ):
        assert binding_matches_window(7, 4, 99, "@0") is False
