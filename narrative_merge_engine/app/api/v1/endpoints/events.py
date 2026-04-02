"""
Event extraction endpoints.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, EventSvc
from app.models.schemas.entities import EventRead

router = APIRouter(prefix="/events", tags=["Events"])


@router.post(
    "/testimonies/{testimony_id}/extract",
    response_model=list[EventRead],
    status_code=status.HTTP_201_CREATED,
    summary="Extract events from a testimony",
)
async def extract_events(
    testimony_id: uuid.UUID,
    svc: EventSvc,
    _user: CurrentUser,
) -> list[EventRead]:
    """Run LLM event extraction on a previously ingested testimony."""
    return await svc.extract_events(testimony_id)


@router.get(
    "/testimonies/{testimony_id}",
    response_model=list[EventRead],
    summary="List events for a testimony",
)
async def list_events(
    testimony_id: uuid.UUID,
    svc: EventSvc,
    _user: CurrentUser,
) -> list[EventRead]:
    return await svc.list_events(testimony_id)


@router.get("/{event_id}", response_model=EventRead, summary="Get a single event")
async def get_event(
    event_id: uuid.UUID,
    svc: EventSvc,
    _user: CurrentUser,
) -> EventRead:
    return await svc.get_event(event_id)
