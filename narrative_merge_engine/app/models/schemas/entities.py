"""
Pydantic schemas for Event, Conflict, Timeline, and Question.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.orm.timeline_conflict_question import (
    ConflictSeverity,
    ConflictType,
    QuestionPriority,
)
from app.models.orm.event import EventConfidence


# ============================================================
# Event
# ============================================================

class EventBase(BaseModel):
    description: str = Field(..., min_length=1)
    timestamp_hint: str | None = None
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    confidence: EventConfidence = EventConfidence.MEDIUM
    meta: dict[str, Any] = Field(default_factory=dict)


class EventCreate(EventBase):
    testimony_id: uuid.UUID


class EventRead(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    testimony_id: uuid.UUID
    resolved_timestamp: str | None
    created_at: datetime
    updated_at: datetime


# ============================================================
# Timeline
# ============================================================

class TimelineCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    testimony_ids: list[uuid.UUID] = Field(..., min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)


class TimelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    testimony_ids: list[uuid.UUID]
    ordered_events: list[dict]
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# ============================================================
# Conflict
# ============================================================

class ConflictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    timeline_id: uuid.UUID
    event_a_id: uuid.UUID
    event_b_id: uuid.UUID
    conflict_type: ConflictType
    description: str
    severity: ConflictSeverity
    is_resolved: bool
    resolution_notes: str | None
    created_at: datetime


class ConflictResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=1)


# ============================================================
# Question
# ============================================================

class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    timeline_id: uuid.UUID
    question_text: str
    target_event_ids: list[uuid.UUID]
    priority: QuestionPriority
    is_answered: bool
    answer: str | None
    created_at: datetime


class QuestionAnswer(BaseModel):
    answer: str = Field(..., min_length=1)
