"""
Demo Pipeline endpoint — the all-in-one hackathon showcase route.

POST /demo/run          → full 5-stage pipeline (audio or text input)
POST /demo/run-preview  → fast preview (skips timeline + conflict LLM calls)
GET  /demo/sample       → returns a pre-built sample result (zero LLM calls)
GET  /demo/health       → confirms all pipeline services are wired correctly
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBDep, LLMDep, SttSvc
from app.core.logging import get_logger
from app.services.demo_pipeline import (
    DemoPipeline,
    PipelineResult,
    PipelineStatus,
    _DEMO_SAMPLE_BRANCHES,
    _DEMO_SAMPLE_TRANSCRIPT,
    build_pipeline,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/demo", tags=["Demo Pipeline"])


# ── Request / response schemas ────────────────────────────────────────────────

class TextRunRequest(BaseModel):
    """Request body for text-based pipeline runs."""

    text: str = Field(
        ...,
        min_length=10,
        description="Raw testimony text. Can be messy, uncertain, or multilingual.",
        examples=["I entered around 9, maybe 10 at night... there was someone near the table."],
    )
    demo_mode: bool = Field(
        default=True,
        description="Force temperature=0 and verbose stage logging. Default True for demos.",
    )
    fast_preview: bool = Field(
        default=False,
        description=(
            "Skip timeline reasoning and conflict detection LLM calls. "
            "Returns events only. Cuts latency from ~15 s to ~4 s."
        ),
    )
    branches: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional: provide multiple testimony texts keyed by witness label. "
            "If provided, each value is independently extracted and then compared. "
            "Example: {\"Witness_A\": \"...\", \"Witness_B\": \"...\"}"
        ),
    )


class PipelineResponse(BaseModel):
    """Structured demo pipeline response."""
    pipeline_id: str
    transcript: str
    events: list[dict]
    timeline: dict
    conflicts: dict
    status: str
    errors: list[str]
    stage_timings_ms: dict[str, float]
    demo_mode: bool
    fast_preview: bool


def _to_response(result: PipelineResult) -> PipelineResponse:
    return PipelineResponse(**result.to_dict())


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/run",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Run full 5-stage pipeline from audio or text",
    description=(
        "The main demo endpoint. Accepts either an audio file (multipart) "
        "or JSON text input and runs the complete Narrative Merge Engine pipeline: "
        "STT → Event Extraction → Timeline → Conflict Detection → Response. "
        "Never crashes — each stage has timeout protection, one retry, and a fallback. "
        "status field reflects worst stage outcome: success | partial | fallback."
    ),
)
async def run_pipeline_audio(
    db: DBDep,
    llm: LLMDep,
    stt_svc: SttSvc,
    _user: CurrentUser,
    file: UploadFile | None = File(default=None, description="Optional audio file"),
    text: str = Form(default="", description="Fallback text if no audio provided"),
    demo_mode: bool = Form(default=True),
    fast_preview: bool = Form(default=False),
) -> PipelineResponse:
    """Accepts multipart form with optional audio file + text fallback."""
    pipeline = build_pipeline(db=db, llm=llm, stt_svc=stt_svc)

    audio_bytes: bytes | None = None
    filename = "audio.wav"

    if file and file.filename:
        audio_bytes = await file.read()
        filename = file.filename

    result = await pipeline.run(
        audio=audio_bytes,
        filename=filename,
        text=text or None,
        demo_mode=demo_mode,
        fast_preview=fast_preview,
    )
    return _to_response(result)


@router.post(
    "/run-text",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Run full pipeline from text input (JSON body)",
    description=(
        "JSON-body version of /demo/run — easier to call from Postman / UI. "
        "Supports multi-witness mode via the 'branches' field."
    ),
)
async def run_pipeline_text(
    payload: TextRunRequest,
    db: DBDep,
    llm: LLMDep,
    stt_svc: SttSvc,
    _user: CurrentUser,
) -> PipelineResponse:
    pipeline = build_pipeline(db=db, llm=llm, stt_svc=stt_svc)
    result = await pipeline.run(
        text=payload.text,
        demo_mode=payload.demo_mode,
        fast_preview=payload.fast_preview,
        branches_override=payload.branches,
    )
    return _to_response(result)


@router.post(
    "/run-preview",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Fast preview — events only (no timeline/conflict LLM calls)",
    description=(
        "Runs STT (if audio) and event extraction only. "
        "Returns immediately after extraction with a trivial timeline. "
        "Target latency: < 5 seconds. Use for live UI streaming feedback."
    ),
)
async def run_preview(
    payload: TextRunRequest,
    db: DBDep,
    llm: LLMDep,
    stt_svc: SttSvc,
    _user: CurrentUser,
) -> PipelineResponse:
    pipeline = build_pipeline(db=db, llm=llm, stt_svc=stt_svc)
    result = await pipeline.run(
        text=payload.text,
        demo_mode=payload.demo_mode,
        fast_preview=True,  # always fast
        branches_override=payload.branches,
    )
    return _to_response(result)


@router.get(
    "/sample",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Return pre-built sample pipeline result (zero LLM calls)",
    description=(
        "Returns the canonical 2-witness demo scenario with a known Git-style conflict. "
        "Zero latency. Use as a demo backup if the LLM API is unavailable."
    ),
)
async def get_sample(_user: CurrentUser) -> PipelineResponse:
    """
    Returns the hardcoded 2-witness sample scenario.
    Useful as a demo backup when the API key is rate-limited or unavailable.
    """
    sample_conflicts = {
        "confirmed_events": [{"event_id": "noise", "description": "Heard a loud noise"}],
        "conflicts": [
            {
                "conflict_block": (
                    "<<<<<<< Witness_A\n"
                    "Entered the building at approximately 9 PM\n"
                    "=======\n"
                    "Entered the building at approximately 10 PM\n"
                    ">>>>>>> Witness_B"
                ),
                "type": "temporal",
                "impact": "high",
            },
            {
                "conflict_block": (
                    "<<<<<<< Witness_A\n"
                    "Saw a person near the table\n"
                    "=======\n"
                    "Saw no one in the room\n"
                    ">>>>>>> Witness_B"
                ),
                "type": "logical",
                "impact": "high",
            },
        ],
        "uncertain_events": [],
        "next_question": {
            "question": (
                "What were you doing in the 30 minutes immediately before you entered the building?"
            ),
            "reason": (
                "The entry time is the temporal anchor for the entire case. "
                "Resolving it reframes every subsequent event."
            ),
        },
        "conflict_count": 2,
        "has_conflicts": True,
    }

    sample_events = (
        list(_DEMO_SAMPLE_BRANCHES["Witness_A"])
        + list(_DEMO_SAMPLE_BRANCHES["Witness_B"])
    )

    return PipelineResponse(
        pipeline_id="demo-sample-00000000",
        transcript=_DEMO_SAMPLE_TRANSCRIPT,
        events=sample_events,
        timeline={
            "confirmed_sequence": [],
            "probable_sequence": [
                {"event_id": "a1", "description": "Entered the building", "position": 0, "placement_confidence": "uncertain"},
                {"event_id": "a2", "description": "Saw a person near the table", "position": 1, "placement_confidence": "probable"},
                {"event_id": "a3", "description": "Heard a loud noise", "position": 2, "placement_confidence": "confirmed"},
            ],
            "uncertain_events": [],
            "event_count": len(sample_events),
            "confidence_summary": {"confirmed": 0, "probable": 3, "uncertain": 0},
            "temporal_links": [],
            "metadata": {"sample": True},
        },
        conflicts=sample_conflicts,
        status=PipelineStatus.SUCCESS.value,
        errors=[],
        stage_timings_ms={"stt_ms": 0, "extraction_ms": 0, "timeline_ms": 0, "conflicts_ms": 0, "total_ms": 0},
        demo_mode=True,
        fast_preview=False,
    )


@router.get(
    "/health",
    summary="Pipeline health check",
    status_code=status.HTTP_200_OK,
)
async def demo_health(_user: CurrentUser) -> dict:
    """Confirms all services the pipeline depends on can be imported and instantiated."""
    checks: dict[str, str] = {}

    try:
        from app.services.event_extraction_service import EventExtractionService
        checks["event_extraction"] = "ok"
    except Exception as exc:
        checks["event_extraction"] = f"ERROR: {exc}"

    try:
        from app.services.timeline_reconstruction_service import TimelineReconstructionService
        checks["timeline_reconstruction"] = "ok"
    except Exception as exc:
        checks["timeline_reconstruction"] = f"ERROR: {exc}"

    try:
        from app.services.conflict_detection_service import ConflictDetectionService
        checks["conflict_detection"] = "ok"
    except Exception as exc:
        checks["conflict_detection"] = f"ERROR: {exc}"

    try:
        from app.services.speech_to_text_service import SpeechToTextService
        checks["speech_to_text"] = "ok"
    except Exception as exc:
        checks["speech_to_text"] = f"ERROR: {exc}"

    try:
        from app.core.config import settings
        checks["groq_key_set"] = "ok" if settings.LLM_API_KEY else "WARNING: LLM_API_KEY not set"
        checks["asr_model"] = settings.ASR_MODEL
        checks["llm_model"] = settings.LLM_MODEL
    except Exception as exc:
        checks["config"] = f"ERROR: {exc}"

    all_ok = all(v == "ok" or not v.startswith("ERROR") for v in checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }
