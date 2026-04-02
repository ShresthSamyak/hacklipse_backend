"""
ORM model: Testimony
Represents a single witness account ingested into the system.
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TestimonyStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class Testimony(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A witness testimony document.
    One testimony → many events.
    """
    __tablename__ = "testimonies"

    # Core fields
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    witness_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="text")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    status: Mapped[TestimonyStatus] = mapped_column(
        Enum(TestimonyStatus),
        nullable=False,
        default=TestimonyStatus.PENDING,
        index=True,
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Flexible metadata (tags, custom fields, etc.)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Relationships
    events: Mapped[list["Event"]] = relationship(  # type: ignore[name-defined]
        "Event", back_populates="testimony", cascade="all, delete-orphan", lazy="selectin"
    )
