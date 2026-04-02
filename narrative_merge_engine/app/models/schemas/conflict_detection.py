"""
Pydantic schemas for the Conflict Detection & Merge Engine.

This is the Git-style merge system for human testimony.  The output models:
  ─ Conflicts rendered in <<<< ==== >>>> merge-conflict format
  ─ Typed conflict metadata (temporal/spatial/logical/entity)
  ─ Impact scoring (how many downstream events does this conflict affect?)
  ─ Partial merge output (confirmed / conflicts / uncertain)
  ─ Next-best-question generation for highest-impact conflicts
  ─ Conflict graph edges (agreement / conflict between event pairs)

Design principles:
  ─ NEVER decide truth.  Both versions are preserved.
  ─ Every conflict has explicit reasoning.
  ─ Impact is propagated downstream (a time conflict at entry
    poisons all later events that depend on entry time).
  ─ The "next best question" is the single most valuable question
    an investigator could ask to resolve the highest-impact conflict.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Enums ───────────────────────────────────────────────────────────────────

class ConflictCategory(str, Enum):
    """The nature of the contradiction between two testimony branches."""
    TEMPORAL = "temporal"       # disagreement on WHEN (9 PM vs 10 PM)
    SPATIAL = "spatial"         # disagreement on WHERE (room vs hallway)
    LOGICAL = "logical"         # mutually exclusive facts (saw someone vs no one)
    ENTITY = "entity"           # disagreement on WHO (man vs woman, 1 vs 3 people)
    SEQUENCE = "sequence"       # disagreement on ORDER (A before B vs B before A)
    CAUSAL = "causal"           # disagreement on WHY / cause-effect chain


class ConflictSeverityLevel(str, Enum):
    LOW = "low"         # minor detail difference — doesn't affect narrative core
    MEDIUM = "medium"   # significant but locally contained
    HIGH = "high"       # major contradiction — affects overall narrative integrity
    CRITICAL = "critical"  # foundational conflict — entire timeline branch diverges


class MergeStatus(str, Enum):
    """Status of a specific event in the merged output."""
    CONFIRMED = "confirmed"   # all branches agree
    CONFLICTED = "conflicted" # branches disagree — preserved both
    UNCERTAIN = "uncertain"   # insufficient evidence to confirm or conflict


class GraphEdgeType(str, Enum):
    """Relationship between two events in the conflict graph."""
    AGREEMENT = "agreement"     # both branches confirm this event
    CONFLICT = "conflict"       # branches give contradictory accounts
    PARTIAL = "partial"         # some overlap but differences exist
    INDEPENDENT = "independent" # events are unrelated


# ─── Core types ──────────────────────────────────────────────────────────────

class MergeConflictBlock(BaseModel):
    """
    A single Git-style merge conflict block.
    Renders as:
        <<<<<<< branch_a_label
        branch_a_text
        =======
        branch_b_text
        >>>>>>> branch_b_label
    """
    branch_a_label: str = Field(..., description="Witness/source identifier for branch A.")
    branch_a_text: str = Field(..., description="Branch A's version of the event.")
    branch_b_label: str = Field(..., description="Witness/source identifier for branch B.")
    branch_b_text: str = Field(..., description="Branch B's version of the event.")

    def render(self) -> str:
        """Produce the Git-style conflict string."""
        return (
            f"<<<<<<< {self.branch_a_label}\n"
            f"{self.branch_a_text}\n"
            f"=======\n"
            f"{self.branch_b_text}\n"
            f">>>>>>> {self.branch_b_label}"
        )


class ConflictImpact(BaseModel):
    """Quantifies the downstream impact of a conflict."""
    impact_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="0=isolated, 1=affects entire narrative.",
    )
    affected_event_count: int = Field(
        default=0, ge=0,
        description="How many downstream events are influenced by this conflict.",
    )
    affected_event_ids: list[str] = Field(
        default_factory=list,
        description="IDs of downstream events affected.",
    )
    reasoning: str = Field(
        default="",
        description="Why this impact score was assigned.",
    )

    @field_validator("impact_score", mode="before")
    @classmethod
    def clamp_impact(cls, v: Any) -> float:
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


class DetectedConflict(BaseModel):
    """A single detected conflict between two testimony branches."""
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique conflict identifier.",
    )
    category: ConflictCategory = Field(
        ..., description="Type of contradiction.",
    )
    severity: ConflictSeverityLevel = Field(
        default=ConflictSeverityLevel.MEDIUM,
    )
    description: str = Field(
        ..., min_length=10,
        description="Human-readable description of the conflict.",
    )
    event_a_id: str = Field(..., description="Event ID from branch A.")
    event_b_id: str = Field(..., description="Event ID from branch B.")
    branch_a: str = Field(default="", description="Source label for branch A.")
    branch_b: str = Field(default="", description="Source label for branch B.")
    merge_block: MergeConflictBlock = Field(
        ..., description="Git-style conflict rendering.",
    )
    impact: ConflictImpact = Field(
        default_factory=lambda: ConflictImpact(impact_score=0.5),
        description="Downstream impact analysis.",
    )
    reasoning: str = Field(
        default="",
        description="Why this was flagged as a conflict.",
    )

    @field_validator("category", mode="before")
    @classmethod
    def normalise_category(cls, v: Any) -> str:
        if isinstance(v, ConflictCategory):
            return v.value
        if isinstance(v, str):
            mapping = {
                "temporal": "temporal", "time": "temporal", "timing": "temporal",
                "spatial": "spatial", "location": "spatial", "place": "spatial",
                "logical": "logical", "factual": "logical", "contradiction": "logical",
                "entity": "entity", "person": "entity", "participant": "entity",
                "actor": "entity", "identity": "entity",
                "sequence": "sequence", "order": "sequence", "ordering": "sequence",
                "causal": "causal", "cause": "causal", "causation": "causal",
            }
            return mapping.get(v.strip().lower(), "logical")
        return "logical"

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: Any) -> str:
        if isinstance(v, ConflictSeverityLevel):
            return v.value
        if isinstance(v, str):
            mapping = {
                "low": "low", "minor": "low",
                "medium": "medium", "moderate": "medium",
                "high": "high", "major": "high", "severe": "high",
                "critical": "critical", "extreme": "critical", "fundamental": "critical",
            }
            return mapping.get(v.strip().lower(), "medium")
        return "medium"


class MergedEvent(BaseModel):
    """An event in the partial merge output."""
    event_id: str = Field(...)
    description: str = Field(...)
    status: MergeStatus = Field(default=MergeStatus.UNCERTAIN)
    branches_confirming: list[str] = Field(
        default_factory=list,
        description="Which branches/witnesses agree on this event.",
    )
    conflict_ids: list[str] = Field(
        default_factory=list,
        description="IDs of conflicts involving this event.",
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalise_status(cls, v: Any) -> str:
        if isinstance(v, MergeStatus):
            return v.value
        if isinstance(v, str):
            mapping = {
                "confirmed": "confirmed", "agreed": "confirmed",
                "conflicted": "conflicted", "conflict": "conflicted",
                "disputed": "conflicted",
                "uncertain": "uncertain", "unknown": "uncertain",
            }
            return mapping.get(v.strip().lower(), "uncertain")
        return "uncertain"


class NextBestQuestion(BaseModel):
    """The single most valuable question to resolve the highest-impact conflict."""
    question: str = Field(
        ..., min_length=10,
        description="The question an investigator should ask.",
    )
    target_conflict_id: str = Field(
        default="",
        description="Which conflict this question aims to resolve.",
    )
    why_this_question: str = Field(
        ..., min_length=10,
        description="Why THIS question is the most impactful one to ask.",
    )
    expected_resolution: str = Field(
        default="",
        description="What answering this question would resolve.",
    )
    priority: ConflictSeverityLevel = Field(
        default=ConflictSeverityLevel.HIGH,
    )


class ConflictGraphEdge(BaseModel):
    """An edge in the conflict graph."""
    event_a_id: str
    event_b_id: str
    edge_type: GraphEdgeType = Field(default=GraphEdgeType.INDEPENDENT)
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    description: str = Field(default="")

    @field_validator("edge_type", mode="before")
    @classmethod
    def normalise_edge_type(cls, v: Any) -> str:
        if isinstance(v, GraphEdgeType):
            return v.value
        if isinstance(v, str):
            mapping = {
                "agreement": "agreement", "agree": "agreement", "match": "agreement",
                "conflict": "conflict", "disagree": "conflict", "contradiction": "conflict",
                "partial": "partial", "overlap": "partial",
                "independent": "independent", "unrelated": "independent",
            }
            return mapping.get(v.strip().lower(), "independent")
        return "independent"


# ─── Top-level output ────────────────────────────────────────────────────────

class ConflictDetectionResult(BaseModel):
    """Complete output of the conflict detection & merge engine."""

    # ── Git-style conflicts ──────────────────────────────────────────────
    conflicts: list[DetectedConflict] = Field(
        default_factory=list,
        description="All detected conflicts with merge blocks and impact.",
    )

    # ── Partial merge ────────────────────────────────────────────────────
    confirmed_events: list[MergedEvent] = Field(
        default_factory=list,
        description="Events all branches agree on.",
    )
    conflicted_events: list[MergedEvent] = Field(
        default_factory=list,
        description="Events with active conflicts.",
    )
    uncertain_events: list[MergedEvent] = Field(
        default_factory=list,
        description="Events with insufficient evidence to classify.",
    )

    # ── Intelligence ─────────────────────────────────────────────────────
    next_best_question: NextBestQuestion | None = Field(
        default=None,
        description="The single most impactful investigator question.",
    )

    # ── Conflict graph ───────────────────────────────────────────────────
    conflict_graph: list[ConflictGraphEdge] = Field(
        default_factory=list,
        description="Event relationship graph (agreement/conflict edges).",
    )

    # ── Git-style diff string ────────────────────────────────────────────
    merge_diff: str = Field(
        default="",
        description="Full Git-style merge conflict rendering.",
    )

    # ── Metadata ─────────────────────────────────────────────────────────
    detection_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Model, latency, token usage, etc.",
    )

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

    @property
    def highest_impact_conflict(self) -> DetectedConflict | None:
        if not self.conflicts:
            return None
        return max(self.conflicts, key=lambda c: c.impact.impact_score)

    def render_full_diff(self) -> str:
        """Render all conflicts as a single Git-style diff string."""
        blocks: list[str] = []
        for conflict in self.conflicts:
            blocks.append(f"# Conflict: {conflict.description}")
            blocks.append(f"# Type: {conflict.category.value} | Severity: {conflict.severity.value}")
            blocks.append(f"# Impact: {conflict.impact.impact_score}")
            blocks.append(conflict.merge_block.render())
            blocks.append("")
        return "\n".join(blocks)
