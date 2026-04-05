"""
Async database session management.
Uses SQLAlchemy 2.x async engine + asyncpg driver for Supabase/PostgreSQL.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_db_url = str(settings.DATABASE_URL)
_is_sqlite = _db_url.startswith("sqlite")

_engine_kwargs = {
    "echo": settings.DATABASE_ECHO,
    "future": True,
}

if not _is_sqlite:
    _engine_kwargs.update({
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    })

db_engine = create_async_engine(_db_url, **_engine_kwargs)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=db_engine,
    class_=AsyncSession,
    expire_on_commit=False,        # prevents lazy-load errors after commit
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """
    FastAPI dependency that yields an async DB session.
    The session is committed on success and rolled back on error.

    Usage in endpoint:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
