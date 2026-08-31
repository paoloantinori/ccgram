"""Base types for TTS synthesis providers.

Defines the Protocol and result types that all SpeechSynthesizer implementations
must follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TtsSynthesisError(Exception):
    """Raised by any SpeechSynthesizer when synthesis fails in a known way.

    ``status_code``/``retry_after`` are set by HTTP-backed synthesizers on
    rate-limit responses so callers can retry with backoff instead of
    parsing the message text.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class TtsAudio:
    """Synthesized TTS audio payload."""

    data: bytes
    filename: str = "reply.mp3"


class SpeechSynthesizer(Protocol):
    """Protocol for TTS synthesis backends."""

    async def synthesize(self, text: str) -> TtsAudio:
        """Synthesize speech from plain text, returning audio bytes.

        Raises TtsSynthesisError on known backend failures.
        """
        ...
