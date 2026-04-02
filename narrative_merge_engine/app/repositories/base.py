"""
Generic async repository base.
All concrete repositories inherit from this to get CRUD for free.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """
    Generic repository providing standard async CRUD operations.

    Usage:
        class TestimonyRepository(BaseRepository[Testimony]):
            model = Testimony
    """

    model: type[ModelT]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Reads ────────────────────────────────────────────────────────────────

    async def get_by_id(self, id: uuid.UUID) -> ModelT | None:
        result = await self.db.get(self.model, id)
        return result

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        filters: list[Any] | None = None,
        order_by: Any = None,
    ) -> tuple[Sequence[ModelT], int]:
        """Returns (items, total_count) for pagination."""
        query = select(self.model)
        count_query = select(func.count()).select_from(self.model)

        if filters:
            for f in filters:
                query = query.where(f)
                count_query = count_query.where(f)

        if order_by is not None:
            query = query.order_by(order_by)

        total_result = await self.db.execute(count_query)
        total: int = total_result.scalar_one()

        query = query.offset(offset).limit(limit)
        result = await self.db.execute(query)
        items = result.scalars().all()

        return items, total

    # ── Writes ───────────────────────────────────────────────────────────────

    async def create(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        await self.db.flush()        # get PK without committing (session handles commit)
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: ModelT, data: dict[str, Any]) -> ModelT:
        for field, value in data.items():
            setattr(obj, field, value)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def exists(self, id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(func.count()).select_from(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        )
        return result.scalar_one() > 0
