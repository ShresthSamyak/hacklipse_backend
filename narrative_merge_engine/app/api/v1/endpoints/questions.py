"""
Question generation endpoints.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, QuestionSvc
from app.models.schemas.entities import QuestionAnswer, QuestionRead

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.post(
    "/timelines/{timeline_id}/generate",
    response_model=list[QuestionRead],
    status_code=status.HTTP_201_CREATED,
    summary="Generate clarifying questions for a timeline",
)
async def generate_questions(
    timeline_id: uuid.UUID,
    svc: QuestionSvc,
    _user: CurrentUser,
) -> list[QuestionRead]:
    return await svc.generate_questions(timeline_id)


@router.get(
    "/timelines/{timeline_id}",
    response_model=list[QuestionRead],
    summary="List questions for a timeline",
)
async def list_questions(
    timeline_id: uuid.UUID,
    svc: QuestionSvc,
    _user: CurrentUser,
) -> list[QuestionRead]:
    return await svc.list_questions(timeline_id)


@router.patch(
    "/{question_id}/answer",
    response_model=QuestionRead,
    summary="Record an answer to a generated question",
)
async def answer_question(
    question_id: uuid.UUID,
    payload: QuestionAnswer,
    svc: QuestionSvc,
    _user: CurrentUser,
) -> QuestionRead:
    return await svc.answer_question(question_id, payload)
