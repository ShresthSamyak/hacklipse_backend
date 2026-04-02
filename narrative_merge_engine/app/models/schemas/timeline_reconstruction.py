"""
Pydantic schemas for the Timeline Reconstruction pipeline.

These model the OUTPUT of the reasoning engine — a structured timeline
with explicit confidence tiers, placement reasoning, and temporal links.

Design principles:
  ─ Events are separated into three tiers: confirmed, probable, uncertain.
    This PREVENTS forcing false precision on ambiguous orderings.
  ─ Every placement decision has a `reason` string explaining WHY the
    event was placed there — required for trust and human review.
  ─ Temporal links model directed relationships between events:
    "before", "after", "concurrent", "unknown" — NOT just linear order.
  ─ The timeline is a DAG (directed acyclic graph), not a list.
    Two events CAN occupy the same position if they're concurrent.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Enums ───────────────────────────────────────────────────────────────────

class PlacementConfidence(str, Enum):
    """How confident the reasoning engine is in an event's position."""
    CONFIRMED = "confirmed"    # explicit timestamp or undeniable logical order
    PROBABLE = "probable"      # strong contextual clues but some ambiguity
    UNCERTAIN = "uncertain"    # could go in multiple positions


class TemporalLinkType(str, Enum):
    """Directed temporal relationship between two events."""
    BEFORE = "before"            # A definitely happened before B
    AFTER = "after"              # A definitely happened after B
    CONCURRENT = "concurrent"    # A and B happened at approximately the same time
    PROBABLY_BEFORE = "probably_before"
    PROBABLY_AFTER = "probably_after"
    UNKNOWN = "unknown"          # relationship cannot be determined


# ─── Core types ──────────────────────────────────────────────────────────────

class TimelineEvent(BaseModel):
    """An event placed within the timeline with reasoning metadata."""

    event_id: str = Field(
        ..., description="ID of the original extracted event."
    )
    description: str = Field(
        ..., description="Description of the event (from extraction)."
    )
    time: str | None = Field(
        default=None, description="Original temporal marker from the witness."
    )
    time_uncertainty: str | None = Field(
        default=None, description="Why the time is uncertain."
    )
    location: str | None = Field(
        default=None, description="Location as described by the witness."
    )
    actors: list[str] = Field(
        default_factory=list, description="People involved."
    )
    original_confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Confidence from the extraction layer.",
    )
    position: int = Field(
        ..., ge=0,
        description=(
            "Position in the timeline (0-indexed).  Events with the same "
            "position are concurrent."
        ),
    )
    placement_confidence: PlacementConfidence = Field(
        default=PlacementConfidence.UNCERTAIN,
        description="How confident the engine is in this position.",
    )

    @field_validator("placement_confidence", mode="before")
    @classmethod
    def normalise_placement(cls, v: Any) -> str:
        if isinstance(v, PlacementConfidence):
            return v.value
        if isinstance(v, str):
            mapping = {
                "confirmed": "confirmed",
                "definite": "confirmed",
                "certain": "confirmed",
                "high": "confirmed",
                "probable": "probable",
                "likely": "probable",
                "medium": "probable",
                "uncertain": "uncertain",
                "low": "uncertain",
                "unknown": "uncertain",
                "ambiguous": "uncertain",
            }
            return mapping.get(v.strip().lower(), "uncertain")
        return "uncertain"


class PlacementReasoning(BaseModel):
    """Explains WHY a specific event was placed at a given position."""

    event_id: str = Field(
        ..., description="Event being reasoned about."
    )
    placed_at: int = Field(
        ..., ge=0, description="The position assigned."
    )
    reason: str = Field(
        ..., min_length=10,
        description=(
            "Human-readable explanation of why this event was placed here. "
            "Must reference the evidence: timestamps, temporal words, "
            "logical constraints, or explicit uncertainty."
        ),
    )
    confidence: PlacementConfidence = Field(
        default=PlacementConfidence.UNCERTAIN,
    )
    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Specific pieces of evidence used: temporal keywords, "
            "timestamps, logical deductions."
        ),
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def normalise_confidence(cls, v: Any) -> str:
        if isinstance(v, PlacementConfidence):
            return v.value
        if isinstance(v, str):
            mapping = {
                "confirmed": "confirmed", "definite": "confirmed",
                "certain": "confirmed", "high": "confirmed",
                "probable": "probable", "likely": "probable",
                "medium": "probable",
                "uncertain": "uncertain", "low": "uncertain",
                "unknown": "uncertain",
            }
            return mapping.get(v.strip().lower(), "uncertain")
        return "uncertain"


class TemporalLink(BaseModel):
    """A directed temporal relationship between two events."""

    event_a_id: str = Field(..., description="Source event.")
    event_b_id: str = Field(..., description="Target event.")
    link_type: TemporalLinkType = Field(
        ..., description="Type of temporal relationship."
    )
    reason: str = Field(
        default="", description="Why this link was inferred."
    )
    strength: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="How strong this temporal link is (0=guess, 1=certain).",
    )

    @field_validator("link_type", mode="before")
    @classmethod
    def normalise_link_type(cls, v: Any) -> str:
        if isinstance(v, TemporalLinkType):
            return v.value
        if isinstance(v, str):
            mapping = {
                "before": "before",
                "after": "after",
                "concurrent": "concurrent",
                "simultaneous": "concurrent",
                "same_time": "concurrent",
                "probably_before": "probably_before",
                "likely_before": "probably_before",
                "probably_after": "probably_after",
                "likely_after": "probably_after",
                "unknown": "unknown",
                "unclear": "unknown",
            }
            return mapping.get(v.strip().lower(), "unknown")
        return "unknown"

    @field_validator("strength", mode="before")
    @classmethod
    def clamp_strength(cls, v: Any) -> float:
        if isinstance(v, str):
            try:
                v = float(v.strip().rstrip("%"))
            except ValueError:
                return 0.5
        if isinstance(v, (int, float)):
            if v > 1.0:
                v = v / 100.0
            return max(0.0, min(1.0, float(v)))
        return 0.5


# ─── Top-level output ────────────────────────────────────────────────────────

class TimelineReconstructionResult(BaseModel):
    """Complete output of the timeline reconstruction pipeline."""

    confirmed_sequence: list[TimelineEvent] = Field(
        default_factory=list,
        description="Events whose position is high-confidence.",
    )
    probable_sequence: list[TimelineEvent] = Field(
        default_factory=list,
        description="Events whose position is likely but not certain.",
    )
    uncertain_events: list[TimelineEvent] = Field(
        default_factory=list,
        description="Events that could not be reliably placed.",
    )
    reasoning: list[PlacementReasoning] = Field(
        default_factory=list,
        description="Per-event explanation of placement decisions.",
    )
    temporal_links: list[TemporalLink] = Field(
        default_factory=list,
        description="Directed temporal relationships between events.",
    )
    reconstruction_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Model, latency, token usage, etc.",
    )

    @property
    def full_sequence(self) -> list[TimelineEvent]:
        """All events in reconstructed order, regardless of confidence tier."""
        all_events = (
            self.confirmed_sequence
            + self.probable_sequence
            + self.uncertain_events
        )
        return sorted(all_events, key=lambda e: e.position)

    @property
    def event_count(self) -> int:
        return (
            len(self.confirmed_sequence)
            + len(self.probable_sequence)
            + len(self.uncertain_events)
        )
