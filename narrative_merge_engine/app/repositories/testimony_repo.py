"""
Testimony repository — data access layer for testimony records.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.testimony import Testimony, TestimonyStatus
from app.repositories.base import BaseRepository


class TestimonyRepository(BaseRepository[Testimony]):
    model = Testimony

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)

    async def get_by_witness(self, witness_id: str) -> list[Testimony]:
        result = await self.db.execute(
            select(Testimony).where(Testimony.witness_id == witness_id)
        )
        return list(result.scalars().all())

    async def get_by_status(self, status: TestimonyStatus) -> list[Testimony]:
        result = await self.db.execute(
            select(Testimony).where(Testimony.status == status)
        )
        return list(result.scalars().all())

    async def update_status(
        self, testimony_id: uuid.UUID, status: TestimonyStatus
    ) -> Testimony | None:
        obj = await self.get_by_id(testimony_id)
        if obj is None:
            return None
        return await self.update(obj, {"status": status})
