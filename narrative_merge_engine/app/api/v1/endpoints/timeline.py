"""
Timeline reconstruction endpoints.

Exposes:
  - POST /timelines/                       → full pipeline (load events → reason → persist)
  - POST /timelines/reconstruct-preview    → reason from raw events (no DB persistence)
  - GET  /timelines/{id}                   → get persisted timeline
  - GET  /timelines/                       → list all timelines
"""

import uuid

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, TimelineSvc
from app.models.schemas.entities import TimelineCreate, TimelineRead
from app.models.schemas.timeline_reconstruction import TimelineReconstructionResult

router = APIRouter(prefix="/timelines", tags=["Timelines"])


# ── Request schemas ──────────────────────────────────────────────────────────

class ReconstructPreviewRequest(BaseModel):
    """Request body for the preview reconstruction endpoint."""

    events: list[dict] = Field(
        ...,
        min_length=1,
        description=(
            "List of extracted event dicts. Each should have at minimum: "
            "id, description.  Optional: time, time_uncertainty, location, "
            "actors, confidence."
        ),
        examples=[
            [
                {
                    "id": "evt-A",
                    "description": "Entered the room",
                    "time": "9 PM",
                    "time_uncertainty": "approximate",
                    "location": "room",
                    "actors": ["witness"],
                    "confidence": 0.7,
                },
                {
                    "id": "evt-B",
                    "description": "Heard a loud noise",
                    "time": None,
                    "time_uncertainty": "relative",
                    "location": None,
                    "actors": ["witness"],
                    "confidence": 0.6,
                },
            ]
        ],
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=TimelineRead,
    status_code=status.HTTP_201_CREATED,
    summary="Reconstruct a timeline from multiple testimonies",
    description=(
        "Loads all events for the given testimony IDs from the database, "
        "runs the full reasoning pipeline (LLM temporal analysis → "
        "confidence classification → reasoning → temporal links), "
        "and persists the resulting timeline."
    ),
)
async def reconstruct_timeline(
    payload: TimelineCreate,
    svc: TimelineSvc,
    _user: CurrentUser,
) -> TimelineRead:
    return await svc.reconstruct(payload)


@router.post(
    "/reconstruct-preview",
    response_model=TimelineReconstructionResult,
    status_code=status.HTTP_200_OK,
    summary="Preview timeline reconstruction from raw events (no persistence)",
    description=(
        "Runs the reasoning pipeline on raw event dicts without loading "
        "from or writing to the database.  Returns the full "
        "TimelineReconstructionResult with confirmed/probable/uncertain "
        "tiers, per-event reasoning, and temporal links."
    ),
)
async def reconstruct_preview(
    payload: ReconstructPreviewRequest,
    svc: TimelineSvc,
    _user: CurrentUser,
) -> TimelineReconstructionResult:
    return await svc.reconstruct_from_events(payload.events)


@router.get(
    "/{timeline_id}",
    response_model=TimelineRead,
    summary="Get a timeline by ID",
)
async def get_timeline(
    timeline_id: uuid.UUID,
    svc: TimelineSvc,
    _user: CurrentUser,
) -> TimelineRead:
    return await svc.get(timeline_id)


@router.get(
    "/",
    response_model=list[TimelineRead],
    summary="List all timelines",
)
async def list_timelines(
    svc: TimelineSvc,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[TimelineRead]:
    items, _ = await svc.list(page=page, page_size=page_size)
    return items
