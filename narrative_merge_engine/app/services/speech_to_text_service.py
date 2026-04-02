"""
Speech-to-Text (ASR) Service
==============================

Converts raw audio bytes into a text transcript.

Provider: Groq — Whisper Large V3 Turbo
  - Ultra-fast inference (~216× realtime)
  - Supports 57+ languages (auto-detect if ASR_LANGUAGE is blank)
  - Accepts: flac, mp3, mp4, mpeg, mpga, m4a, ogg, opus, wav, webm
  - Max file size: 25 MB (controlled by ASR_MAX_FILE_BYTES in settings)

API: Uses Groq's audio transcription endpoint via the openai SDK
     (Groq is OpenAI-compatible for audio too)

Architecture:
  ┌──────────────────┐
  │  Audio bytes/file │
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │  Input validation │  size check, format hint
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │  Groq Whisper API │  async HTTP
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │  TranscriptResult │  text + detected_language + duration_s + metadata
  └──────────────────┘

Usage:
    svc = SpeechToTextService()
    result = await svc.transcribe(audio_bytes, filename="testimony.wav")
    print(result.text)
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Groq's OpenAI-compatible base URL (same as LLM provider)
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Supported audio formats by Groq Whisper
_SUPPORTED_FORMATS = frozenset({
    "flac", "mp3", "mp4", "mpeg", "mpga", "m4a",
    "ogg", "opus", "wav", "webm",
})


@dataclass
class TranscriptResult:
    """Structured output from the STT service."""
    text: str
    detected_language: str = ""
    duration_seconds: float | None = None
    model: str = ""
    provider: str = "groq"
    elapsed_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class SpeechToTextService:
    """
    Async Speech-to-Text service backed by Groq Whisper.

    Initialises lazily — the Groq/OpenAI client is created on first use.
    """

    def __init__(self) -> None:
        self._client = None  # lazy init

    def _get_client(self):
        """Lazy-initialise the AsyncOpenAI client pointed at Groq."""
        if self._client is not None:
            return self._client
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "openai package is required for SpeechToTextService. "
                "Install it with: pip install openai"
            ) from exc

        api_key = settings.LLM_API_KEY  # same Groq key as LLM
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Set it in .env to use the STT service."
            )

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=_GROQ_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        return self._client

    # ── Public API ───────────────────────────────────────────────────────────

    async def transcribe(
        self,
        audio: bytes | BinaryIO,
        *,
        filename: str = "audio.wav",
        language: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptResult:
        """
        Transcribe audio to text.

        Args:
            audio:    Raw audio bytes or a file-like object.
            filename: Filename hint for format detection (e.g. "testimony.mp3").
            language: ISO 639-1 language code (e.g. "en", "hi").
                      Blank/None → Whisper auto-detects.
            prompt:   Optional prompt to guide Whisper's vocabulary/style.
                      Useful for domain-specific terms or expected speakers.

        Returns:
            TranscriptResult with .text and metadata.

        Raises:
            ValidationError: if the audio is too large or format is unsupported.
        """
        start = time.monotonic()

        # Normalise to bytes
        if isinstance(audio, (bytes, bytearray)):
            audio_bytes = bytes(audio)
        else:
            audio_bytes = audio.read()  # type: ignore[union-attr]

        self._validate(audio_bytes, filename)

        model = settings.ASR_MODEL
        lang = language or settings.ASR_LANGUAGE or None

        logger.info(
            "STT transcription started",
            model=model,
            filename=filename,
            size_bytes=len(audio_bytes),
            language=lang or "auto",
        )

        client = self._get_client()

        try:
            file_tuple = (filename, io.BytesIO(audio_bytes))

            kwargs: dict = dict(
                model=model,
                file=file_tuple,
                response_format="verbose_json",  # gives us language + duration
            )
            if lang:
                kwargs["language"] = lang
            if prompt:
                kwargs["prompt"] = prompt

            response = await client.audio.transcriptions.create(**kwargs)

        except Exception as exc:
            logger.error("Groq Whisper transcription failed", error=str(exc))
            raise RuntimeError(f"STT transcription failed: {exc}") from exc

        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        text = getattr(response, "text", "") or ""
        detected_lang = getattr(response, "language", "") or ""
        duration = getattr(response, "duration", None)

        result = TranscriptResult(
            text=text.strip(),
            detected_language=detected_lang,
            duration_seconds=duration,
            model=model,
            provider="groq",
            elapsed_ms=elapsed_ms,
            metadata={
                "filename": filename,
                "size_bytes": len(audio_bytes),
                "language_hint": lang,
            },
        )

        logger.info(
            "STT transcription completed",
            elapsed_ms=elapsed_ms,
            detected_language=detected_lang,
            text_length=len(text),
            duration_seconds=duration,
        )

        return result

    async def transcribe_file(self, path: str | Path) -> TranscriptResult:
        """Convenience wrapper: transcribe a local file by path."""
        path = Path(path)
        audio_bytes = path.read_bytes()
        return await self.transcribe(audio_bytes, filename=path.name)

    # ── Validation ───────────────────────────────────────────────────────────

    def _validate(self, audio_bytes: bytes, filename: str) -> None:
        """Check file size and format before sending to Groq."""
        size = len(audio_bytes)
        if size == 0:
            raise ValidationError("Audio file is empty")
        if size > settings.ASR_MAX_FILE_BYTES:
            raise ValidationError(
                f"Audio file too large: {size} bytes "
                f"(max {settings.ASR_MAX_FILE_BYTES} bytes / 25 MB)",
                detail={"size_bytes": size, "max_bytes": settings.ASR_MAX_FILE_BYTES},
            )
        ext = Path(filename).suffix.lstrip(".").lower()
        if ext and ext not in _SUPPORTED_FORMATS:
            raise ValidationError(
                f"Unsupported audio format: .{ext}",
                detail={"supported": sorted(_SUPPORTED_FORMATS)},
            )


# ── Module-level singleton ────────────────────────────────────────────────────

_stt_instance: SpeechToTextService | None = None


def get_stt_service() -> SpeechToTextService:
    """Return the shared STT service singleton."""
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = SpeechToTextService()
    return _stt_instance
