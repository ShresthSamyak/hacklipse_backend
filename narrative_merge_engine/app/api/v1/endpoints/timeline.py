"""
Timeline reconstruction endpoints.
"""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, TimelineSvc
from app.models.schemas.entities import TimelineCreate, TimelineRead

router = APIRouter(prefix="/timelines", tags=["Timelines"])


@router.post(
    "/",
    response_model=TimelineRead,
    status_code=status.HTTP_201_CREATED,
    summary="Reconstruct a timeline from multiple testimonies",
)
async def reconstruct_timeline(
    payload: TimelineCreate,
    svc: TimelineSvc,
    _user: CurrentUser,
) -> TimelineRead:
    return await svc.reconstruct(payload)


@router.get("/{timeline_id}", response_model=TimelineRead, summary="Get a timeline by ID")
async def get_timeline(
    timeline_id: uuid.UUID,
    svc: TimelineSvc,
    _user: CurrentUser,
) -> TimelineRead:
    return await svc.get(timeline_id)


@router.get("/", response_model=list[TimelineRead], summary="List all timelines")
async def list_timelines(
    svc: TimelineSvc,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[TimelineRead]:
    items, _ = await svc.list(page=page, page_size=page_size)
    return items
