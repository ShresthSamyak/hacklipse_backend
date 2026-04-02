"""
Pydantic schemas for Testimony (request / response / internal).
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.orm.testimony import TestimonyStatus


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class TestimonyBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    witness_id: str = Field(..., description="Anonymised or real witness identifier")
    raw_text: str = Field(..., min_length=10)
    source_type: str = Field(default="text", pattern="^(text|audio_transcript|video_transcript|document)$")
    language: str = Field(default="en", max_length=16)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class TestimonyCreate(TestimonyBase):
    """Payload for ingesting a new testimony."""
    pass


class TestimonyUpdate(BaseModel):
    """Partial update schema."""
    title: str | None = Field(None, max_length=255)
    summary: str | None = None
    status: TestimonyStatus | None = None
    meta: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TestimonyRead(TestimonyBase):
    """Full testimony response."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    summary: str | None
    status: TestimonyStatus
    confidence_score: float | None
    created_at: datetime
    updated_at: datetime


class TestimonyList(BaseModel):
    """Paginated response envelope."""
    items: list[TestimonyRead]
    total: int
    page: int
    page_size: int
