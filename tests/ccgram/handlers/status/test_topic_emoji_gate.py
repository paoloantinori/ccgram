"""CCGRAM_TOPIC_EMOJI=off silences the automatic title renamer."""

from ccgram.handlers.status import topic_emoji


def test_off_disables_the_gate(monkeypatch):
    monkeypatch.setenv("CCGRAM_TOPIC_EMOJI", "off")
    assert topic_emoji._automatic_renames_enabled() is False


def test_off_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("CCGRAM_TOPIC_EMOJI", " OFF ")
    assert topic_emoji._automatic_renames_enabled() is False


def test_on_enables_the_gate(monkeypatch):
    monkeypatch.setenv("CCGRAM_TOPIC_EMOJI", "on")
    assert topic_emoji._automatic_renames_enabled() is True


def test_unset_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("CCGRAM_TOPIC_EMOJI", raising=False)
    assert topic_emoji._automatic_renames_enabled() is True


async def test_update_returns_before_debounce_when_off(monkeypatch):
    monkeypatch.setenv("CCGRAM_TOPIC_EMOJI", "off")
    monkeypatch.setattr(
        topic_emoji,
        "_resolve_topic_name",
        lambda *a: (_ for _ in ()).throw(
            AssertionError("must not resolve names when off")
        ),
    )
    await topic_emoji.update_topic_emoji(object(), 1, 2, "idle", "antiwire")


async def test_update_reaches_name_resolution_when_on(monkeypatch):
    monkeypatch.setenv("CCGRAM_TOPIC_EMOJI", "on")
    resolved = []
    monkeypatch.setattr(
        topic_emoji,
        "_resolve_topic_name",
        lambda *a: resolved.append(a) or ("name", False),
    )
    await topic_emoji.update_topic_emoji(object(), 1, 2, "idle", "antiwire")
    assert resolved, "the enabled path must resolve the topic name"
