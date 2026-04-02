"""
Timeline Reconstruction Service — Reasoning Under Uncertainty
==============================================================

This service takes structured events (output of EventExtractionService)
and reconstructs a chronological timeline using LLM-powered reasoning.

This is NOT sorting.  This is:
  1. Evidence collection (what temporal signals exist?)
  2. Constraint inference (what must come before/after what?)
  3. Confidence classification (how certain is each placement?)
  4. Explicit reasoning (WHY was each event placed here?)
  5. Graph construction (temporal links between events)

Architecture:
  ┌─────────────────────┐
  │  Extracted Events    │  From EventExtractionService or direct input
  └──────────┬──────────┘
             │
    ┌────────▼────────┐
    │  Pre-analysis    │  Count temporal anchors, detect relative markers
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │  LLM Reasoning   │  v2 prompt → Orchestrator → Provider
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │  Response Parse   │  JSON extraction + schema validation
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │  Post-validation  │  Cross-check reasoning, verify temporal consistency
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │  Persist + Return │  ORM write → TimelineReconstructionResult
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
from app.models.orm.timeline_conflict_question import Timeline
from app.models.schemas.entities import TimelineCreate, TimelineRead
from app.models.schemas.timeline_reconstruction import (
    PlacementConfidence,
    PlacementReasoning,
    TemporalLink,
    TemporalLinkType,
    TimelineEvent,
    TimelineReconstructionResult,
)
from app.repositories.entity_repos import EventRepository, TimelineRepository
from app.repositories.testimony_repo import TestimonyRepository

logger = get_logger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────

# Max events per LLM call (beyond this, chunk into sub-problems)
_MAX_EVENTS_PER_CALL = 40

# Max retry attempts for validation failures
_MAX_VALIDATION_RETRIES = 2


# ─── Pre-analysis helpers ────────────────────────────────────────────────────

def _analyse_temporal_signals(events: list[dict]) -> dict[str, Any]:
    """
    Pre-analyse the event set to understand what temporal evidence exists.
    This metadata helps the service decide trust levels and detect edge cases.
    """
    total = len(events)
    with_explicit_time = sum(1 for e in events if e.get("time"))
    with_relative_time = sum(
        1 for e in events
        if e.get("time_uncertainty") and any(
            kw in (e.get("time_uncertainty") or "").lower()
            for kw in ["relative", "after", "before", "later", "earlier", "pehle", "baad"]
        )
    )
    with_location = sum(1 for e in events if e.get("location"))
    with_actors = sum(1 for e in events if e.get("actors"))

    anchor_ratio = with_explicit_time / total if total > 0 else 0

    return {
        "total_events": total,
        "with_explicit_time": with_explicit_time,
        "with_relative_time": with_relative_time,
        "with_location": with_location,
        "with_actors": with_actors,
        "temporal_anchor_ratio": round(anchor_ratio, 3),
        "has_strong_anchors": anchor_ratio >= 0.3,
    }


def _prepare_events_for_prompt(events: list[dict]) -> list[dict]:
    """
    Normalise event dicts for the prompt.  Strip internal fields,
    ensure consistent key names.
    """
    prepared: list[dict] = []

    for e in events:
        prepared.append({
            "id": e.get("id", e.get("event_id", str(uuid.uuid4()))),
            "description": e.get("description", ""),
            "time": e.get("time", e.get("timestamp_hint")),
            "time_uncertainty": e.get("time_uncertainty"),
            "location": e.get("location"),
            "actors": e.get("actors", e.get("participants", [])),
            "confidence": e.get("confidence", e.get("original_confidence", 0.5)),
        })

    return prepared


# ─── Post-validation ────────────────────────────────────────────────────────

def _validate_temporal_consistency(result: TimelineReconstructionResult) -> list[str]:
    """
    Cross-check the temporal links against the event positions.
    Returns a list of warnings (not errors — the timeline is still valid).
    """
    warnings: list[str] = []

    # Build position map
    position_map: dict[str, int] = {}
    for event in result.full_sequence:
        position_map[event.event_id] = event.position

    for link in result.temporal_links:
        a_pos = position_map.get(link.event_a_id)
        b_pos = position_map.get(link.event_b_id)

        if a_pos is None or b_pos is None:
            # link references an event not in the timeline — skip
            continue

        if link.link_type == TemporalLinkType.BEFORE and a_pos >= b_pos:
            warnings.append(
                f"Inconsistency: {link.event_a_id} marked 'before' "
                f"{link.event_b_id} but placed at position {a_pos} >= {b_pos}"
            )
        elif link.link_type == TemporalLinkType.AFTER and a_pos <= b_pos:
            warnings.append(
                f"Inconsistency: {link.event_a_id} marked 'after' "
                f"{link.event_b_id} but placed at position {a_pos} <= {b_pos}"
            )

    if warnings:
        logger.warning(
            "Temporal consistency issues detected",
            warning_count=len(warnings),
            warnings=warnings[:5],
        )

    return warnings


def _ensure_all_events_placed(
    input_event_ids: set[str],
    result: TimelineReconstructionResult,
) -> TimelineReconstructionResult:
    """
    Verify every input event appears in the output.
    If the LLM dropped events, add them to uncertain_events.
    """
    placed_ids: set[str] = set()
    for event in result.full_sequence:
        placed_ids.add(event.event_id)

    missing = input_event_ids - placed_ids
    if missing:
        logger.warning(
            "LLM dropped events from timeline — adding to uncertain",
            missing_count=len(missing),
            missing_ids=list(missing)[:10],
        )
        max_position = max(
            (e.position for e in result.full_sequence), default=0
        )
        for mid in missing:
            max_position += 1
            result.uncertain_events.append(
                TimelineEvent(
                    event_id=mid,
                    description=f"[Event {mid} — not placed by reasoning engine]",
                    position=max_position,
                    placement_confidence=PlacementConfidence.UNCERTAIN,
                )
            )
            result.reasoning.append(
                PlacementReasoning(
                    event_id=mid,
                    placed_at=max_position,
                    reason=(
                        "This event was not placed by the reasoning engine. "
                        "It was appended to the end of the timeline with "
                        "uncertain confidence to ensure completeness."
                    ),
                    confidence=PlacementConfidence.UNCERTAIN,
                    evidence=["Missing from LLM output — auto-appended"],
                )
            )

    return result


def _ensure_reasoning_complete(
    input_event_ids: set[str],
    result: TimelineReconstructionResult,
) -> TimelineReconstructionResult:
    """
    Verify every placed event has a reasoning entry.
    """
    reasoned_ids = {r.event_id for r in result.reasoning}
    missing = input_event_ids - reasoned_ids

    for mid in missing:
        # Find the event's position
        pos = 0
        conf = PlacementConfidence.UNCERTAIN
        for event in result.full_sequence:
            if event.event_id == mid:
                pos = event.position
                conf = event.placement_confidence
                break

        result.reasoning.append(
            PlacementReasoning(
                event_id=mid,
                placed_at=pos,
                reason=(
                    "Reasoning not provided by the LLM for this event. "
                    "Position was assigned but justification is missing."
                ),
                confidence=conf,
                evidence=["No reasoning provided"],
            )
        )

    return result


# ============================================================================
# Main Service
# ============================================================================

class TimelineReconstructionService:
    """
    Reasoning engine: events → chronological timeline with uncertainty.

    This service:
      1. Pre-analyses temporal signals in the event set.
      2. Calls the LLM with the v2 timeline reconstruction prompt.
      3. Parses and validates the structured output.
      4. Cross-checks temporal consistency (links vs positions).
      5. Ensures all input events appear in the output.
      6. Ensures all events have reasoning entries.
      7. Persists the timeline to the database.
      8. Returns a TimelineReconstructionResult with full metadata.
    """

    def __init__(self, db: AsyncSession, llm: LLMOrchestrator) -> None:
        self.timeline_repo = TimelineRepository(db)
        self.event_repo = EventRepository(db)
        self.testimony_repo = TestimonyRepository(db)
        self.llm = llm

    # ── Public API ───────────────────────────────────────────────────────────

    async def reconstruct(self, payload: TimelineCreate) -> TimelineRead:
        """
        Full pipeline: load events from DB → reason → persist timeline.
        """
        if not payload.testimony_ids:
            raise ValidationError("At least one testimony ID is required")

        # Gather all events across testimonies
        all_events: list[dict] = []
        for tid in payload.testimony_ids:
            events = await self.event_repo.get_by_testimony(tid)
            for e in events:
                event_dict: dict[str, Any] = {
                    "id": str(e.id),
                    "testimony_id": str(e.testimony_id),
                    "description": e.description,
                    "time": e.timestamp_hint,
                    "location": e.location,
                    "actors": e.participants,
                    "confidence": e.confidence.value if hasattr(e.confidence, "value") else str(e.confidence),
                }
                # Enrich from meta if available
                if e.meta:
                    event_dict["time_uncertainty"] = e.meta.get("time_uncertainty")
                    event_dict["uncertainty_type"] = e.meta.get("uncertainty_type")

                all_events.append(event_dict)

        if not all_events:
            raise ValidationError("No events found for the specified testimonies")

        # Run the reasoning pipeline
        result = await self.reconstruct_from_events(all_events)

        # Persist to database
        timeline = Timeline(
            title=payload.title,
            description=payload.description,
            testimony_ids=[str(t) for t in payload.testimony_ids],
            ordered_events=[e.model_dump() for e in result.full_sequence],
            meta={
                "reconstruction_metadata": result.reconstruction_metadata,
                "temporal_links": [l.model_dump() for l in result.temporal_links],
                "reasoning": [r.model_dump() for r in result.reasoning],
                "confidence_summary": {
                    "confirmed": len(result.confirmed_sequence),
                    "probable": len(result.probable_sequence),
                    "uncertain": len(result.uncertain_events),
                },
            },
        )
        timeline = await self.timeline_repo.create(timeline)

        logger.info(
            "Timeline created",
            timeline_id=str(timeline.id),
            confirmed=len(result.confirmed_sequence),
            probable=len(result.probable_sequence),
            uncertain=len(result.uncertain_events),
        )

        return TimelineRead.model_validate(timeline)

    async def reconstruct_from_events(
        self,
        events: list[dict],
    ) -> TimelineReconstructionResult:
        """
        Reconstruct a timeline from a list of event dicts WITHOUT DB persistence.
        Useful for testing, previewing, and API preview endpoints.
        """
        start_time = time.monotonic()

        # ── 1. Pre-analysis ──────────────────────────────────────────────
        prepared = _prepare_events_for_prompt(events)
        signals = _analyse_temporal_signals(prepared)
        input_ids = {e["id"] for e in prepared}

        logger.info(
            "Timeline reconstruction started",
            event_count=len(prepared),
            temporal_signals=signals,
        )

        # ── 2. LLM reasoning ────────────────────────────────────────────
        result = await self._reason_with_retries(
            prepared_events=prepared,
            input_ids=input_ids,
            signals=signals,
        )

        # ── 3. Post-validation ───────────────────────────────────────────
        result = _ensure_all_events_placed(input_ids, result)
        result = _ensure_reasoning_complete(input_ids, result)
        consistency_warnings = _validate_temporal_consistency(result)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)

        result.reconstruction_metadata.update({
            "elapsed_ms": elapsed_ms,
            "event_count": len(prepared),
            "temporal_signals": signals,
            "consistency_warnings": consistency_warnings,
            "confidence_summary": {
                "confirmed": len(result.confirmed_sequence),
                "probable": len(result.probable_sequence),
                "uncertain": len(result.uncertain_events),
            },
        })

        logger.info(
            "Timeline reconstruction completed",
            elapsed_ms=elapsed_ms,
            confirmed=len(result.confirmed_sequence),
            probable=len(result.probable_sequence),
            uncertain=len(result.uncertain_events),
            links=len(result.temporal_links),
            warnings=len(consistency_warnings),
        )

        return result

    async def get(self, timeline_id: uuid.UUID) -> TimelineRead:
        timeline = await self.timeline_repo.get_by_id(timeline_id)
        if not timeline:
            raise NotFoundError(f"Timeline {timeline_id} not found")
        return TimelineRead.model_validate(timeline)

    async def list(self, *, page: int = 1, page_size: int = 20) -> tuple[list[TimelineRead], int]:
        offset = (page - 1) * page_size
        items, total = await self.timeline_repo.get_all(offset=offset, limit=page_size)
        return [TimelineRead.model_validate(t) for t in items], total

    # ── Internal reasoning pipeline ──────────────────────────────────────────

    async def _reason_with_retries(
        self,
        *,
        prepared_events: list[dict],
        input_ids: set[str],
        signals: dict[str, Any],
    ) -> TimelineReconstructionResult:
        """
        Call the LLM with retries for validation failures.
        """
        for attempt in range(_MAX_VALIDATION_RETRIES + 1):
            try:
                return await self._single_reasoning_pass(
                    prepared_events=prepared_events,
                    input_ids=input_ids,
                    signals=signals,
                    is_retry=attempt > 0,
                )
            except ValidationError as exc:
                if attempt < _MAX_VALIDATION_RETRIES:
                    logger.warning(
                        "Timeline reasoning validation failed — retrying",
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    continue
                logger.error(
                    "Timeline reasoning failed after all retries",
                    error=str(exc),
                )
                # Return a bare-minimum result rather than crashing
                return self._build_fallback_result(prepared_events)

        return self._build_fallback_result(prepared_events)

    async def _single_reasoning_pass(
        self,
        *,
        prepared_events: list[dict],
        input_ids: set[str],
        signals: dict[str, Any],
        is_retry: bool,
    ) -> TimelineReconstructionResult:
        """
        Single LLM call → parse → validate.
        """
        # ── Build prompt ─────────────────────────────────────────────────
        prompt_key = "timeline_reconstruction_v2"
        events_json = json.dumps(prepared_events, indent=2, ensure_ascii=False)
        user_prompt = prompt_registry.render(prompt_key, events_json=events_json)
        system_prompt = prompt_registry.get_system_prompt(prompt_key)

        if is_retry:
            user_prompt += (
                "\n\n⚠️ IMPORTANT: Your previous response had validation errors. "
                "Please be very careful to:\n"
                "1. Return ONLY valid JSON (no markdown fences)\n"
                "2. Include ALL input events in the output\n"
                "3. Provide reasoning for EVERY event\n"
                "4. Use the exact field names from the schema\n"
                "5. Ensure position values are integers starting from 0"
            )

        messages: list[LLMMessage] = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=user_prompt))

        request = LLMRequest(
            messages=messages,
            temperature=0.05,   # near-deterministic reasoning
            max_tokens=8192,    # timelines need more output space
        )

        # ── Call LLM ─────────────────────────────────────────────────────
        response = await self.llm.complete(request, task_name="timeline_reconstruction_v2")

        meta: dict[str, Any] = {
            "model": response.model,
            "usage": response.usage,
            "is_retry": is_retry,
        }

        # ── Parse JSON ───────────────────────────────────────────────────
        raw = extract_json(response.content)

        if not isinstance(raw, dict):
            raise ValidationError(
                "Expected a JSON object from timeline reasoning",
                detail={"actual_type": type(raw).__name__},
            )

        # ── Validate each section ────────────────────────────────────────
        result = self._parse_llm_output(raw, meta)

        return result

    def _parse_llm_output(
        self,
        raw: dict,
        meta: dict[str, Any],
    ) -> TimelineReconstructionResult:
        """
        Parse and validate the raw LLM output dict into typed models.
        Uses per-item validation (drop bad, keep good) for events and reasoning.
        """
        # ── Timeline events ──────────────────────────────────────────────
        confirmed_raw = raw.get("confirmed_sequence", [])
        probable_raw = raw.get("probable_sequence", [])
        uncertain_raw = raw.get("uncertain_events", [])

        confirmed, c_dropped = validate_events(confirmed_raw, TimelineEvent)
        probable, p_dropped = validate_events(probable_raw, TimelineEvent)
        uncertain, u_dropped = validate_events(uncertain_raw, TimelineEvent)

        total_dropped = len(c_dropped) + len(p_dropped) + len(u_dropped)
        if total_dropped:
            logger.warning(
                "Timeline events dropped during validation",
                confirmed_dropped=len(c_dropped),
                probable_dropped=len(p_dropped),
                uncertain_dropped=len(u_dropped),
            )

        # ── Reasoning ────────────────────────────────────────────────────
        reasoning_raw = raw.get("reasoning", [])
        reasoning, r_dropped = validate_events(reasoning_raw, PlacementReasoning)

        if r_dropped:
            logger.warning(
                "Reasoning entries dropped during validation",
                dropped=len(r_dropped),
            )

        # ── Temporal links ───────────────────────────────────────────────
        links_raw = raw.get("temporal_links", [])
        links, l_dropped = validate_events(links_raw, TemporalLink)

        if l_dropped:
            logger.warning(
                "Temporal links dropped during validation",
                dropped=len(l_dropped),
            )

        return TimelineReconstructionResult(
            confirmed_sequence=confirmed,
            probable_sequence=probable,
            uncertain_events=uncertain,
            reasoning=reasoning,
            temporal_links=links,
            reconstruction_metadata=meta,
        )

    def _build_fallback_result(
        self,
        events: list[dict],
    ) -> TimelineReconstructionResult:
        """
        If the LLM completely fails, build a minimal timeline where
        all events are uncertain, in input order.
        """
        logger.error("Building fallback timeline — all events marked uncertain")

        uncertain: list[TimelineEvent] = []
        reasoning: list[PlacementReasoning] = []

        for i, e in enumerate(events):
            eid = e.get("id", str(uuid.uuid4()))
            uncertain.append(
                TimelineEvent(
                    event_id=eid,
                    description=e.get("description", "Unknown event"),
                    time=e.get("time"),
                    time_uncertainty=e.get("time_uncertainty"),
                    location=e.get("location"),
                    actors=e.get("actors", []),
                    original_confidence=float(e.get("confidence", 0.5)),
                    position=i,
                    placement_confidence=PlacementConfidence.UNCERTAIN,
                )
            )
            reasoning.append(
                PlacementReasoning(
                    event_id=eid,
                    placed_at=i,
                    reason=(
                        "Fallback ordering: LLM reasoning failed. Events are listed "
                        "in input order with no temporal analysis applied."
                    ),
                    confidence=PlacementConfidence.UNCERTAIN,
                    evidence=["Fallback — no LLM reasoning available"],
                )
            )

        return TimelineReconstructionResult(
            confirmed_sequence=[],
            probable_sequence=[],
            uncertain_events=uncertain,
            reasoning=reasoning,
            temporal_links=[],
            reconstruction_metadata={"fallback": True},
        )
