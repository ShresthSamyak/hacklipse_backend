"""
FastAPI dependency injection.
All shared request-scoped dependencies are defined here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.orchestrator import LLMOrchestrator, get_orchestrator
from app.core.security import decode_access_token
from app.db.session import get_db
from app.services.conflict_detection_service import ConflictDetectionService
from app.services.event_extraction_service import EventExtractionService
from app.services.question_generation_service import QuestionGenerationService
from app.services.speech_to_text_service import SpeechToTextService, get_stt_service
from app.services.testimony_service import TestimonyIngestionService
from app.services.timeline_reconstruction_service import TimelineReconstructionService

# ---------------------------------------------------------------------------
# Type aliases for cleaner endpoint signatures
# ---------------------------------------------------------------------------

DBDep = Annotated[AsyncSession, Depends(get_db)]
LLMDep = Annotated[LLMOrchestrator, Depends(get_orchestrator)]


# ---------------------------------------------------------------------------
# Auth (JWT bearer token)
# ---------------------------------------------------------------------------

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user() -> dict:
    """
    Bypasses JWT completely for local development / hackathon testing.
    """
    return {"user": "demo"}


CurrentUser = Annotated[dict, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# Service dependencies
# ---------------------------------------------------------------------------

def get_testimony_service(db: DBDep, llm: LLMDep) -> TestimonyIngestionService:
    return TestimonyIngestionService(db=db, llm=llm)


def get_event_service(db: DBDep, llm: LLMDep) -> EventExtractionService:
    return EventExtractionService(db=db, llm=llm)


def get_timeline_service(db: DBDep, llm: LLMDep) -> TimelineReconstructionService:
    return TimelineReconstructionService(db=db, llm=llm)


def get_conflict_service(db: DBDep, llm: LLMDep) -> ConflictDetectionService:
    return ConflictDetectionService(db=db, llm=llm)


def get_question_service(db: DBDep, llm: LLMDep) -> QuestionGenerationService:
    return QuestionGenerationService(db=db, llm=llm)


TestimonySvc = Annotated[TestimonyIngestionService, Depends(get_testimony_service)]
EventSvc = Annotated[EventExtractionService, Depends(get_event_service)]
TimelineSvc = Annotated[TimelineReconstructionService, Depends(get_timeline_service)]
ConflictSvc = Annotated[ConflictDetectionService, Depends(get_conflict_service)]
QuestionSvc = Annotated[QuestionGenerationService, Depends(get_question_service)]
SttSvc = Annotated[SpeechToTextService, Depends(get_stt_service)]

