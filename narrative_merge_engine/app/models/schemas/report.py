from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConflictType(str, Enum):
    TEMPORAL = "temporal"
    LOGICAL = "logical"
    SPATIAL = "spatial"
    OTHER = "other"


class ConflictImpact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReportConflict(BaseModel):
    description: str = Field(..., description="Summary of the conflict.")
    type: ConflictType = Field(..., description="Type of the conflict: temporal, logical, or spatial.")
    impact: ConflictImpact = Field(..., description="Severity or impact of this conflict.")


class ReportGenerationResult(BaseModel):
    """Structured synthesis of the narrative pipeline."""
    summary: str = Field(..., description="Executive summary of the testimony and events.")
    key_events: list[str] = Field(..., description="List of the most critical events.")
    conflicts: list[ReportConflict] = Field(default_factory=list, description="Any identified conflicts.")
    emotional_analysis: str = Field(..., description="A summary of the witness's emotional state.")
    uncertainty_analysis: str = Field(..., description="A summary of the witness's uncertainty levels.")
    recommended_next_steps: list[str] = Field(..., description="Suggested follow-ups based on the analysis.")

    @classmethod
    def fallback(cls) -> "ReportGenerationResult":
        """Fallback used when the report generation fails."""
        return cls(
            summary="Report generation failed. Please refer to raw events and timeline.",
            key_events=[],
            conflicts=[],
            emotional_analysis="Analysis unavailable.",
            uncertainty_analysis="Analysis unavailable.",
            recommended_next_steps=["Manually review the extracted events."]
        )
