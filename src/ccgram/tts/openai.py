"""OpenAI TTS synthesis backend.

Uses httpx to call the OpenAI audio/speech endpoint. No openai SDK required.
"""

from __future__ import annotations

import httpx

from .base import TtsAudio, TtsSynthesisError

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_RATE_LIMITED_STATUS = 429


class OpenAITtsSynthesizer:
    """Speech synthesizer backed by the OpenAI TTS API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        voice: str,
        base_url: str | None = None,
        response_format: str = "mp3",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._base_url = (base_url or _OPENAI_BASE_URL).rstrip("/")
        self._response_format = response_format
        self._timeout = timeout

    async def synthesize(self, text: str) -> TtsAudio:
        """Synthesize speech via the OpenAI audio/speech endpoint.

        Raises:
            ValueError: if text is empty.
            TtsSynthesisError: on API or network failure.
        """
        if not text.strip():
            msg = "Cannot synthesize empty text"
            raise ValueError(msg)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/audio/speech",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "input": text,
                        "voice": self._voice,
                        "response_format": self._response_format,
                    },
                    timeout=self._timeout,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                msg = f"TTS failed: {status} {exc.response.text}"
                retry_after: float | None = None
                if status == _RATE_LIMITED_STATUS:
                    # The LAN backend returns Retry-After (seconds); honor
                    # it so callers can back off instead of hammering.
                    header = exc.response.headers.get("Retry-After", "")
                    try:
                        retry_after = float(header) if header else None
                    except ValueError:
                        retry_after = None
                raise TtsSynthesisError(
                    msg, status_code=status, retry_after=retry_after
                ) from exc
            except httpx.HTTPError as exc:
                # httpx timeout exceptions stringify to "": name the class
                # or the failure reaches the user as an empty reason.
                msg = f"TTS failed: {type(exc).__name__}: {exc}"
                raise TtsSynthesisError(msg) from exc

        audio = response.content
        if not audio:
            raise TtsSynthesisError("No audio bytes received from OpenAI TTS")
        return TtsAudio(data=audio, filename=f"reply.{self._response_format}")
