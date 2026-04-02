"""
Event Extraction Service.
Uses the LLM to extract discrete events from a testimony's raw text.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base_provider import LLMMessage, LLMRequest
from app.core.ai.orchestrator import LLMOrchestrator
from app.core.ai.prompt_registry import prompt_registry
from app.core.ai.response_parser import extract_json
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.orm.event import Event, EventConfidence
from app.models.schemas.entities import EventRead
from app.repositories.entity_repos import EventRepository
from app.repositories.testimony_repo import TestimonyRepository

logger = get_logger(__name__)


class EventExtractionService:
    """
    Extracts structured events from testimonies via LLM.
    Each call to `extract_events` produces N Event records from one testimony.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.event_repo = EventRepository(db)
        self.testimony_repo = TestimonyRepository(db)
        self.llm = llm

    async def extract_events(self, testimony_id: uuid.UUID) -> list[EventRead]:
        """
        Run event extraction on a testimony and persist the results.

        Flow:
          1. Load testimony.
          2. Call LLM with event_extraction prompt.
          3. Parse JSON response into Event records.
          4. Persist and return.
        """
        testimony = await self.testimony_repo.get_by_id(testimony_id)
        if not testimony:
            raise NotFoundError(f"Testimony {testimony_id} not found")

        logger.info("Extracting events", testimony_id=str(testimony_id))

        prompt = prompt_registry.render("event_extraction_v1", testimony_text=testimony.raw_text)
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are a structured data extraction engine. Always return valid JSON."),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.0,  # deterministic extraction
        )
        response = await self.llm.complete(request, task_name="event_extraction")

        raw_events: list[dict] = extract_json(response.content)

        created: list[Event] = []
        for raw in raw_events:
            event = Event(
                testimony_id=testimony_id,
                description=raw.get("description", ""),
                timestamp_hint=raw.get("timestamp_hint"),
                location=raw.get("location"),
                participants=raw.get("participants", []),
                confidence=EventConfidence(raw.get("confidence", "medium")),
                meta={"llm_raw": raw},
            )
            event = await self.event_repo.create(event)
            created.append(event)

        logger.info("Events extracted", testimony_id=str(testimony_id), count=len(created))
        return [EventRead.model_validate(e) for e in created]

    async def list_events(self, testimony_id: uuid.UUID) -> list[EventRead]:
        """List all previously extracted events for a testimony."""
        events = await self.event_repo.get_by_testimony(testimony_id)
        return [EventRead.model_validate(e) for e in events]

    async def get_event(self, event_id: uuid.UUID) -> EventRead:
        event = await self.event_repo.get_by_id(event_id)
        if not event:
            raise NotFoundError(f"Event {event_id} not found")
        return EventRead.model_validate(event)
