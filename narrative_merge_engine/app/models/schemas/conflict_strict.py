"""
Pydantic schemas for Strict Mode conflict detection.

These are INTENTIONALLY minimal — no impact scoring, no conflict graph,
no reasoning fields.  The strict-mode output schema matches EXACTLY
what the strict prompt requests:

  {
    "confirmed_events": [...],
    "conflicts": [...],
    "uncertain_events": [...],
    "next_question": {...}
  }

Each conflict contains ONLY:
  - conflict_block (the raw <<<< ==== >>>> string)
  - type (temporal | logical | spatial)
  - impact (low | medium | high)

No extra fields.  No hallucination surface.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Enums ───────────────────────────────────────────────────────────────────

class StrictConflictType(str, Enum):
    TEMPORAL = "temporal"
    LOGICAL = "logical"
    SPATIAL = "spatial"


class StrictImpactLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ─── Core types ──────────────────────────────────────────────────────────────

class StrictEvent(BaseModel):
    """Minimal event reference — just ID and description."""
    event_id: str
    description: str


class StrictConflict(BaseModel):
    """
    A single conflict in strict mode.
    Contains the raw Git-style conflict block as a string.
    """
    conflict_block: str = Field(
        ...,
        description="Git-style merge conflict block as a raw string.",
    )
    type: StrictConflictType = Field(
        ...,
        description="temporal | logical | spatial",
    )
    impact: StrictImpactLevel = Field(
        default=StrictImpactLevel.MEDIUM,
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalise_type(cls, v: Any) -> str:
        if isinstance(v, StrictConflictType):
            return v.value
        if isinstance(v, str):
            mapping = {
                "temporal": "temporal", "time": "temporal",
                "logical": "logical", "factual": "logical",
                "contradiction": "logical",
                "spatial": "spatial", "location": "spatial",
            }
            return mapping.get(v.strip().lower(), "logical")
        return "logical"

    @field_validator("impact", mode="before")
    @classmethod
    def normalise_impact(cls, v: Any) -> str:
        if isinstance(v, StrictImpactLevel):
            return v.value
        if isinstance(v, str):
            mapping = {
                "low": "low", "minor": "low",
                "medium": "medium", "moderate": "medium",
                "high": "high", "major": "high", "critical": "high",
            }
            return mapping.get(v.strip().lower(), "medium")
        return "medium"


class StrictNextQuestion(BaseModel):
    """Single investigator question — no extras."""
    question: str = Field(..., min_length=5)
    reason: str = Field(..., min_length=5)


class StrictConflictResult(BaseModel):
    """
    Complete strict-mode output.
    Matches EXACTLY the schema enforced by the strict prompt.
    """
    confirmed_events: list[StrictEvent] = Field(default_factory=list)
    conflicts: list[StrictConflict] = Field(default_factory=list)
    uncertain_events: list[StrictEvent] = Field(default_factory=list)
    next_question: StrictNextQuestion | None = Field(default=None)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def render_diff(self) -> str:
        """Render all conflict blocks as a continuous string."""
        return "\n\n".join(c.conflict_block for c in self.conflicts)
