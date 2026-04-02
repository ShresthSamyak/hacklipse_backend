"""
Testimony endpoints — ingestion and management.
"""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, TestimonySvc
from app.models.schemas.testimony import (
    TestimonyCreate,
    TestimonyList,
    TestimonyRead,
    TestimonyUpdate,
)

router = APIRouter(prefix="/testimonies", tags=["Testimonies"])


@router.post(
    "/",
    response_model=TestimonyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a new testimony",
)
async def ingest_testimony(
    payload: TestimonyCreate,
    svc: TestimonySvc,
    _user: CurrentUser,
) -> TestimonyRead:
    return await svc.ingest(payload)


@router.get("/", response_model=TestimonyList, summary="List testimonies (paginated)")
async def list_testimonies(
    svc: TestimonySvc,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> TestimonyList:
    items, total = await svc.list(page=page, page_size=page_size)
    return TestimonyList(items=items, total=total, page=page, page_size=page_size)


@router.get("/{testimony_id}", response_model=TestimonyRead, summary="Get a testimony by ID")
async def get_testimony(
    testimony_id: uuid.UUID,
    svc: TestimonySvc,
    _user: CurrentUser,
) -> TestimonyRead:
    return await svc.get(testimony_id)


@router.patch("/{testimony_id}", response_model=TestimonyRead, summary="Partially update a testimony")
async def update_testimony(
    testimony_id: uuid.UUID,
    payload: TestimonyUpdate,
    svc: TestimonySvc,
    _user: CurrentUser,
) -> TestimonyRead:
    return await svc.update(testimony_id, payload)


@router.delete(
    "/{testimony_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a testimony",
)
async def delete_testimony(
    testimony_id: uuid.UUID,
    svc: TestimonySvc,
    _user: CurrentUser,
) -> None:
    await svc.delete(testimony_id)
