"""
Conflict detection & merge endpoints.

Exposes:
  - POST /conflicts/timelines/{id}/detect       → full pipeline (load → detect → persist)
  - POST /conflicts/detect-preview               → preview from raw branches (no DB)
  - POST /conflicts/detect-strict                → strict mode (zero hallucination, no DB)
  - GET  /conflicts/timelines/{id}               → list persisted conflicts
  - PATCH /conflicts/{id}/resolve                → mark a conflict as resolved
"""

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import ConflictSvc, CurrentUser
from app.models.schemas.conflict_detection import ConflictDetectionResult
from app.models.schemas.conflict_strict import StrictConflictResult
from app.models.schemas.entities import ConflictRead, ConflictResolve

router = APIRouter(prefix="/conflicts", tags=["Conflicts"])


# ── Request schemas ──────────────────────────────────────────────────────────

class DetectPreviewRequest(BaseModel):
    """Request body for the preview and strict conflict detection endpoints."""

    branches: dict[str, list[dict]] = Field(
        ...,
        description=(
            "Map of branch_label → list of event dicts.  Each branch "
            "represents one witness/testimony.  Event dicts should have "
            "at minimum: id, description.  Optional: time, location, actors."
        ),
        examples=[
            {
                "Witness_A": [
                    {"id": "a1", "description": "Entered at 9 PM", "time": "9 PM", "location": "entrance"},
                    {"id": "a2", "description": "Saw a person near the table", "time": None, "location": "dining room"},
                    {"id": "a3", "description": "Heard a loud noise", "time": "9:30 PM"},
                ],
                "Witness_B": [
                    {"id": "b1", "description": "Entered at 10 PM", "time": "10 PM", "location": "entrance"},
                    {"id": "b2", "description": "Saw no one in the room", "time": None, "location": "dining room"},
                    {"id": "b3", "description": "Heard a loud noise", "time": "10:15 PM"},
                ],
            }
        ],
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/timelines/{timeline_id}/detect",
    response_model=list[ConflictRead],
    status_code=status.HTTP_201_CREATED,
    summary="Detect conflicts in a timeline and persist results",
    description=(
        "Loads all events from a reconstructed timeline, groups them by "
        "testimony branch, runs Git-style conflict detection (LLM merge "
        "analysis → impact scoring → next-best-question), and persists "
        "each detected conflict to the database for resolution tracking."
    ),
)
async def detect_conflicts(
    timeline_id: uuid.UUID,
    svc: ConflictSvc,
    _user: CurrentUser,
) -> list[ConflictRead]:
    """Run LLM conflict detection across all events in a timeline."""
    return await svc.detect_conflicts(timeline_id)


@router.post(
    "/detect-preview",
    response_model=ConflictDetectionResult,
    status_code=status.HTTP_200_OK,
    summary="Preview conflict detection from raw branches (no persistence)",
    description=(
        "Runs the full Git-style merge analysis on raw testimony branches "
        "without loading from or writing to the database.  Returns the "
        "complete ConflictDetectionResult with merge blocks, impact scores, "
        "partial merge output, next-best-question, and conflict graph."
    ),
)
async def detect_preview(
    payload: DetectPreviewRequest,
    svc: ConflictSvc,
    _user: CurrentUser,
) -> ConflictDetectionResult:
    return await svc.detect_from_events_preview(payload.branches)


@router.post(
    "/detect-strict",
    response_model=StrictConflictResult,
    status_code=status.HTTP_200_OK,
    summary="Strict-mode conflict detection (zero hallucination)",
    description=(
        "Runs zero-hallucination, zero-inference conflict detection. "
        "The LLM acts as a pure comparison engine: it flags ONLY clear, "
        "directly observable conflicts.  Returns a minimal JSON output "
        "with no impact scoring, no conflict graph, and no reasoning. "
        "Uses temperature=0 for deterministic output.  Suitable for "
        "automated pipelines, CI checks, and forensic audit trails."
    ),
)
async def detect_strict(
    payload: DetectPreviewRequest,
    svc: ConflictSvc,
    _user: CurrentUser,
) -> StrictConflictResult:
    return await svc.detect_strict(payload.branches)


@router.get(
    "/timelines/{timeline_id}",
    response_model=list[ConflictRead],
    summary="List conflicts for a timeline",
)
async def list_conflicts(
    timeline_id: uuid.UUID,
    svc: ConflictSvc,
    _user: CurrentUser,
) -> list[ConflictRead]:
    return await svc.list_conflicts(timeline_id)


@router.patch(
    "/{conflict_id}/resolve",
    response_model=ConflictRead,
    summary="Mark a conflict as resolved",
)
async def resolve_conflict(
    conflict_id: uuid.UUID,
    payload: ConflictResolve,
    svc: ConflictSvc,
    _user: CurrentUser,
) -> ConflictRead:
    return await svc.resolve_conflict(conflict_id, payload)
