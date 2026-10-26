"""VT100 screen buffer — wraps pyte for clean terminal text rendering.

Feeds raw tmux pane captures (with ANSI escape sequences) into a pyte
virtual terminal, producing clean rendered lines stripped of control codes.
Used by terminal_parser.py for robust status and interactive UI detection.
Escape-free single-width text (herdr/agterm text captures) skips pyte
re-emulation entirely and renders as split lines.

Key class: ScreenBuffer — create, feed raw text, read rendered lines.
"""

import re

import structlog
import pyte
from wcwidth import wcwidth

logger = structlog.get_logger()

_NON_ASCII = re.compile(r"[^\x00-\x7f]+")
_BARE_LF = re.compile(r"(?<!\r)\n")


class ScreenBuffer:
    """Virtual terminal screen backed by pyte.

    Wraps a pyte Screen + Stream to accept raw terminal text and
    expose clean rendered output lines, cursor position, and separator
    detection.
    """

    def __init__(self, columns: int = 200, rows: int = 50) -> None:
        self._screen = pyte.Screen(columns, rows)
        self._stream = pyte.Stream(self._screen)
        self._fast_lines: list[str] | None = None
        self._pyte_fed = False

    @property
    def columns(self) -> int:
        return self._screen.columns

    @property
    def rows(self) -> int:
        return self._screen.lines

    def _try_fast_feed(self, raw_text: str) -> bool:
        """Store qualifying text as split lines, skipping pyte emulation.

        herdr and agterm text captures carry no escape sequences, so pyte
        has nothing to strip and re-emulating every character once per
        status tick is pure cost (the poll's single biggest measured one).
        Text qualifies when every character is printable and single-width
        once tabs and newlines are accounted for; the width oracle is
        wcwidth(), the same callable pyte consults per character, so a
        qualifying capture renders identically as split lines. The checks
        are staged so the hot path stays C-level: isprintable() screens
        all controls and other non-printables in one scan, isascii()
        skips the width scan entirely for ASCII text, and wcwidth() only
        ever sees the non-ASCII remainder.
        """
        if self._pyte_fed:
            return False
        if not raw_text.replace("\n", "").replace("\t", "").isprintable():
            return False
        if not raw_text.isascii():
            for chunk in _NON_ASCII.finditer(raw_text):
                if any(wcwidth(ch) != 1 for ch in chunk.group()):
                    return False
        candidate = self._merge_fast_parts(raw_text.split("\n"))
        if any(self._wraps_in_pyte(line) for line in candidate[:-1]) or (
            candidate and self._wraps_in_pyte(candidate[-1], final=True, raw=raw_text)
        ):
            return False
        # Cap the store like pyte's scrolled screen; overflow leaves the
        # top, and display pads from this invariant.
        if len(candidate) > self._screen.lines:
            del candidate[: len(candidate) - self._screen.lines]
        self._fast_lines = candidate
        return True

    def _merge_fast_parts(self, parts: list[str]) -> list[str]:
        """Join this feed's parts onto any stored fast lines."""
        if self._fast_lines is None:
            return list(parts)
        candidate = self._fast_lines[:-1]
        candidate.append(self._fast_lines[-1] + parts[0])
        candidate.extend(parts[1:])
        return candidate

    def _wraps_in_pyte(self, line: str, *, final: bool = False, raw: str = "") -> bool:
        """Whether pyte would wrap this row, disqualifying the fast path.

        A line longer than the margin wraps outright; a line exactly at
        the margin risks the deferred wrap only while more text can still
        arrive on that row, so the final part of an unterminated feed
        keeps the guard while newline-terminated rows (full-width
        separators included) admit. The merged first row is checked too:
        it grew across feeds.
        """
        width = len(line.expandtabs())
        if width > self._screen.columns:
            return True
        return width == self._screen.columns and final and not raw.endswith("\n")

    def _feed_pyte(self, text: str, err_msg: str) -> None:
        """Feed one text into pyte, resetting the screen on its errors."""
        try:
            self._stream.feed(text)
        except TypeError, ValueError, KeyError, IndexError, UnicodeDecodeError:
            logger.debug(err_msg, exc_info=True)
            self._screen.reset()

    def feed(self, raw_text: str) -> None:
        """Feed raw terminal text (with ANSI escapes) into the screen."""
        if self._try_fast_feed(raw_text):
            return
        replay = "\r\n".join(self._fast_lines) if self._fast_lines else None
        self._fast_lines = None
        self._pyte_fed = True
        if "\x1b" not in raw_text:
            # Escape-free text that failed admission (a margin-reaching
            # row, or pyte already active from an earlier frame): pyte
            # does not carriage-return on a bare LF, so the frame would
            # render cumulatively staggered; CRLF keeps the fallback
            # output identical to the fast path for the same content.
            # Only bare LFs: an existing CR must not be doubled.
            raw_text = _BARE_LF.sub("\r\n", raw_text)
        if replay:
            self._feed_pyte(replay, "pyte replay error, resetting screen")
        self._feed_pyte(raw_text, "pyte feed error, resetting screen")

    @property
    def display(self) -> list[str]:
        """Rendered lines with trailing whitespace stripped."""
        if self._fast_lines is not None:
            lines = [line.expandtabs().rstrip() for line in self._fast_lines]
            lines += [""] * (self._screen.lines - len(lines))
            return lines
        return [line.rstrip() for line in self._screen.display]

    @property
    def rendered_text(self) -> str:
        """Full rendered text with trailing blank lines trimmed."""
        lines = self.display
        last = len(lines) - 1
        while last >= 0 and not lines[last].strip():
            last -= 1
        return "\n".join(lines[: last + 1]) if last >= 0 else ""

    @property
    def cursor_row(self) -> int:
        if self._fast_lines is not None:
            # terminal_parser.py only uses this to bound trailing-blank trimming; for
            # a settled screen the last non-blank row is an equivalent bound.
            lines = self.display
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip():
                    return i
            return 0
        return self._screen.cursor.y

    def resize(self, columns: int, rows: int) -> None:
        """Resize the screen and clear content."""
        if columns < 1 or rows < 1:
            return
        self._screen.resize(rows, columns)
        self._screen.reset()
        self._fast_lines = None
        self._pyte_fed = False

    def reset(self) -> None:
        """Clear all screen state for reuse."""
        self._screen.reset()
        self._fast_lines = None
        self._pyte_fed = False
