"""
Timeline Reconstruction Service.
Merges events from multiple testimonies into a coherent chronological timeline.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base_provider import LLMMessage, LLMRequest
from app.core.ai.orchestrator import LLMOrchestrator
from app.core.ai.prompt_registry import prompt_registry
from app.core.ai.response_parser import extract_json
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.orm.timeline_conflict_question import Timeline
from app.models.schemas.entities import TimelineCreate, TimelineRead
from app.repositories.entity_repos import EventRepository, TimelineRepository
from app.repositories.testimony_repo import TestimonyRepository

logger = get_logger(__name__)


class TimelineReconstructionService:
    """
    Reconstructs a unified timeline from events across multiple testimonies.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.timeline_repo = TimelineRepository(db)
        self.event_repo = EventRepository(db)
        self.testimony_repo = TestimonyRepository(db)
        self.llm = llm

    async def reconstruct(self, payload: TimelineCreate) -> TimelineRead:
        """
        Build a timeline from the given testimony IDs.

        Flow:
          1. Collect all events for the specified testimonies.
          2. Pass events to LLM for chronological alignment.
          3. Store the resulting timeline.
        """
        if not payload.testimony_ids:
            raise ValidationError("At least one testimony ID is required")

        # Gather all events across testimonies
        all_events: list[dict] = []
        for tid in payload.testimony_ids:
            events = await self.event_repo.get_by_testimony(tid)
            for e in events:
                all_events.append({
                    "id": str(e.id),
                    "testimony_id": str(e.testimony_id),
                    "description": e.description,
                    "timestamp_hint": e.timestamp_hint,
                    "location": e.location,
                    "participants": e.participants,
                    "confidence": e.confidence.value,
                })

        if not all_events:
            raise ValidationError("No events found for the specified testimonies")

        logger.info(
            "Reconstructing timeline",
            testimony_count=len(payload.testimony_ids),
            event_count=len(all_events),
        )

        prompt = prompt_registry.render("timeline_alignment_v1", events_json=json.dumps(all_events, indent=2))
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are a forensic timeline reconstruction expert. Return valid JSON only."),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.0,
        )
        response = await self.llm.complete(request, task_name="timeline_reconstruction")
        ordered_events: list[dict] = extract_json(response.content)

        timeline = Timeline(
            title=payload.title,
            description=payload.description,
            testimony_ids=[str(t) for t in payload.testimony_ids],
            ordered_events=ordered_events,
            meta=payload.meta,
        )
        timeline = await self.timeline_repo.create(timeline)

        logger.info("Timeline created", timeline_id=str(timeline.id))
        return TimelineRead.model_validate(timeline)

    async def get(self, timeline_id: uuid.UUID) -> TimelineRead:
        timeline = await self.timeline_repo.get_by_id(timeline_id)
        if not timeline:
            raise NotFoundError(f"Timeline {timeline_id} not found")
        return TimelineRead.model_validate(timeline)

    async def list(self, *, page: int = 1, page_size: int = 20) -> tuple[list[TimelineRead], int]:
        offset = (page - 1) * page_size
        items, total = await self.timeline_repo.get_all(offset=offset, limit=page_size)
        return [TimelineRead.model_validate(t) for t in items], total
