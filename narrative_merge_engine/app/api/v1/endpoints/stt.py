"""
Speech-to-Text (transcription) endpoints.

Exposes:
  - POST /stt/transcribe          → transcribe audio bytes (multipart upload)
  - POST /stt/transcribe-url      → transcribe from a publicly accessible URL
  - GET  /stt/health              → check STT provider reachability
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SttSvc
from app.core.logging import get_logger
from app.services.speech_to_text_service import TranscriptResult

logger = get_logger(__name__)

router = APIRouter(prefix="/stt", tags=["Speech-to-Text"])

# Maximum URL-fetched audio size: same as file-upload limit
_MAX_URL_BYTES = 26_214_400  # 25 MB


# ── Response schema ───────────────────────────────────────────────────────────

class TranscriptResponse(BaseModel):
    """Public transcript response shape."""
    text: str
    detected_language: str = ""
    duration_seconds: float | None = None
    model: str
    provider: str
    elapsed_ms: float


def _to_response(result: TranscriptResult) -> TranscriptResponse:
    return TranscriptResponse(
        text=result.text,
        detected_language=result.detected_language,
        duration_seconds=result.duration_seconds,
        model=result.model,
        provider=result.provider,
        elapsed_ms=result.elapsed_ms,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/transcribe",
    response_model=TranscriptResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe audio (file upload)",
    description=(
        "Upload an audio file and receive a text transcript. "
        "Backed by Groq Whisper Large V3 Turbo (~216× realtime speed). "
        "Supported formats: flac, mp3, mp4, mpeg, mpga, m4a, ogg, opus, wav, webm. "
        "Max file size: 25 MB."
    ),
)
async def transcribe_audio(
    svc: SttSvc,
    _user: CurrentUser,
    file: UploadFile = File(..., description="Audio file to transcribe"),
    language: str = Form(
        default="",
        description="ISO 639-1 language code (e.g. 'en', 'hi'). Leave blank for auto-detect.",
    ),
    prompt: str = Form(
        default="",
        description=(
            "Optional guidance for Whisper (e.g. domain terms, speaker names). "
            "Helps with accuracy for domain-specific vocabulary."
        ),
    ),
) -> TranscriptResponse:
    audio_bytes = await file.read()
    result = await svc.transcribe(
        audio_bytes,
        filename=file.filename or "audio.wav",
        language=language or None,
        prompt=prompt or None,
    )
    return _to_response(result)


class TranscribeUrlRequest(BaseModel):
    """Request body for URL-based transcription."""
    url: str = Field(..., description="Publicly accessible URL to an audio file")
    language: str = Field(default="", description="ISO 639-1 language code — blank = auto")
    prompt: str = Field(default="", description="Optional Whisper guidance prompt")


@router.post(
    "/transcribe-url",
    response_model=TranscriptResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe audio from URL",
    description=(
        "Provide a publicly accessible audio URL. The server downloads the file "
        "and sends it to Groq Whisper. Max file size: 25 MB."
    ),
)
async def transcribe_from_url(
    payload: TranscribeUrlRequest,
    svc: SttSvc,
    _user: CurrentUser,
) -> TranscriptResponse:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            head = await client.head(payload.url)
            content_length = int(head.headers.get("content-length", 0))
            if content_length > _MAX_URL_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Remote file too large: {content_length} bytes (max 25 MB)",
                )
            resp = await client.get(payload.url)
            resp.raise_for_status()
            audio_bytes = resp.content
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to fetch audio from URL: {exc}",
        )

    filename = payload.url.split("/")[-1].split("?")[0] or "audio.wav"
    result = await svc.transcribe(
        audio_bytes,
        filename=filename,
        language=payload.language or None,
        prompt=payload.prompt or None,
    )
    return _to_response(result)


@router.get(
    "/health",
    summary="STT provider health check",
    status_code=status.HTTP_200_OK,
)
async def stt_health(_user: CurrentUser) -> dict:
    """Ping the STT provider (Groq) to confirm reachability."""
    try:
        from openai import AsyncOpenAI  # type: ignore[import]
        from app.core.config import settings

        client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            timeout=10,
        )
        models = await client.models.list()
        model_ids = [m.id for m in models.data] if hasattr(models, "data") else []
        return {
            "status": "ok",
            "provider": "groq",
            "model": settings.ASR_MODEL,
            "available_models_count": len(model_ids),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"STT provider unreachable: {exc}",
        )
