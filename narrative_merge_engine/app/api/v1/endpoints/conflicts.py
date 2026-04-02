"""
Conflict detection endpoints.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import ConflictSvc, CurrentUser
from app.models.schemas.entities import ConflictRead, ConflictResolve

router = APIRouter(prefix="/conflicts", tags=["Conflicts"])


@router.post(
    "/timelines/{timeline_id}/detect",
    response_model=list[ConflictRead],
    status_code=status.HTTP_201_CREATED,
    summary="Detect conflicts in a timeline",
)
async def detect_conflicts(
    timeline_id: uuid.UUID,
    svc: ConflictSvc,
    _user: CurrentUser,
) -> list[ConflictRead]:
    """Run LLM conflict detection across all events in a timeline."""
    return await svc.detect_conflicts(timeline_id)


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
