"""
ORM model: Event
An extracted atomic event from one testimony.
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EventConfidence(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Event(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A single discrete event extracted from a testimony.
    """
    __tablename__ = "events"

    testimony_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("testimonies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_timestamp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    participants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[EventConfidence] = mapped_column(
        Enum(EventConfidence),
        nullable=False,
        default=EventConfidence.MEDIUM,
    )
    embedding_vector: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # placeholder for pgvector
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Relationships
    testimony: Mapped["Testimony"] = relationship(  # type: ignore[name-defined]
        "Testimony", back_populates="events"
    )
    conflicts_as_a: Mapped[list["Conflict"]] = relationship(  # type: ignore[name-defined]
        "Conflict", foreign_keys="Conflict.event_a_id", back_populates="event_a", cascade="all, delete-orphan"
    )
    conflicts_as_b: Mapped[list["Conflict"]] = relationship(  # type: ignore[name-defined]
        "Conflict", foreign_keys="Conflict.event_b_id", back_populates="event_b", cascade="all, delete-orphan"
    )
