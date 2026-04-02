"""
Testimony Ingestion Service.
Orchestrates storing a testimony and triggering AI-powered summarisation.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.orchestrator import LLMOrchestrator
from app.core.ai.base_provider import LLMMessage, LLMRequest
from app.core.ai.prompt_registry import prompt_registry
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.orm.testimony import Testimony, TestimonyStatus
from app.models.schemas.testimony import TestimonyCreate, TestimonyRead, TestimonyUpdate
from app.repositories.testimony_repo import TestimonyRepository

logger = get_logger(__name__)


class TestimonyIngestionService:
    """
    Service layer for testimony creation, retrieval, and processing.
    All business logic lives here; the router just delegates.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.repo = TestimonyRepository(db)
        self.llm = llm

    async def ingest(self, payload: TestimonyCreate) -> TestimonyRead:
        """
        Persist a new testimony and trigger async summarisation.
        In production, summarisation would be pushed to a background task queue.
        """
        logger.info("Ingesting testimony", witness_id=payload.witness_id, title=payload.title)

        testimony = Testimony(
            title=payload.title,
            witness_id=payload.witness_id,
            raw_text=payload.raw_text,
            source_type=payload.source_type,
            language=payload.language,
            meta=payload.meta,
            status=TestimonyStatus.PENDING,
        )
        testimony = await self.repo.create(testimony)

        # ── Fire-and-forget summarisation (simplified; use BackgroundTasks or Celery in prod) ──
        try:
            await self._summarise(testimony)
        except Exception as exc:
            logger.warning("Summarisation failed", testimony_id=str(testimony.id), error=str(exc))
            await self.repo.update_status(testimony.id, TestimonyStatus.FAILED)

        return TestimonyRead.model_validate(testimony)

    async def _summarise(self, testimony: Testimony) -> None:
        """Generate a short summary of the testimony via LLM."""
        await self.repo.update_status(testimony.id, TestimonyStatus.PROCESSING)

        prompt = prompt_registry.render("testimony_summary_v1", testimony_text=testimony.raw_text)
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content="You are a forensic analyst assistant."),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.1,
        )
        response = await self.llm.complete(request, task_name="testimony_summary")
        summary = response.content.strip()

        await self.repo.update(testimony, {
            "summary": summary,
            "status": TestimonyStatus.PROCESSED,
        })
        logger.info("Testimony summarised", testimony_id=str(testimony.id))

    async def get(self, testimony_id: uuid.UUID) -> TestimonyRead:
        testimony = await self.repo.get_by_id(testimony_id)
        if not testimony:
            raise NotFoundError(f"Testimony {testimony_id} not found")
        return TestimonyRead.model_validate(testimony)

    async def list(
        self, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[TestimonyRead], int]:
        offset = (page - 1) * page_size
        items, total = await self.repo.get_all(offset=offset, limit=page_size)
        return [TestimonyRead.model_validate(t) for t in items], total

    async def update(self, testimony_id: uuid.UUID, payload: TestimonyUpdate) -> TestimonyRead:
        testimony = await self.repo.get_by_id(testimony_id)
        if not testimony:
            raise NotFoundError(f"Testimony {testimony_id} not found")
        data = payload.model_dump(exclude_none=True)
        testimony = await self.repo.update(testimony, data)
        return TestimonyRead.model_validate(testimony)

    async def delete(self, testimony_id: uuid.UUID) -> None:
        testimony = await self.repo.get_by_id(testimony_id)
        if not testimony:
            raise NotFoundError(f"Testimony {testimony_id} not found")
        await self.repo.delete(testimony)
