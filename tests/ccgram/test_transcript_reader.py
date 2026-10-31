"""Tests for transcript reader offset handling."""

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ccgram import transcript_reader
from ccgram.idle_tracker import IdleTracker
from ccgram.monitor_state import BacklogSkipIntent, MonitorState, TrackedSession
from ccgram.transcript_reader import TranscriptReader, _StableRead


def test_clear_session_cancels_pending_skip_barrier(tmp_path) -> None:
    state = MonitorState(state_file=tmp_path / "monitor.json")
    state.update_session(TrackedSession("sess", str(tmp_path / "session.jsonl")))
    state.begin_skip(BacklogSkipIntent("sess", "@1", 1, 4, 99, 10, 0))
    reader = TranscriptReader(state, IdleTracker())

    reader.clear_session("sess")

    assert "sess" not in state.pending_skips
    assert state.get_session("sess") is None


async def test_same_transcript_reuses_offset_after_session_map_refresh(
    tmp_path,
) -> None:
    """A tmux rename/session-map refresh must not replay an existing transcript."""
    first = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"old"}]}}\n'
    )
    second = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"new"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(first + second, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess-before-rename",
            file_path=str(session_file),
            last_byte_offset=len(first.encode()),
        )
    )
    state.begin_skip(BacklogSkipIntent("sess-before-rename", "@1", 1, 4, 99, 50, 0))
    reader = TranscriptReader(state, IdleTracker())

    messages = []
    await reader._process_session_file(
        "sess-after-rename",
        session_file,
        messages,
        window_id="@1",
    )

    assert [msg.text for msg in messages] == ["new"]
    tracked = state.get_session("sess-after-rename")
    assert tracked is not None
    assert tracked.parsed_offset == session_file.stat().st_size
    assert "sess-before-rename" not in state.pending_skips


async def test_catch_up_read_after_restart_is_not_activity(tmp_path) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"a"}]}}\n'
    unread = '{"type":"assistant","message":{"content":[{"type":"text","text":"b"}]}}\n'
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(old + unread, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=len(old.encode()),
        )
    )
    idle = IdleTracker()
    reader = TranscriptReader(state, idle)

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert [msg.text for msg in messages] == ["b"]
    assert idle.get_last_activity("sess") is None


async def test_first_poll_counts_only_bytes_written_after_startup(tmp_path) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"a"}]}}\n'
    unread = '{"type":"assistant","message":{"content":[{"type":"text","text":"b"}]}}\n'
    fresh = '{"type":"assistant","message":{"content":[{"type":"text","text":"c"}]}}\n'
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(old + unread, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=len(old.encode()),
        )
    )
    idle = IdleTracker()
    reader = TranscriptReader(state, idle)
    with session_file.open("a") as transcript:
        transcript.write(fresh)

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert [msg.text for msg in messages] == ["b", "c"]
    assert idle.get_last_activity("sess") is not None


async def test_post_start_truncation_clamps_to_eof_without_replay(tmp_path) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"old"}]}}\n'
    history = old * 10
    fresh = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"new"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=len(old.encode()) * 5,
        )
    )
    idle = IdleTracker()
    reader = TranscriptReader(state, idle)
    session_file.write_text(fresh, newline="\n")

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert messages == []


async def test_atomic_replacement_after_start_clamps_to_eof(tmp_path) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"old"}]}}\n'
    fresh = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"fresh"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(old, newline="\n")
    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess", file_path=str(session_file), last_byte_offset=0
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("sess", session_file, [], window_id="@1")

    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text(fresh, newline="\n")
    replacement.replace(session_file)

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert messages == []


async def test_same_inode_rewrite_with_preserved_mtime_does_not_replay(
    tmp_path,
) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"old"}]}}\n'
    new = old.replace("old", "new")
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(old)
    initial_stat = session_file.stat()
    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess", file_path=str(session_file), last_byte_offset=0
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("sess", session_file, [], window_id="@1")

    session_file.write_text(new)
    os.utime(
        session_file,
        ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns),
    )

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert messages == []


async def test_replacement_between_stat_and_open_clamps_to_eof(tmp_path) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"old"}]}}\n'
    new = old.replace("old", "new")
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(old)
    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess", file_path=str(session_file), last_byte_offset=0
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("sess", session_file, [], window_id="@1")
    original_read = reader._read_new_lines
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text(new)
    session_file.write_text(old)  # Trigger the read before replacing it in-flight.
    replaced = False

    async def replace_then_read(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            replacement.replace(session_file)
            replaced = True
        return await original_read(*args, **kwargs)

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert messages == []


async def test_whole_file_rewrite_bypasses_unchanged_mtime(tmp_path) -> None:
    session_file = tmp_path / "transcript.json"
    session_file.write_text("old")
    old_stat = session_file.stat()
    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess", file_path=str(session_file), last_byte_offset=0
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    provider = SimpleNamespace(
        capabilities=SimpleNamespace(
            name="gemini",
            supports_incremental_read=False,
            supports_task_tracking=False,
        )
    )
    with (
        patch(
            "ccgram.transcript_reader._resolve_provider_for_file", return_value=provider
        ),
        patch.object(
            reader,
            "_read_session_entries",
            new=AsyncMock(
                side_effect=lambda *_args, **_kwargs: _StableRead(
                    [], session_file.stat(), False
                )
            ),
        ) as read,
        patch.object(reader, "_append_provider_messages"),
    ):
        await reader._process_session_file("sess", session_file, [], window_id="@1")
        session_file.write_text("new-long")
        os.utime(session_file, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        await reader._process_session_file("sess", session_file, [], window_id="@1")
    assert read.await_count == 2


async def test_whole_file_replacement_bypasses_unchanged_mtime(tmp_path) -> None:
    session_file = tmp_path / "transcript.json"
    session_file.write_text("old")
    old_stat = session_file.stat()
    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess", file_path=str(session_file), last_byte_offset=0
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    provider = SimpleNamespace(
        capabilities=SimpleNamespace(
            name="gemini",
            supports_incremental_read=False,
            supports_task_tracking=False,
        )
    )

    with (
        patch(
            "ccgram.transcript_reader._resolve_provider_for_file", return_value=provider
        ),
        patch.object(
            reader,
            "_read_session_entries",
            new=AsyncMock(
                side_effect=lambda *_args, **_kwargs: _StableRead(
                    [],
                    session_file.stat(),
                    False,
                )
            ),
        ) as read,
        patch.object(reader, "_append_provider_messages"),
    ):
        await reader._process_session_file("sess", session_file, [], window_id="@1")
        replacement = tmp_path / "replacement.json"
        replacement.write_text("new")
        replacement.replace(session_file)
        os.utime(session_file, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))

        await reader._process_session_file("sess", session_file, [], window_id="@1")

    assert read.await_count == 2


async def test_failed_startup_read_preserves_catch_up_boundary(tmp_path) -> None:
    old = '{"type":"assistant","message":{"content":[{"type":"text","text":"a"}]}}\n'
    unread = '{"type":"assistant","message":{"content":[{"type":"text","text":"b"}]}}\n'
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(old + unread, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=len(old.encode()),
        )
    )
    idle = IdleTracker()
    reader = TranscriptReader(state, idle)

    with patch.object(
        reader, "_read_new_lines", new=AsyncMock(side_effect=OSError("busy"))
    ):
        await reader._process_session_file("sess", session_file, [], window_id="@1")

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert [msg.text for msg in messages] == ["b"]
    assert idle.get_last_activity("sess") is None


async def test_metadata_only_ctime_bump_does_not_replay_transcript(tmp_path) -> None:
    """A ctime bump that leaves consumed bytes intact is not a replacement."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    os.chmod(session_file, 0o600)

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert messages == []
    tracked = state.get_session("sess")
    assert tracked is not None
    assert tracked.parsed_offset == session_file.stat().st_size


async def test_append_during_read_does_not_replay_transcript(tmp_path) -> None:
    """A concurrent append mid-read must deliver the new entry, not the file."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    fresh = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"fresh"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    original_read = reader._read_new_lines
    appended = False

    async def append_then_read(*args, **kwargs):
        nonlocal appended
        if not appended:
            with session_file.open("a") as transcript:
                transcript.write(fresh)
            appended = True
        return await original_read(*args, **kwargs)

    messages = []
    with patch.object(reader, "_read_new_lines", side_effect=append_then_read):
        await reader._process_session_file(
            "sess", session_file, messages, window_id="@1"
        )

    assert [msg.text for msg in messages] == ["fresh"]


async def test_rewrite_before_tail_marker_does_not_replay(tmp_path) -> None:
    """A rewrite outside the tail marker must not be skipped as an append."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("sess", session_file, [], window_id="@1")
    reader._file_mtimes["sess"] = 0.0

    original_read = reader._read_new_lines
    rewritten = False

    async def rewrite_then_read(*args, **kwargs):
        nonlocal rewritten
        if not rewritten:
            session_file.write_text(
                session_file.read_text().replace('"h0"', '"changed"', 1),
                newline="\n",
            )
            rewritten = True
        return await original_read(*args, **kwargs)

    messages = []
    await reader._process_session_file("sess", session_file, messages, window_id="@1")

    assert messages == []


async def test_replaced_smaller_transcript_resumes_from_eof_no_replay(
    tmp_path,
) -> None:
    """A replaced (smaller) transcript must not be replayed as notifications.

    Regression for the 2026-08-17 flood: an adopted offset larger than the
    new file's size used to reset the offset to 0 and re-emit the whole
    history, flooding Telegram and starving every other topic.
    """
    big = '{"type":"assistant","message":{"content":[{"type":"text","text":"old"}]}}\n'
    small = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"fresh"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(small, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    # offset from the PREVIOUS (larger) transcript, carried over by adoption
    state.update_session(
        TrackedSession(
            session_id="sess-replaced",
            file_path=str(session_file),
            last_byte_offset=len(big.encode()) * 100,
        )
    )
    reader = TranscriptReader(state, IdleTracker())

    messages = []
    await reader._process_session_file(
        "sess-replaced", session_file, messages, window_id="@1"
    )

    assert messages == []  # nothing replayed from the replaced file
    tracked = state.get_session("sess-replaced")
    assert tracked is not None
    assert tracked.parsed_offset == session_file.stat().st_size


_CLAUDE_PROVIDER = SimpleNamespace(
    capabilities=SimpleNamespace(
        name="claude",
        supports_incremental_read=True,
        supports_task_tracking=False,
    )
)


async def test_consecutive_appends_skip_prefix_digest(tmp_path) -> None:
    """Growing transcripts must not pay a full-file digest every poll cycle."""
    history = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h0"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=len(history.encode()),
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    real_digest = transcript_reader._prefix_digest

    delivered = []
    with (
        patch(
            "ccgram.transcript_reader._resolve_provider_for_file",
            return_value=_CLAUDE_PROVIDER,
        ),
        patch("ccgram.transcript_reader._prefix_digest", wraps=real_digest) as digest,
    ):
        for index in range(4):
            line = (
                '{"type":"assistant","message":{"content":[{"type":"text","text":"m%d"}]}}\n'
                % index
            )
            with session_file.open("a") as transcript:
                transcript.write(line)
            messages = []
            await reader._process_session_file(
                "sess", session_file, messages, window_id="@1"
            )
            delivered.extend(msg.text for msg in messages)
        assert digest.call_count == 0

    assert delivered == ["m0", "m1", "m2", "m3"]


async def test_rewrite_of_tail_marker_window_clamps_without_replay(
    tmp_path,
) -> None:
    """A rewrite inside the tail-marker window must verify and clamp."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    with patch(
        "ccgram.transcript_reader._resolve_provider_for_file",
        return_value=_CLAUDE_PROVIDER,
    ):
        await reader._process_session_file("sess", session_file, [], window_id="@1")

        session_file.write_text(history.replace('"h4"', '"h9"'), newline="\n")
        reader._file_mtimes["sess"] = 0.0

        messages = []
        await reader._process_session_file(
            "sess", session_file, messages, window_id="@1"
        )

    assert messages == []
    tracked = state.get_session("sess")
    assert tracked is not None
    assert tracked.parsed_offset == session_file.stat().st_size
    # The clamp re-baselines and the read keeps the result, but a clamped
    # cycle is not a clean verification: the reset to the shortest interval
    # must survive the cycle instead of being doubled away.
    assert reader._prefix_verify["sess"][:2] == (0, 1)


async def test_prefix_verify_backoff_resets_on_restart_and_generation_change(
    tmp_path,
) -> None:
    """The digest backoff re-arms immediately after replacement or restart."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    with patch(
        "ccgram.transcript_reader._resolve_provider_for_file",
        return_value=_CLAUDE_PROVIDER,
    ):
        await reader._process_session_file("sess", session_file, [], window_id="@1")
        assert reader._prefix_verify["sess"][:2] == (0, 2)

        for index in range(2):
            line = (
                '{"type":"assistant","message":{"content":[{"type":"text","text":"m%d"}]}}\n'
                % index
            )
            with session_file.open("a") as transcript:
                transcript.write(line)
            await reader._process_session_file("sess", session_file, [], window_id="@1")
        assert reader._prefix_verify["sess"][:2] == (2, 2)

        replacement = tmp_path / "replacement.jsonl"
        replacement.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"x"}]}}\n',
            newline="\n",
        )
        replacement.replace(session_file)
        messages = []
        await reader._process_session_file(
            "sess", session_file, messages, window_id="@1"
        )

    assert messages == []
    assert reader._prefix_verify["sess"][:2] == (0, 1)

    reader.clear_session("sess")
    assert "sess" not in reader._prefix_verify


async def test_idle_due_session_verifies_once_not_every_cycle(tmp_path) -> None:
    """A due session verifies once per interval while idle, not per tick."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    real_digest = transcript_reader._prefix_digest

    with (
        patch(
            "ccgram.transcript_reader._resolve_provider_for_file",
            return_value=_CLAUDE_PROVIDER,
        ),
        patch("ccgram.transcript_reader._prefix_digest", wraps=real_digest) as digest,
    ):
        for index in range(2):
            line = (
                '{"type":"assistant","message":{"content":[{"type":"text","text":"m%d"}]}}\n'
                % index
            )
            with session_file.open("a") as transcript:
                transcript.write(line)
            await reader._process_session_file("sess", session_file, [], window_id="@1")
        assert digest.call_count == 0

        for _ in range(3):
            await reader._process_session_file("sess", session_file, [], window_id="@1")
        # The first idle cycle verifies the frozen prefix and extends the
        # baseline, then doubles the interval; the rest defer.
        assert digest.call_count == 2


async def test_overdue_session_forces_verification_even_while_growing(
    tmp_path,
) -> None:
    """Past the defer cap, growth cycles verify instead of deferring forever."""
    history = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h0"}]}}\n'
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=len(history.encode()),
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    reader._prefix_verify["sess"] = (
        transcript_reader._PREFIX_VERIFY_CAP,
        transcript_reader._PREFIX_VERIFY_CAP,
        0.0,
    )
    real_digest = transcript_reader._prefix_digest

    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"m0"}]}}\n'
    with (
        patch(
            "ccgram.transcript_reader._resolve_provider_for_file",
            return_value=_CLAUDE_PROVIDER,
        ),
        patch("ccgram.transcript_reader._prefix_digest", wraps=real_digest) as digest,
    ):
        with session_file.open("a") as transcript:
            transcript.write(line)
        messages = []
        await reader._process_session_file(
            "sess", session_file, messages, window_id="@1"
        )
        assert digest.call_count >= 1
        assert reader._prefix_verify["sess"][0] < transcript_reader._PREFIX_VERIFY_CAP

    assert [msg.text for msg in messages] == ["m0"]


async def test_atomic_replacement_preserving_marker_clamps(tmp_path) -> None:
    """A new inode keeping the verified prefix and marker but editing the gap clamps.

    Review P1. The baseline must NOT cover consumed: appends since the
    constructor snapshot grow the parse position past the digest, then an
    atomic replacement preserves the verified prefix and the last 128
    bytes while changing the middle and appends one unread line beyond.
    The digest ran and matched its own range, the marker matches, the size
    covers pos, yet nothing proved the gap: the dismissal must not fire on
    generation evidence alone, and the clamp must swallow the unread line
    as history.
    """
    base = '{"type":"user","message":{"content":[{"type":"text","text":"a"}]}}\n'
    session_file = tmp_path / "t.jsonl"
    session_file.write_text(base, newline="\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("s", session_file, [], window_id="@1")
    baseline = state.tracked_sessions["s"].parsed_offset

    grow = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\n'
        % ("g" * 160)
    )
    with session_file.open("a") as fh:
        fh.write(grow)
    await reader._process_session_file("s", session_file, [], window_id="@1")
    consumed = state.tracked_sessions["s"].parsed_offset
    assert consumed > baseline
    marker_bytes = transcript_reader._MARKER_BYTES
    gap_len = (consumed - marker_bytes) - baseline
    # The preserved tail window must start past the baseline: a shorter
    # grow puts the fill inside the window and clamps through the ordinary
    # marker-mismatch path, which the pre-fix code takes as well.
    assert gap_len > 0

    fresh = '{"type":"assistant","message":{"content":[{"type":"text","text":"tail-fresh"}]}}\n'
    # Byte-exact by construction: text slicing would match the marker
    # window only while every fixture byte is ASCII.
    data = session_file.read_bytes()
    replaced = tmp_path / "r.jsonl"
    replaced.write_bytes(
        data[:baseline]
        + b"X" * gap_len
        + data[consumed - marker_bytes :]
        + fresh.encode()
    )
    os.replace(replaced, session_file)

    messages: list = []
    await reader._process_session_file("s", session_file, messages, window_id="@1")
    # The discriminating observable: the pre-fix code dismisses the
    # generation signal (marker, size, and digest all intact) and delivers
    # the unread line; the clamp treats it as already-notified history.
    assert messages == []
    assert state.tracked_sessions["s"].parsed_offset >= session_file.stat().st_size


async def test_stale_marker_mismatch_during_inplace_rewrite_is_not_an_append(
    tmp_path,
) -> None:
    """A stale-offset marker mismatch during an in-place rewrite is not an append.

    Review gate 2. The cached marker offset trails the parse position (the
    post-clamp cache shape), so a mismatch there cannot set marker_changed,
    but it did happen during a rewrite: only a marker that still MATCHES
    may qualify the cycle as a verified append. The mid-read rewrite edits
    consumed bytes inside the stale window, so the read must fall to the
    consumed-prefix digest, fail it, and clamp instead of delivering the
    concurrent entry as an append cycle.
    """
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(6)
    )
    fresh = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"fresh"}]}}\n'
    )
    session_file = tmp_path / "t.jsonl"
    session_file.write_text(history, newline="\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("s", session_file, [], window_id="@1")
    pos = state.tracked_sessions["s"].parsed_offset
    with session_file.open("a") as fh:
        fh.write(fresh)
    # Sentinel bytes no transcript content can match.
    reader._file_markers["s"] = (pos - 64, b"stale-sentinel")

    original_read = reader._read_new_lines
    rewritten = False

    async def rewrite_then_read(*args, **kwargs):
        nonlocal rewritten
        if not rewritten:
            session_file.write_text(
                session_file.read_text().replace('"h3"', '"hZ"', 1),
                newline="\n",
            )
            rewritten = True
        return await original_read(*args, **kwargs)

    messages: list = []
    t0 = time.monotonic()
    with patch.object(reader, "_read_new_lines", side_effect=rewrite_then_read):
        await reader._process_session_file("s", session_file, messages, window_id="@1")

    assert messages == []
    assert reader._prefix_verify["s"][:2] == (0, 1)
    # The post-clamp reset must carry a real monotonic stamp, not the
    # never-verified 0.0 sentinel: on a freshly booted host the sentinel
    # would leave the idle deadline undue for the whole boot window.
    assert reader._prefix_verify["s"][2] >= t0


async def test_generation_dismissal_requires_a_digest_verdict(tmp_path) -> None:
    """An OSError during the scheduled digest blocks the generation dismissal.

    Review P1, OSError half. The marker matches and the cached baseline
    covers every consumed byte, but the digest run raised: no verdict ran,
    so a new inode must not be dismissed on metadata alone. Dropping the
    prefix_checked conjunct would fire the dismissal and deliver the
    unread line.
    """
    base = '{"type":"user","message":{"content":[{"type":"text","text":"a"}]}}\n'
    session_file = tmp_path / "t.jsonl"
    session_file.write_text(base, newline="\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("s", session_file, [], window_id="@1")
    baseline = state.tracked_sessions["s"].parsed_offset

    grow = (
        '{"type":"assistant","message":{"content":[{"type":"text","text":"%s"}]}}\n'
        % ("g" * 160)
    )
    with session_file.open("a") as fh:
        fh.write(grow)
    # Drop the marker cache so the growth cycle cannot defer the scheduled
    # digest: the clean verification extends the cached baseline over the
    # gap, which is what would make the covered-range check alone pass.
    reader._file_markers.pop("s", None)
    await reader._process_session_file("s", session_file, [], window_id="@1")
    consumed = state.tracked_sessions["s"].parsed_offset
    marker_bytes = transcript_reader._MARKER_BYTES
    gap_len = (consumed - marker_bytes) - baseline
    assert gap_len > 0

    fresh = '{"type":"assistant","message":{"content":[{"type":"text","text":"tail-fresh"}]}}\n'
    data = session_file.read_bytes()
    replaced = tmp_path / "r.jsonl"
    replaced.write_bytes(
        data[:baseline]
        + b"X" * gap_len
        + data[consumed - marker_bytes :]
        + fresh.encode()
    )
    os.replace(replaced, session_file)

    real_digest = transcript_reader._prefix_digest
    raised = {"done": False}

    def _raise_once(path, size):
        if not raised["done"]:
            raised["done"] = True
            raise OSError("digest unavailable")
        return real_digest(path, size)

    messages: list = []
    with patch("ccgram.transcript_reader._prefix_digest", side_effect=_raise_once):
        await reader._process_session_file("s", session_file, messages, window_id="@1")

    assert messages == []
    assert state.tracked_sessions["s"].parsed_offset >= session_file.stat().st_size


def test_idle_deadline_forces_verification(tmp_path) -> None:
    """Quiet polls stop counting, so the monotonic deadline forces a digest.

    Review P2: the stale-stamp branch is the one that must fire when the
    growth-cycle counter sits far under its threshold.
    """
    session_file = tmp_path / "t.jsonl"
    session_file.write_text("{}\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    reader._prefix_verify["s"] = (
        1,
        32,
        time.monotonic() - transcript_reader._PREFIX_VERIFY_MAX_IDLE_S - 1,
    )
    assert reader._prefix_verify_due("s") is True
    reader._prefix_verify["s"] = (1, 32, time.monotonic())
    assert reader._prefix_verify_due("s") is False


async def test_identity_flip_after_probe_clamp_restores_the_baseline(
    tmp_path, monkeypatch
) -> None:
    """A clamp observed during an identity flip must not bless the new file.

    The probe clamps a replaced transcript and re-baselines the prefix at
    the new EOF. When the provider observation flips right after the probe,
    the rollback restores the parse offset; it must restore the baseline
    too, or the next cycle dismisses the replacement against a baseline
    nobody committed to and delivers the replaced file as new messages.
    """
    from ccgram.window_state_ports import identity_state

    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    await reader._process_session_file("s", session_file, [], window_id="@1")
    pos = state.tracked_sessions["s"].parsed_offset
    baseline = reader._file_prefixes["s"]
    verify = reader._prefix_verify.get("s")

    replaced = tmp_path / "r.jsonl"
    replaced.write_text(
        "".join(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"g%d"}]}}\n'
            % index
            for index in range(4)
        ),
        newline="\n",
    )
    os.replace(replaced, session_file)

    calls = {"n": 0}

    def flip_after_probe(window_id, provider_name):
        calls["n"] += 1
        # The entry gate accepts; the post-probe check is what flips.
        return calls["n"] < 2

    monkeypatch.setattr(
        identity_state, "accepts_provider_observation", flip_after_probe
    )
    flipped: list = []
    await reader._process_session_file("s", session_file, flipped, window_id="@1")
    assert flipped == []
    assert state.tracked_sessions["s"].parsed_offset == pos
    assert reader._file_prefixes["s"] == baseline
    assert reader._prefix_verify.get("s") == verify

    # With identity stable again the next cycle re-judges the file from the
    # OLD baseline: the replacement clamps instead of being dismissed and
    # the replaced content is never delivered.
    monkeypatch.setattr(
        identity_state,
        "accepts_provider_observation",
        lambda window_id, provider_name: True,
    )
    messages: list = []
    await reader._process_session_file("s", session_file, messages, window_id="@1")
    assert messages == []
    assert state.tracked_sessions["s"].parsed_offset >= session_file.stat().st_size


async def test_missing_baseline_seeds_on_read_and_recovers_detection(
    tmp_path,
) -> None:
    """A failed startup snapshot must not disable rewrite detection forever.

    Review P1: with no cached prefix baseline the scheduled digest never
    starts, and the clamp-only re-baseline means a healthy read never
    creates one, so a rewrite outside the tail-marker window would stay
    undetected for the process lifetime. The first committed read now
    seeds the baseline at its parse position, and the next replacement
    signal gets a digest verdict again.
    """
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "t.jsonl"
    session_file.write_text(history, newline="\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    # The state a failed constructor snapshot leaves behind: no baseline.
    reader._file_prefixes.pop("s", None)

    messages: list = []
    await reader._process_session_file("s", session_file, messages, window_id="@1")
    assert len(messages) == 5
    baseline = reader._file_prefixes.get("s")
    pos = state.tracked_sessions["s"].parsed_offset
    assert baseline is not None
    assert baseline[0] == pos

    # A rewrite inside the now-verified range but outside the tail-marker
    # window, plus one unread line, with the schedule overdue so the growth
    # cycle cannot defer the digest: without the seeded baseline the digest
    # has no range to compare, the marker dismisses the signal, and the
    # unread line is delivered as if nothing happened.
    reader._prefix_verify["s"] = (
        transcript_reader._PREFIX_VERIFY_CAP,
        transcript_reader._PREFIX_VERIFY_CAP,
        0.0,
    )
    fresh = '{"type":"assistant","message":{"content":[{"type":"text","text":"tail-fresh"}]}}\n'
    session_file.write_text(
        session_file.read_text().replace('"h0"', '"hZ"', 1) + fresh, newline="\n"
    )
    clamped: list = []
    await reader._process_session_file("s", session_file, clamped, window_id="@1")
    assert clamped == []
    assert state.tracked_sessions["s"].parsed_offset >= session_file.stat().st_size


async def test_baseline_seed_failure_keeps_the_cycle_and_retries(tmp_path) -> None:
    """A transient OSError during the seed keeps the commit and the retry.

    The marker read already succeeded, so the cycle must deliver and store
    its caches rather than abort; and the stored mtime must not gate the
    retry away, or a quiet file never reaches the next commit and the
    missing-baseline condition persists. The successful retry stamps the
    verification schedule instead of re-hashing the same range.
    """
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "t.jsonl"
    session_file.write_text(history, newline="\n")
    state = MonitorState(state_file=tmp_path / "m.json")
    state.update_session(
        TrackedSession(session_id="s", file_path=str(session_file), last_byte_offset=0)
    )
    reader = TranscriptReader(state, IdleTracker())
    reader._file_prefixes.pop("s", None)

    real_digest = transcript_reader._prefix_digest
    raised = {"done": False}

    def _raise_once(path, size):
        if not raised["done"]:
            raised["done"] = True
            raise OSError("digest unavailable")
        return real_digest(path, size)

    messages: list = []
    with patch("ccgram.transcript_reader._prefix_digest", side_effect=_raise_once):
        await reader._process_session_file("s", session_file, messages, window_id="@1")
        assert len(messages) == 5
        assert "s" not in reader._file_prefixes
        assert "s" not in reader._file_mtimes

        # Quiet file, same patch context: the retry reaches the commit and
        # the seed succeeds, stamping the schedule it just verified.
        await reader._process_session_file("s", session_file, [], window_id="@1")
        baseline = reader._file_prefixes.get("s")
        assert baseline is not None
        assert baseline[0] == state.tracked_sessions["s"].parsed_offset
        assert reader._prefix_verify.get("s") is not None
        assert reader._prefix_verify["s"][:2] == (0, 1)


async def test_clamp_cycle_keeps_verify_schedule_at_shortest_interval(
    tmp_path,
) -> None:
    """The cycle after a clamp must verify again, not inherit a doubled interval."""
    history = "".join(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"h%d"}]}}\n'
        % index
        for index in range(5)
    )
    session_file = tmp_path / "transcript.jsonl"
    session_file.write_text(history, newline="\n")

    state = MonitorState(state_file=tmp_path / "monitor_state.json")
    state.update_session(
        TrackedSession(
            session_id="sess",
            file_path=str(session_file),
            last_byte_offset=session_file.stat().st_size,
        )
    )
    reader = TranscriptReader(state, IdleTracker())
    real_digest = transcript_reader._prefix_digest
    with patch(
        "ccgram.transcript_reader._resolve_provider_for_file",
        return_value=_CLAUDE_PROVIDER,
    ):
        await reader._process_session_file("sess", session_file, [], window_id="@1")

        session_file.write_text(history.replace('"h4"', '"h9"'), newline="\n")
        reader._file_mtimes["sess"] = 0.0
        await reader._process_session_file("sess", session_file, [], window_id="@1")
        assert reader._prefix_verify["sess"][:2] == (0, 1)

        # One marker-verified append cycle counts up to (1, 1), so the next
        # quiet cycle is due and must run the full verification. Had the
        # clamp cycle's intact read doubled the interval to (0, 2), the state
        # would sit at (1, 2) here and this cycle's digest would be skipped.
        with session_file.open("a") as transcript:
            transcript.write(
                '{"type":"assistant","message":{"content":[{"type":"text","text":"m0"}]}}\n'
            )
        await reader._process_session_file("sess", session_file, [], window_id="@1")
        assert reader._prefix_verify["sess"][:2] == (1, 1)

        reader._file_mtimes["sess"] = 0.0
        with patch(
            "ccgram.transcript_reader._prefix_digest", wraps=real_digest
        ) as digest:
            await reader._process_session_file("sess", session_file, [], window_id="@1")
        assert digest.call_count > 0
        assert reader._prefix_verify["sess"][:2] == (0, 2)
