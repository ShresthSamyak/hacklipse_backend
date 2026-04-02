"""
Event, Timeline, Conflict, and Question repositories.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.event import Event
from app.models.orm.timeline_conflict_question import Conflict, Question, Timeline
from app.repositories.base import BaseRepository


class EventRepository(BaseRepository[Event]):
    model = Event

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    async def get_by_testimony(self, testimony_id: uuid.UUID) -> list[Event]:
        result = await self.db.execute(
            select(Event).where(Event.testimony_id == testimony_id)
        )
        return list(result.scalars().all())

    async def get_by_ids(self, event_ids: list[uuid.UUID]) -> list[Event]:
        result = await self.db.execute(
            select(Event).where(Event.id.in_(event_ids))
        )
        return list(result.scalars().all())


class TimelineRepository(BaseRepository[Timeline]):
    model = Timeline

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    async def get_with_events_and_conflicts(self, timeline_id: uuid.UUID) -> Timeline | None:
        """Eagerly loads conflicts and questions via selectin (set in ORM model)."""
        return await self.get_by_id(timeline_id)


class ConflictRepository(BaseRepository[Conflict]):
    model = Conflict

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    async def get_by_timeline(self, timeline_id: uuid.UUID) -> list[Conflict]:
        result = await self.db.execute(
            select(Conflict).where(Conflict.timeline_id == timeline_id)
        )
        return list(result.scalars().all())

    async def get_unresolved(self, timeline_id: uuid.UUID) -> list[Conflict]:
        result = await self.db.execute(
            select(Conflict)
            .where(Conflict.timeline_id == timeline_id)
            .where(Conflict.is_resolved == False)  # noqa: E712
        )
        return list(result.scalars().all())


class QuestionRepository(BaseRepository[Question]):
    model = Question

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    async def get_by_timeline(self, timeline_id: uuid.UUID) -> list[Question]:
        result = await self.db.execute(
            select(Question).where(Question.timeline_id == timeline_id)
        )
        return list(result.scalars().all())

    async def get_unanswered(self, timeline_id: uuid.UUID) -> list[Question]:
        result = await self.db.execute(
            select(Question)
            .where(Question.timeline_id == timeline_id)
            .where(Question.is_answered == False)  # noqa: E712
        )
        return list(result.scalars().all())
