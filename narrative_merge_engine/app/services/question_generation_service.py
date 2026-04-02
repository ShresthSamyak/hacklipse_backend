"""
Question Generation Service.
Generates clarifying questions from timeline gaps and conflicts.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base_provider import LLMMessage, LLMRequest
from app.core.ai.orchestrator import LLMOrchestrator
from app.core.ai.prompt_registry import prompt_registry
from app.core.ai.response_parser import extract_json
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.orm.timeline_conflict_question import Question, QuestionPriority
from app.models.schemas.entities import QuestionAnswer, QuestionRead
from app.repositories.entity_repos import ConflictRepository, QuestionRepository, TimelineRepository

logger = get_logger(__name__)


class QuestionGenerationService:
    """
    Generates targeted investigator questions based on conflicts and timeline gaps.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.question_repo = QuestionRepository(db)
        self.timeline_repo = TimelineRepository(db)
        self.conflict_repo = ConflictRepository(db)
        self.llm = llm

    async def generate_questions(self, timeline_id: uuid.UUID) -> list[QuestionRead]:
        """
        Generate clarifying questions for a given timeline.

        Flow:
          1. Load the timeline and its unresolved conflicts.
          2. Send to LLM with question_generation prompt.
          3. Persist Question records.
        """
        timeline = await self.timeline_repo.get_by_id(timeline_id)
        if not timeline:
            raise NotFoundError(f"Timeline {timeline_id} not found")

        conflicts = await self.conflict_repo.get_unresolved(timeline_id)
        conflicts_data = [
            {
                "id": str(c.id),
                "conflict_type": c.conflict_type.value,
                "description": c.description,
                "severity": c.severity.value,
                "event_a_id": str(c.event_a_id),
                "event_b_id": str(c.event_b_id),
            }
            for c in conflicts
        ]

        logger.info(
            "Generating questions",
            timeline_id=str(timeline_id),
            conflict_count=len(conflicts_data),
        )

        prompt = prompt_registry.render(
            "question_generation_v1",
            timeline_json=json.dumps(timeline.ordered_events, indent=2),
            conflicts_json=json.dumps(conflicts_data, indent=2),
        )
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are an expert investigative analyst. Return JSON only."),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.3,  # slight creativity for question variety
        )
        response = await self.llm.complete(request, task_name="question_generation")
        raw_questions: list[dict] = extract_json(response.content)

        created: list[Question] = []
        for raw in raw_questions:
            question = Question(
                timeline_id=timeline_id,
                question_text=raw.get("question", ""),
                target_event_ids=raw.get("target_event_ids", []),
                priority=QuestionPriority(raw.get("priority", "medium")),
                meta={"llm_raw": raw},
            )
            question = await self.question_repo.create(question)
            created.append(question)

        logger.info("Questions generated", timeline_id=str(timeline_id), count=len(created))
        return [QuestionRead.model_validate(q) for q in created]

    async def list_questions(self, timeline_id: uuid.UUID) -> list[QuestionRead]:
        questions = await self.question_repo.get_by_timeline(timeline_id)
        return [QuestionRead.model_validate(q) for q in questions]

    async def answer_question(self, question_id: uuid.UUID, payload: QuestionAnswer) -> QuestionRead:
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError(f"Question {question_id} not found")
        question = await self.question_repo.update(
            question,
            {"is_answered": True, "answer": payload.answer},
        )
        return QuestionRead.model_validate(question)
