"""
Conflict Detection Service.
Identifies contradictions between events in a timeline via LLM analysis.
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
from app.models.orm.timeline_conflict_question import Conflict, ConflictSeverity, ConflictType
from app.models.schemas.entities import ConflictRead, ConflictResolve
from app.repositories.entity_repos import ConflictRepository, TimelineRepository

logger = get_logger(__name__)


class ConflictDetectionService:
    """
    Detects and manages conflicts within a reconstructed timeline.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.conflict_repo = ConflictRepository(db)
        self.timeline_repo = TimelineRepository(db)
        self.llm = llm

    async def detect_conflicts(self, timeline_id: uuid.UUID) -> list[ConflictRead]:
        """
        Analyse timeline events for contradictions using the LLM.

        Flow:
          1. Load the timeline with its ordered events.
          2. Pass events to the LLM conflict detector.
          3. Persist detected conflict records.
        """
        timeline = await self.timeline_repo.get_by_id(timeline_id)
        if not timeline:
            raise NotFoundError(f"Timeline {timeline_id} not found")

        events_json = json.dumps(timeline.ordered_events, indent=2)
        logger.info("Detecting conflicts", timeline_id=str(timeline_id), event_count=len(timeline.ordered_events))

        prompt = prompt_registry.render("conflict_detection_v1", events_json=events_json)
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are a contradiction detection expert. Return JSON only."),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.0,
        )
        response = await self.llm.complete(request, task_name="conflict_detection")
        raw_conflicts: list[dict] = extract_json(response.content)

        created: list[Conflict] = []
        for raw in raw_conflicts:
            conflict = Conflict(
                timeline_id=timeline_id,
                event_a_id=uuid.UUID(raw["event_a_id"]),
                event_b_id=uuid.UUID(raw["event_b_id"]),
                conflict_type=ConflictType(raw.get("conflict_type", "factual")),
                description=raw.get("description", ""),
                severity=ConflictSeverity(raw.get("severity", "medium")),
                meta={"llm_raw": raw},
            )
            conflict = await self.conflict_repo.create(conflict)
            created.append(conflict)

        logger.info("Conflicts detected", timeline_id=str(timeline_id), count=len(created))
        return [ConflictRead.model_validate(c) for c in created]

    async def list_conflicts(self, timeline_id: uuid.UUID) -> list[ConflictRead]:
        conflicts = await self.conflict_repo.get_by_timeline(timeline_id)
        return [ConflictRead.model_validate(c) for c in conflicts]

    async def resolve_conflict(
        self, conflict_id: uuid.UUID, payload: ConflictResolve
    ) -> ConflictRead:
        conflict = await self.conflict_repo.get_by_id(conflict_id)
        if not conflict:
            raise NotFoundError(f"Conflict {conflict_id} not found")
        conflict = await self.conflict_repo.update(
            conflict,
            {"is_resolved": True, "resolution_notes": payload.resolution_notes},
        )
        return ConflictRead.model_validate(conflict)
