"""Extension loader: the zero-extension warning is the dropped-ext alarm."""

import logging

from ccgram import extensions


def test_load_extensions_warns_when_none_installed(caplog):
    with caplog.at_level(logging.WARNING, logger="ccgram.extensions"):
        count = extensions.load_extensions(lambda _handler: None)
    if count == 0:
        assert any("no extensions loaded" in r.message for r in caplog.records)
    else:
        assert not any("no extensions loaded" in r.message for r in caplog.records)


def test_load_extensions_returns_nonnegative_count():
    assert extensions.load_extensions(lambda _handler: None) >= 0
