import pytest

from ccgram.screen_buffer import ScreenBuffer


class TestScreenBufferInit:
    def test_default_dimensions(self):
        buf = ScreenBuffer()
        assert buf.columns == 200
        assert buf.rows == 50

    def test_custom_dimensions(self):
        buf = ScreenBuffer(columns=80, rows=24)
        assert buf.columns == 80
        assert buf.rows == 24


class TestFeedAndDisplay:
    def test_plain_text(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("Hello, world!")
        lines = buf.display
        assert lines[0] == "Hello, world!"

    def test_ansi_colors_stripped(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("\x1b[31mred text\x1b[0m normal")
        lines = buf.display
        assert lines[0] == "red text normal"

    def test_ansi_bold_stripped(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("\x1b[1mbold\x1b[0m plain")
        assert buf.display[0] == "bold plain"

    def test_multiline_feed(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("line one\r\nline two\r\nline three")
        assert buf.display[0] == "line one"
        assert buf.display[1] == "line two"
        assert buf.display[2] == "line three"

    def test_empty_lines_are_empty_strings(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("first")
        for line in buf.display[1:]:
            assert line == ""

    def test_trailing_whitespace_stripped(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("text")
        raw = buf._screen.display[0]
        assert len(raw) == 40
        assert buf.display[0] == "text"


class TestRenderedText:
    @pytest.mark.parametrize(
        ("fed", "expected"),
        [
            pytest.param("Hello\r\nWorld", "Hello\nWorld", id="trims_trailing_blanks"),
            pytest.param("", "", id="empty_screen"),
            pytest.param(
                "\x1b[31mred\x1b[0m\r\n\x1b[1mbold\x1b[0m",
                "red\nbold",
                id="strips_ansi",
            ),
            pytest.param(
                "first\r\n\r\nthird", "first\n\nthird", id="preserves_internal_blanks"
            ),
        ],
    )
    def test_rendered_text(self, fed: str, expected: str):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed(fed)
        assert buf.rendered_text == expected


class TestCursorPosition:
    def test_cursor_after_text(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("hello")
        assert buf.cursor_row == 0

    def test_cursor_after_newline(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("hello\r\n")
        assert buf.cursor_row == 1


class TestReset:
    def test_reset_clears_content(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("some content")
        buf.reset()
        assert all(line == "" for line in buf.display)

    def test_reset_resets_cursor(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("hello\r\nworld")
        buf.reset()
        assert buf.cursor_row == 0


class TestResize:
    def test_resize_changes_dimensions(self):
        buf = ScreenBuffer(columns=80, rows=24)
        buf.resize(120, 40)
        assert buf.columns == 120
        assert buf.rows == 40

    def test_resize_clears_content(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("some content")
        buf.resize(60, 10)
        assert all(line == "" for line in buf.display)

    def test_resize_preserves_usability(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("old content")
        buf.resize(80, 10)
        buf.feed("new content")
        assert buf.display[0] == "new content"


class TestSequentialFeeds:
    def test_incremental_feed_accumulates(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("hello")
        buf.feed(" world")
        assert buf.display[0] == "hello world"

    def test_reset_then_feed(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("old content")
        buf.reset()
        buf.feed("new content")
        assert buf.display[0] == "new content"


class TestRealWorldCapture:
    def test_claude_status_with_ansi(self):
        sep = "─" * 30
        raw = (
            "some output\r\n"
            "\x1b[36m✻ Reading file\x1b[0m\r\n"
            f"{sep}\r\n"
            "❯ \r\n"
            f"{sep}\r\n"
            "  \x1b[90m[Opus 4.6]\x1b[0m Context: 34%"
        )
        buf = ScreenBuffer(columns=80, rows=10)
        buf.feed(raw)
        lines = buf.display

        assert "✻ Reading file" in lines[1]
        assert "\x1b" not in lines[1]
        assert lines[2] == sep
        assert lines[4] == sep

    def test_interactive_ui_checkboxes(self):
        raw = (
            "  ☐ Option A\r\n"
            "  \x1b[1m✔ Option B\x1b[0m\r\n"
            "  ☐ Option C\r\n"
            "  Enter to select"
        )
        buf = ScreenBuffer(columns=80, rows=10)
        buf.feed(raw)
        lines = buf.display

        assert "☐ Option A" in lines[0]
        assert "✔ Option B" in lines[1]
        assert "Enter to select" in lines[3]


# A herdr text-format capture shape: escape-free, bare \n separators,
# non-ASCII chrome (box drawing, dingbats), trailing blank lines.
_ESCAPE_FREE_CAPTURE = (
    "+------------------------------------------+\n"
    "| ✻ Reading file src/ccgram/screen_buffer   |\n"
    "|                                           |\n"
    "❯ cd /home/pantinor/data/repo/apps/ccgram\n"
    "\n"
    "\n"
    "  ● Edit(src/ccgram/screen_buffer.py)\n"
    "  ✓ 3 tests passed\n"
)


class _CountingStream:
    """Stream double that records feeds; swapped in for routing tests."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def feed(self, data: str) -> None:
        self._calls.append(data)


def _buffer_with_counting_stream(
    calls: list[str], columns: int = 80, rows: int = 10
) -> ScreenBuffer:
    buf = ScreenBuffer(columns=columns, rows=rows)
    # White-box stream swap for routing assertions only.
    buf._stream = _CountingStream(calls)  # type: ignore[reportAttributeAccessIssue]
    return buf


def _parity_buffers(
    columns: int, rows: int, fed: str, reference_fed: str | None = None
) -> tuple[ScreenBuffer, ScreenBuffer]:
    """Feed `fed` to a fast buffer and its pyte reference; return both.

    The reference gets `reference_fed` verbatim, defaulting to the CRLF
    equivalent of `fed` (pyte's bare LF does not carriage-return, so the
    CRLF form is the frame the bare-LF capture represents).
    """
    fast = ScreenBuffer(columns=columns, rows=rows)
    fast.feed(fed)
    reference = ScreenBuffer(columns=columns, rows=rows)
    reference.feed(
        reference_fed if reference_fed is not None else fed.replace("\n", "\r\n")
    )
    return fast, reference


class TestFastPathParity:
    """Fast-path rendering must equal pyte's rendering of the same frame."""

    def test_display_matches_pyte_reference(self):
        fast, reference = _parity_buffers(80, 10, _ESCAPE_FREE_CAPTURE)
        assert fast.display == reference.display

    def test_rendered_text_matches_pyte_reference(self):
        fast, reference = _parity_buffers(80, 10, _ESCAPE_FREE_CAPTURE)
        assert fast.rendered_text == reference.rendered_text
        assert fast.rendered_text.endswith("✓ 3 tests passed")

    def test_tab_line_matches_pyte_single_line(self):
        # Single line, so pyte's missing CR cannot stagger it. The escape
        # appended to the reference is a no-op SGR whose only job is to
        # push the reference buffer down the pyte path; rendering is
        # unaffected, so any divergence is a real tab-stop difference.
        fed = "col0\tcol8\tcol16"
        fast, reference = _parity_buffers(40, 5, fed, reference_fed=fed + "\x1b[0m")
        assert fast.display[0] == reference.display[0]
        assert fast.display[0].startswith("col0    col8    ")

    def test_fewer_lines_than_rows_pads_to_rows(self):
        fast, reference = _parity_buffers(40, 8, "one\ntwo\n")
        display = fast.display
        assert len(display) == 8
        assert display[:2] == ["one", "two"]
        assert all(line == "" for line in display[2:])
        assert display == reference.display

    def test_more_lines_than_rows_keeps_tail(self):
        text = "\n".join(f"line {i}" for i in range(6))
        fast, reference = _parity_buffers(40, 3, text)
        assert fast.display == ["line 3", "line 4", "line 5"]
        assert fast.display == reference.display

    def test_exact_margin_line_falls_back_to_pyte_wrap(self):
        # A line exactly columns wide leaves the cursor at the margin, so
        # pyte wraps the next drawn character to a new row.
        buf = ScreenBuffer(columns=10, rows=4)
        buf.feed("0123456789\nsecond")
        assert buf.display[:3] == ["0123456789", "", "second"]


class TestFastPathRouting:
    """Which feeds reach the pyte stream.

    Routing is asserted white-box at the stream seam because the fast
    path's whole purpose is that no emulation runs; rendering parity is
    covered by TestFastPathParity and TestFastPathFallbacks.
    """

    @pytest.mark.parametrize(
        "fed",
        [
            pytest.param(_ESCAPE_FREE_CAPTURE, id="escape_free_capture"),
            pytest.param("plain text", id="ascii"),
            pytest.param("✻ ❯ ● ✓", id="non_ascii_chrome"),
            pytest.param("col0\tcol8", id="tabs"),
        ],
    )
    def test_escape_free_feed_skips_pyte_stream(self, fed):
        calls: list[str] = []
        buf = _buffer_with_counting_stream(calls)
        buf.feed(fed)
        _ = buf.display, buf.rendered_text, buf.cursor_row
        assert calls == []

    @pytest.mark.parametrize(
        "fed",
        [
            pytest.param("\x1b[31mred\x1b[0m", id="ansi_sgr"),
            pytest.param("中文 text", id="wide_char"),
            pytest.param("a\u0301bc", id="zero_width_char"),
            pytest.param("one\r\ntwo", id="carriage_return"),
            pytest.param("nul\x00", id="nul"),
            pytest.param("del\x7f", id="del"),
        ],
    )
    def test_qualified_char_reaches_pyte_stream(self, fed):
        calls: list[str] = []
        buf = _buffer_with_counting_stream(calls)
        buf.feed(fed)
        assert calls == [fed]


class TestFastPathFallbacks:
    def test_ansi_sequence_strips_styles_via_pyte(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("\x1b[31mred\x1b[0m after")
        assert buf.display[0] == "red after"

    def test_fast_lines_replayed_into_pyte_on_fallback(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("abc")
        buf.feed("\x1b[31mR\x1b[0m")
        # The fast-fed text must reach pyte so the stream stays continuous.
        assert buf.display[0] == "abcR"

    def test_zero_width_char_nfc_merged_by_pyte(self):
        # pyte merges the combining mark into a precomposed glyph; a leaked
        # fast path would keep the decomposed pair.
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("a\u0301bc")
        assert buf.display[0] == "\u00e1bc"

    def test_cross_feed_merged_row_checked_against_margin(self):
        # The merged first row grows across feeds; once it reaches the
        # margin the whole feed must fall back to pyte (which wraps).
        calls: list[str] = []
        buf = _buffer_with_counting_stream(calls, columns=10, rows=4)
        buf.feed("abc")
        assert calls == []
        buf.feed("defghij")
        assert calls == ["abc", "defghij"]

    def test_fast_lines_capped_to_rows_like_scrolled_screen(self):
        buf = ScreenBuffer(columns=40, rows=3)
        buf.feed("a\nb\nc\n")
        buf.feed("d\ne")
        assert buf.display == ["c", "d", "e"]
        reference = ScreenBuffer(columns=40, rows=3)
        reference.feed("a\r\nb\r\nc\r\nd\r\ne")
        assert buf.display == reference.display

    def test_no_fast_feed_after_pyte_feed(self):
        # Stream state set by escapes (charsets, tabstops) must not leak
        # into a fast-path split; after any pyte feed, later feeds stay
        # on the pyte path.
        calls: list[str] = []
        buf = _buffer_with_counting_stream(calls)
        buf.feed("\x1b(0")
        buf.feed("qq")
        assert len(calls) == 2

    def test_reset_re_enables_fast_path(self):
        buf = ScreenBuffer(columns=40, rows=5)
        buf.feed("\x1b[31mstyled\x1b[0m")
        buf.reset()
        buf.feed("plain\ntext")
        assert buf.display[:2] == ["plain", "text"]


class TestFastPathCursorRow:
    def test_cursor_row_is_last_nonblank_row(self):
        buf = ScreenBuffer(columns=40, rows=8)
        buf.feed("first\nsecond\n\n\n")
        assert buf.cursor_row == 1

    def test_cursor_row_zero_when_all_blank(self):
        buf = ScreenBuffer(columns=40, rows=8)
        buf.feed("\n\n\n")
        assert buf.cursor_row == 0

    def test_rows_below_cursor_row_are_blank(self):
        # terminal_parser.py bounds trailing-blank trimming with
        # cursor_row; the approximation holds only if nothing but blanks
        # sits below it.
        buf = ScreenBuffer(columns=40, rows=8)
        buf.feed("first\nsecond\n\n\n")
        display = buf.display
        assert all(not line.strip() for line in display[buf.cursor_row + 1 :])
