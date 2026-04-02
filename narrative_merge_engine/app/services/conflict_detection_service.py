"""
Conflict Detection & Merge Service — Git for Human Testimony
==============================================================

This service is the core USP of the Narrative Merge Engine.
It works like Git's merge algorithm: given multiple testimony "branches",
it detects contradictions, renders them as merge conflicts, scores their
downstream impact, and generates the single most valuable question for
resolution.

This is NOT truth-finding.  This is conflict EXPOSURE.

Architecture:
  ┌─────────────────────────────┐
  │  Branch A  │  Branch B  │ … │   Multiple witness testimony branches
  └──────┬──────┬────────────┘
         │      │
    ┌────▼──────▼────┐
    │  Pre-processing │  Group events by branch, normalise keys
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │  LLM Reasoning  │   v2 prompt → Orchestrator → Provider
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │  Response Parse  │  JSON extraction + per-section validation
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │  Post-validation │  Impact recalculation, missing conflict IDs
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │  Merge Render    │  Build <<<< ==== >>>> diff string
    └───────┬────────┘
            │
    ┌───────▼────────┐
    │  Persist + Return│
    └─────────────────┘
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base_provider import LLMMessage, LLMRequest
from app.core.ai.orchestrator import LLMOrchestrator
from app.core.ai.prompt_registry import prompt_registry
from app.core.ai.response_parser import extract_json, validate_events
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.orm.timeline_conflict_question import (
    Conflict,
    ConflictSeverity,
    ConflictType,
)
from app.models.schemas.conflict_detection import (
    ConflictCategory,
    ConflictDetectionResult,
    ConflictGraphEdge,
    ConflictImpact,
    ConflictSeverityLevel,
    DetectedConflict,
    GraphEdgeType,
    MergeConflictBlock,
    MergedEvent,
    MergeStatus,
    NextBestQuestion,
)
from app.models.schemas.entities import ConflictRead, ConflictResolve
from app.models.schemas.conflict_strict import (
    StrictConflict,
    StrictConflictResult,
    StrictEvent,
    StrictNextQuestion,
)
from app.repositories.entity_repos import ConflictRepository, TimelineRepository

logger = get_logger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────

_MAX_VALIDATION_RETRIES = 2

# Map from our fine-grained categories to the ORM's simpler enum
_CATEGORY_TO_ORM: dict[str, ConflictType] = {
    "temporal": ConflictType.TEMPORAL,
    "spatial": ConflictType.LOCATION,
    "logical": ConflictType.FACTUAL,
    "entity": ConflictType.PARTICIPANT,
    "sequence": ConflictType.TEMPORAL,
    "causal": ConflictType.CAUSAL,
}

_SEVERITY_TO_ORM: dict[str, ConflictSeverity] = {
    "low": ConflictSeverity.LOW,
    "medium": ConflictSeverity.MEDIUM,
    "high": ConflictSeverity.HIGH,
    "critical": ConflictSeverity.HIGH,  # ORM doesn't have 'critical'
}


# ─── Pre-processing helpers ─────────────────────────────────────────────────

def _prepare_branches_for_prompt(
    branches: dict[str, list[dict]],
) -> str:
    """
    Format multiple testimony branches into a structured prompt input.

    Each branch is labelled with its witness/source name and presented
    as a JSON array of events.
    """
    sections: list[str] = []
    for label, events in branches.items():
        normalised: list[dict] = []
        for e in events:
            normalised.append({
                "id": e.get("id", e.get("event_id", str(uuid.uuid4()))),
                "description": e.get("description", ""),
                "time": e.get("time", e.get("timestamp_hint")),
                "time_uncertainty": e.get("time_uncertainty"),
                "location": e.get("location"),
                "actors": e.get("actors", e.get("participants", [])),
                "confidence": e.get("confidence", 0.5),
            })
        sections.append(
            f"BRANCH: {label}\n{json.dumps(normalised, indent=2, ensure_ascii=False)}"
        )
    return "\n\n".join(sections)


def _build_branches_from_timeline(
    ordered_events: list[dict],
) -> dict[str, list[dict]]:
    """
    Group events from a reconstructed timeline by their testimony_id
    to form branches for conflict detection.
    """
    branches: dict[str, list[dict]] = {}
    for event in ordered_events:
        tid = event.get("testimony_id", "unknown")
        branch_label = f"Testimony_{tid[:8]}" if len(tid) > 8 else f"Testimony_{tid}"
        branches.setdefault(branch_label, []).append(event)

    return branches


def _analyse_branch_overlap(
    branches: dict[str, list[dict]],
) -> dict[str, Any]:
    """Pre-analyse branch structure for metadata."""
    total_events = sum(len(evts) for evts in branches.values())
    locations: set[str] = set()
    times: set[str] = set()

    for evts in branches.values():
        for e in evts:
            if e.get("location"):
                locations.add(e["location"])
            if e.get("time"):
                times.add(e["time"])

    return {
        "branch_count": len(branches),
        "total_events": total_events,
        "unique_locations": len(locations),
        "unique_times": len(times),
        "branch_sizes": {k: len(v) for k, v in branches.items()},
    }


# ─── Post-validation helpers ────────────────────────────────────────────────

def _render_merge_diff(result: ConflictDetectionResult) -> str:
    """Build the full Git-style merge diff string from all conflicts."""
    return result.render_full_diff()


def _ensure_conflict_ids_linked(result: ConflictDetectionResult) -> ConflictDetectionResult:
    """
    Ensure conflicted_events have correct conflict_ids cross-references.
    """
    conflict_event_map: dict[str, list[str]] = {}
    for c in result.conflicts:
        conflict_event_map.setdefault(c.event_a_id, []).append(c.id)
        conflict_event_map.setdefault(c.event_b_id, []).append(c.id)

    for event in result.conflicted_events:
        if not event.conflict_ids:
            event.conflict_ids = conflict_event_map.get(event.event_id, [])

    return result


def _validate_impact_consistency(result: ConflictDetectionResult) -> list[str]:
    """Cross-check impact scores for reasonableness."""
    warnings: list[str] = []

    for c in result.conflicts:
        if c.impact.impact_score > 0.7 and c.severity in (
            ConflictSeverityLevel.LOW,
        ):
            warnings.append(
                f"Conflict {c.id}: high impact ({c.impact.impact_score}) "
                f"but low severity — may be miscalibrated"
            )
        if c.impact.affected_event_count == 0 and c.impact.impact_score > 0.5:
            warnings.append(
                f"Conflict {c.id}: impact_score={c.impact.impact_score} "
                f"but affected_event_count=0"
            )

    if warnings:
        logger.warning(
            "Impact consistency issues",
            warning_count=len(warnings),
            warnings=warnings[:5],
        )

    return warnings


# ============================================================================
# Main Service
# ============================================================================

class ConflictDetectionService:
    """
    Git-style merge engine for human testimony.

    This service:
      1. Groups events by testimony branch (witness).
      2. Sends branches to LLM for contradiction analysis.
      3. Parses and validates Git-style merge output.
      4. Scores downstream impact of each conflict.
      5. Generates the single most impactful investigator question.
      6. Builds a conflict graph (agreement/conflict edges).
      7. Renders a full <<<< ==== >>>> diff string.
      8. Persists conflicts to database for resolution tracking.
      9. NEVER decides truth — only exposes disagreements.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.conflict_repo = ConflictRepository(db)
        self.timeline_repo = TimelineRepository(db)
        self.llm = llm

    # ── Public API ───────────────────────────────────────────────────────────

    async def detect_conflicts(self, timeline_id: uuid.UUID) -> list[ConflictRead]:
        """
        Full pipeline: load timeline → group by branch → detect → persist.
        Returns ORM-compatible ConflictRead objects for backward compat.
        """
        timeline = await self.timeline_repo.get_by_id(timeline_id)
        if not timeline:
            raise NotFoundError(f"Timeline {timeline_id} not found")

        ordered_events = timeline.ordered_events
        if not ordered_events:
            logger.info("No events in timeline", timeline_id=str(timeline_id))
            return []

        # Group events into branches by testimony
        branches = _build_branches_from_timeline(ordered_events)

        if len(branches) < 2:
            logger.info(
                "Only one branch — no cross-testimony conflicts possible",
                timeline_id=str(timeline_id),
            )
            return []

        # Run full merge analysis
        result = await self.detect_from_branches(branches)

        # Persist each conflict to the ORM
        created: list[Conflict] = []
        for conflict in result.conflicts:
            try:
                orm_conflict = Conflict(
                    timeline_id=timeline_id,
                    event_a_id=uuid.UUID(conflict.event_a_id),
                    event_b_id=uuid.UUID(conflict.event_b_id),
                    conflict_type=_CATEGORY_TO_ORM.get(
                        conflict.category.value, ConflictType.FACTUAL
                    ),
                    description=conflict.description,
                    severity=_SEVERITY_TO_ORM.get(
                        conflict.severity.value, ConflictSeverity.MEDIUM
                    ),
                    meta={
                        "merge_block": conflict.merge_block.model_dump(),
                        "impact": conflict.impact.model_dump(),
                        "reasoning": conflict.reasoning,
                        "category": conflict.category.value,
                        "git_diff": conflict.merge_block.render(),
                    },
                )
                orm_conflict = await self.conflict_repo.create(orm_conflict)
                created.append(orm_conflict)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "Failed to persist conflict — skipping",
                    conflict_id=conflict.id,
                    error=str(exc),
                )

        logger.info(
            "Conflicts detected and persisted",
            timeline_id=str(timeline_id),
            total=len(result.conflicts),
            persisted=len(created),
        )

        return [ConflictRead.model_validate(c) for c in created]

    async def detect_from_branches(
        self,
        branches: dict[str, list[dict]],
    ) -> ConflictDetectionResult:
        """
        Detect conflicts from pre-structured branches WITHOUT DB persistence.
        Useful for testing, previewing, and the API preview endpoint.
        """
        start_time = time.monotonic()

        overlap = _analyse_branch_overlap(branches)
        logger.info(
            "Conflict detection started",
            branch_count=len(branches),
            total_events=overlap["total_events"],
        )

        result = await self._detect_with_retries(branches=branches)

        # Post-validation
        result = _ensure_conflict_ids_linked(result)
        impact_warnings = _validate_impact_consistency(result)
        result.merge_diff = _render_merge_diff(result)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)

        result.detection_metadata.update({
            "elapsed_ms": elapsed_ms,
            "branch_overlap": overlap,
            "impact_warnings": impact_warnings,
            "summary": {
                "total_conflicts": len(result.conflicts),
                "confirmed_events": len(result.confirmed_events),
                "conflicted_events": len(result.conflicted_events),
                "uncertain_events": len(result.uncertain_events),
                "has_next_question": result.next_best_question is not None,
            },
        })

        logger.info(
            "Conflict detection completed",
            elapsed_ms=elapsed_ms,
            conflicts=len(result.conflicts),
            confirmed=len(result.confirmed_events),
            conflicted=len(result.conflicted_events),
            uncertain=len(result.uncertain_events),
        )

        return result

    async def detect_from_events_preview(
        self,
        branches: dict[str, list[dict]],
    ) -> ConflictDetectionResult:
        """Alias for detect_from_branches — clearer name for the API."""
        return await self.detect_from_branches(branches)

    async def list_conflicts(self, timeline_id: uuid.UUID) -> list[ConflictRead]:
        conflicts = await self.conflict_repo.get_by_timeline(timeline_id)
        return [ConflictRead.model_validate(c) for c in conflicts]

    async def resolve_conflict(
        self, conflict_id: uuid.UUID, payload: ConflictResolve
    ) -> ConflictRead:
        conflict = await self.conflict_repo.get_by_id(conflict_id)
        if not conflict:
            raise NotFoundError(f"Conflict {conflict_id} not found")
        conflict = await self.conflict_repo.update(
            conflict,
            {"is_resolved": True, "resolution_notes": payload.resolution_notes},
        )
        return ConflictRead.model_validate(conflict)

    async def detect_strict(
        self,
        branches: dict[str, list[dict]],
    ) -> StrictConflictResult:
        """
        Strict mode: zero-hallucination, zero-inference, deterministic.

        Uses:
          - conflict_detection_strict prompt
          - temperature=0
          - lean StrictConflictResult schema
          - no impact scoring, no graph, no reasoning fields
          - max 2 retries on validation failure

        Suitable for automated pipelines, CI checks, and audit trails.
        """
        start_time = time.monotonic()

        for attempt in range(_MAX_VALIDATION_RETRIES + 1):
            try:
                result = await self._strict_detection_pass(
                    branches=branches,
                    is_retry=attempt > 0,
                )
                elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
                logger.info(
                    "Strict conflict detection completed",
                    elapsed_ms=elapsed_ms,
                    conflicts=result.conflict_count,
                    confirmed=len(result.confirmed_events),
                    uncertain=len(result.uncertain_events),
                )
                return result
            except (ValidationError, Exception) as exc:
                if attempt < _MAX_VALIDATION_RETRIES:
                    logger.warning(
                        "Strict detection validation failed — retrying",
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    continue
                logger.error(
                    "Strict detection failed after all retries",
                    error=str(exc),
                )
                return self._build_strict_fallback(branches)

        return self._build_strict_fallback(branches)

    async def _strict_detection_pass(
        self,
        *,
        branches: dict[str, list[dict]],
        is_retry: bool,
    ) -> StrictConflictResult:
        """Single strict-mode LLM call."""
        prompt_key = "conflict_detection_strict"
        branches_json = _prepare_branches_for_prompt(branches)
        user_prompt = prompt_registry.render(prompt_key, branches_json=branches_json)
        system_prompt = prompt_registry.get_system_prompt(prompt_key)

        if is_retry:
            user_prompt += (
                "\n\n--- RETRY: Your previous output was invalid JSON. "
                "Return ONLY a raw JSON object.  No markdown fences.  "
                "No text before or after the JSON."
            )

        messages: list[LLMMessage] = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=user_prompt))

        request = LLMRequest(
            messages=messages,
            temperature=0.0,  # deterministic
            max_tokens=4096,  # strict mode is lean
        )

        response = await self.llm.complete(
            request, task_name="conflict_detection_strict"
        )

        raw = extract_json(response.content)

        if not isinstance(raw, dict):
            raise ValidationError(
                "Strict mode: expected a JSON object",
                detail={"actual_type": type(raw).__name__},
            )

        return self._parse_strict_output(raw)

    def _parse_strict_output(self, raw: dict) -> StrictConflictResult:
        """Parse raw LLM output into the lean strict schema."""

        # Confirmed events
        confirmed_raw = raw.get("confirmed_events", [])
        confirmed, _ = validate_events(confirmed_raw, StrictEvent)

        # Conflicts
        conflicts_raw = raw.get("conflicts", [])
        conflicts, _ = validate_events(conflicts_raw, StrictConflict)

        # Uncertain events
        uncertain_raw = raw.get("uncertain_events", [])
        uncertain, _ = validate_events(uncertain_raw, StrictEvent)

        # Next question
        nq_raw = raw.get("next_question")
        next_question: StrictNextQuestion | None = None
        if nq_raw and isinstance(nq_raw, dict):
            try:
                next_question = StrictNextQuestion.model_validate(nq_raw)
            except Exception as exc:
                logger.warning(
                    "Strict mode: next_question validation failed",
                    error=str(exc),
                )

        return StrictConflictResult(
            confirmed_events=confirmed,
            conflicts=conflicts,
            uncertain_events=uncertain,
            next_question=next_question,
        )

    def _build_strict_fallback(
        self, branches: dict[str, list[dict]]
    ) -> StrictConflictResult:
        """Fallback for total strict-mode failure."""
        logger.error("Building strict-mode fallback — no analysis available")
        uncertain: list[StrictEvent] = []
        for _label, events in branches.items():
            for e in events:
                uncertain.append(
                    StrictEvent(
                        event_id=e.get("id", str(uuid.uuid4())),
                        description=e.get("description", "Unknown event"),
                    )
                )
        return StrictConflictResult(
            confirmed_events=[],
            conflicts=[],
            uncertain_events=uncertain,
            next_question=None,
        )

    # ── Internal pipeline ────────────────────────────────────────────────────

    async def _detect_with_retries(
        self,
        *,
        branches: dict[str, list[dict]],
    ) -> ConflictDetectionResult:
        """Call the LLM with retries for validation failures."""
        for attempt in range(_MAX_VALIDATION_RETRIES + 1):
            try:
                return await self._single_detection_pass(
                    branches=branches,
                    is_retry=attempt > 0,
                )
            except ValidationError as exc:
                if attempt < _MAX_VALIDATION_RETRIES:
                    logger.warning(
                        "Conflict detection validation failed — retrying",
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    continue
                logger.error(
                    "Conflict detection failed after all retries",
                    error=str(exc),
                )
                return self._build_fallback_result(branches)

        return self._build_fallback_result(branches)

    async def _single_detection_pass(
        self,
        *,
        branches: dict[str, list[dict]],
        is_retry: bool,
    ) -> ConflictDetectionResult:
        """Single LLM call → parse → validate."""

        # Build prompt
        prompt_key = "conflict_detection_v2"
        branches_json = _prepare_branches_for_prompt(branches)
        user_prompt = prompt_registry.render(prompt_key, branches_json=branches_json)
        system_prompt = prompt_registry.get_system_prompt(prompt_key)

        if is_retry:
            user_prompt += (
                "\n\n--- IMPORTANT: Your previous response had validation errors. "
                "Please be very careful to:\n"
                "1. Return ONLY valid JSON (no markdown fences)\n"
                "2. Include ALL required fields in every conflict object\n"
                "3. Include merge_block with branch_a_label, branch_a_text, "
                "branch_b_label, branch_b_text for every conflict\n"
                "4. Include impact with impact_score, affected_event_count\n"
                "5. Include next_best_question if conflicts exist"
            )

        messages: list[LLMMessage] = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=user_prompt))

        request = LLMRequest(
            messages=messages,
            temperature=0.05,
            max_tokens=8192,
        )

        # Call LLM
        response = await self.llm.complete(request, task_name="conflict_detection_v2")

        meta: dict[str, Any] = {
            "model": response.model,
            "usage": response.usage,
            "is_retry": is_retry,
        }

        # Parse
        raw = extract_json(response.content)

        if not isinstance(raw, dict):
            raise ValidationError(
                "Expected a JSON object from conflict detection",
                detail={"actual_type": type(raw).__name__},
            )

        return self._parse_llm_output(raw, meta)

    def _parse_llm_output(
        self,
        raw: dict,
        meta: dict[str, Any],
    ) -> ConflictDetectionResult:
        """Parse and validate the raw LLM output into typed models."""

        # ── Conflicts ────────────────────────────────────────────────────
        conflicts_raw = raw.get("conflicts", [])
        conflicts, c_dropped = validate_events(conflicts_raw, DetectedConflict)

        if c_dropped:
            logger.warning(
                "Conflict entries dropped during validation",
                dropped=len(c_dropped),
            )

        # ── Partial merge ────────────────────────────────────────────────
        confirmed_raw = raw.get("confirmed_events", [])
        conflicted_raw = raw.get("conflicted_events", [])
        uncertain_raw = raw.get("uncertain_events", [])

        confirmed, _ = validate_events(confirmed_raw, MergedEvent)
        conflicted, _ = validate_events(conflicted_raw, MergedEvent)
        uncertain, _ = validate_events(uncertain_raw, MergedEvent)

        # ── Next best question ───────────────────────────────────────────
        nbq_raw = raw.get("next_best_question")
        next_best_question: NextBestQuestion | None = None
        if nbq_raw and isinstance(nbq_raw, dict):
            try:
                next_best_question = NextBestQuestion.model_validate(nbq_raw)
            except Exception as exc:
                logger.warning(
                    "NextBestQuestion validation failed",
                    error=str(exc),
                )

        # ── Conflict graph ───────────────────────────────────────────────
        graph_raw = raw.get("conflict_graph", [])
        graph_edges, _ = validate_events(graph_raw, ConflictGraphEdge)

        return ConflictDetectionResult(
            conflicts=conflicts,
            confirmed_events=confirmed,
            conflicted_events=conflicted,
            uncertain_events=uncertain,
            next_best_question=next_best_question,
            conflict_graph=graph_edges,
            detection_metadata=meta,
        )

    def _build_fallback_result(
        self,
        branches: dict[str, list[dict]],
    ) -> ConflictDetectionResult:
        """If the LLM completely fails, return a minimal result."""
        logger.error("Building fallback conflict result — no analysis available")

        all_events: list[MergedEvent] = []
        for label, events in branches.items():
            for e in events:
                all_events.append(
                    MergedEvent(
                        event_id=e.get("id", str(uuid.uuid4())),
                        description=e.get("description", "Unknown event"),
                        status=MergeStatus.UNCERTAIN,
                        branches_confirming=[label],
                    )
                )

        return ConflictDetectionResult(
            conflicts=[],
            confirmed_events=[],
            conflicted_events=[],
            uncertain_events=all_events,
            next_best_question=None,
            conflict_graph=[],
            detection_metadata={"fallback": True},
        )
