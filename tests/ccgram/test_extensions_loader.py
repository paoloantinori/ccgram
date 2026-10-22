"""Extension loader: the zero-extension warning is the dropped-ext alarm."""

from structlog.testing import capture_logs

from ccgram import extensions


def test_load_extensions_warns_when_none_installed():
    with capture_logs() as logs:
        count = extensions.load_extensions(lambda _handler: None)
    warned = [e for e in logs if "no extensions loaded" in str(e.get("event", ""))]
    if count == 0:
        assert warned
    else:
        assert not warned


def test_load_extensions_returns_nonnegative_count():
    assert extensions.load_extensions(lambda _handler: None) >= 0
