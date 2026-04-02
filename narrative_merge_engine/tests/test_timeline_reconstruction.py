"""
Tests for the Timeline Reconstruction Intelligence Layer.

Covers:
  - Pydantic schema validation (TimelineEvent, TemporalLink, etc.)
  - Pre-analysis helpers (temporal signal detection)
  - Post-validation (consistency checks, missing event recovery)
  - Service-level reasoning with mocked LLM (full pipeline)
  - Edge cases: no events, single event, all uncertain, fallback mode
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.ai.base_provider import LLMResponse
from app.core.exceptions import ValidationError
from app.models.schemas.timeline_reconstruction import (
    PlacementConfidence,
    PlacementReasoning,
    TemporalLink,
    TemporalLinkType,
    TimelineEvent,
    TimelineReconstructionResult,
)


# ============================================================================
# Schema Tests
# ============================================================================

class TestTimelineEvent:
    """Tests for the TimelineEvent Pydantic model."""

    def test_basic_valid_event(self):
        event = TimelineEvent(
            event_id="evt-1",
            description="Entered the room",
            time="9 PM",
            position=0,
            placement_confidence="confirmed",
        )
        assert event.placement_confidence == PlacementConfidence.CONFIRMED
        assert event.position == 0

    def test_placement_confidence_normalisation(self):
        """Various spellings should normalise to valid enum values."""
        for input_val, expected in [
            ("confirmed", PlacementConfidence.CONFIRMED),
            ("definite", PlacementConfidence.CONFIRMED),
            ("certain", PlacementConfidence.CONFIRMED),
            ("high", PlacementConfidence.CONFIRMED),
            ("probable", PlacementConfidence.PROBABLE),
            ("likely", PlacementConfidence.PROBABLE),
            ("medium", PlacementConfidence.PROBABLE),
            ("uncertain", PlacementConfidence.UNCERTAIN),
            ("low", PlacementConfidence.UNCERTAIN),
            ("unknown", PlacementConfidence.UNCERTAIN),
            ("ambiguous", PlacementConfidence.UNCERTAIN),
        ]:
            event = TimelineEvent(
                event_id="test",
                description="test event mapping",
                position=0,
                placement_confidence=input_val,
            )
            assert event.placement_confidence == expected, f"Failed for {input_val}"

    def test_default_values(self):
        event = TimelineEvent(
            event_id="evt-1",
            description="Minimal event",
            position=0,
        )
        assert event.time is None
        assert event.location is None
        assert event.actors == []
        assert event.original_confidence == 0.5
        assert event.placement_confidence == PlacementConfidence.UNCERTAIN


class TestTemporalLink:
    """Tests for the TemporalLink model."""

    def test_basic_link(self):
        link = TemporalLink(
            event_a_id="evt-1",
            event_b_id="evt-2",
            link_type="before",
            reason="evt-1 has a timestamp earlier than evt-2",
            strength=0.9,
        )
        assert link.link_type == TemporalLinkType.BEFORE
        assert link.strength == 0.9

    def test_link_type_normalisation(self):
        for input_val, expected in [
            ("before", TemporalLinkType.BEFORE),
            ("after", TemporalLinkType.AFTER),
            ("concurrent", TemporalLinkType.CONCURRENT),
            ("simultaneous", TemporalLinkType.CONCURRENT),
            ("same_time", TemporalLinkType.CONCURRENT),
            ("probably_before", TemporalLinkType.PROBABLY_BEFORE),
            ("likely_before", TemporalLinkType.PROBABLY_BEFORE),
            ("unknown", TemporalLinkType.UNKNOWN),
            ("unclear", TemporalLinkType.UNKNOWN),
        ]:
            link = TemporalLink(
                event_a_id="a", event_b_id="b",
                link_type=input_val,
            )
            assert link.link_type == expected, f"Failed for {input_val}"

    def test_strength_clamping(self):
        link = TemporalLink(
            event_a_id="a", event_b_id="b",
            link_type="before", strength=150,
        )
        assert link.strength <= 1.0

    def test_strength_from_percentage_string(self):
        link = TemporalLink(
            event_a_id="a", event_b_id="b",
            link_type="before", strength="85%",
        )
        assert link.strength == 0.85


class TestPlacementReasoning:
    """Tests for the PlacementReasoning model."""

    def test_valid_reasoning(self):
        r = PlacementReasoning(
            event_id="evt-1",
            placed_at=0,
            reason="This is the earliest event because it has a timestamp of 9 PM",
            confidence="confirmed",
            evidence=["explicit timestamp: 9 PM"],
        )
        assert r.confidence == PlacementConfidence.CONFIRMED
        assert len(r.evidence) == 1

    def test_reason_min_length(self):
        with pytest.raises(Exception):
            PlacementReasoning(
                event_id="evt-1",
                placed_at=0,
                reason="Short",  # too short — min 10 chars
            )


class TestTimelineReconstructionResult:
    """Tests for the result container."""

    def test_full_sequence_ordering(self):
        result = TimelineReconstructionResult(
            confirmed_sequence=[
                TimelineEvent(event_id="c1", description="Confirmed event at pos 0", position=0, placement_confidence="confirmed"),
            ],
            probable_sequence=[
                TimelineEvent(event_id="p1", description="Probable event at pos 2", position=2, placement_confidence="probable"),
            ],
            uncertain_events=[
                TimelineEvent(event_id="u1", description="Uncertain event at pos 1", position=1, placement_confidence="uncertain"),
            ],
        )
        full = result.full_sequence
        assert len(full) == 3
        assert full[0].event_id == "c1"
        assert full[1].event_id == "u1"
        assert full[2].event_id == "p1"

    def test_event_count(self):
        result = TimelineReconstructionResult(
            confirmed_sequence=[
                TimelineEvent(event_id="a", description="Event alpha at pos 0", position=0),
            ],
            probable_sequence=[
                TimelineEvent(event_id="b", description="Event beta at pos 1", position=1),
                TimelineEvent(event_id="c", description="Event gamma at pos 2", position=2),
            ],
        )
        assert result.event_count == 3


# ============================================================================
# Pre-analysis Tests
# ============================================================================

class TestPreAnalysis:
    """Tests for temporal signal pre-analysis."""

    def test_analyse_with_timestamps(self):
        from app.services.timeline_reconstruction_service import _analyse_temporal_signals

        events = [
            {"time": "9 PM", "time_uncertainty": None},
            {"time": "10 PM", "time_uncertainty": None},
            {"time": None, "time_uncertainty": "relative — after entering"},
        ]
        result = _analyse_temporal_signals(events)
        assert result["total_events"] == 3
        assert result["with_explicit_time"] == 2
        assert result["with_relative_time"] == 1
        assert result["has_strong_anchors"] is True

    def test_analyse_no_timestamps(self):
        from app.services.timeline_reconstruction_service import _analyse_temporal_signals

        events = [
            {"time": None, "time_uncertainty": None},
            {"time": None, "time_uncertainty": None},
        ]
        result = _analyse_temporal_signals(events)
        assert result["with_explicit_time"] == 0
        assert result["has_strong_anchors"] is False

    def test_prepare_events_normalisation(self):
        from app.services.timeline_reconstruction_service import _prepare_events_for_prompt

        events = [
            {
                "id": "e1",
                "description": "Something happened",
                "timestamp_hint": "9 PM",  # old key name
                "participants": ["Alice"],  # old key name
            },
        ]
        prepared = _prepare_events_for_prompt(events)
        assert prepared[0]["time"] == "9 PM"
        assert prepared[0]["actors"] == ["Alice"]


# ============================================================================
# Post-validation Tests
# ============================================================================

class TestPostValidation:
    """Tests for post-processing and consistency checks."""

    def test_temporal_consistency_valid(self):
        from app.services.timeline_reconstruction_service import _validate_temporal_consistency

        result = TimelineReconstructionResult(
            confirmed_sequence=[
                TimelineEvent(event_id="a", description="An event at position 0", position=0),
                TimelineEvent(event_id="b", description="An event at position 1", position=1),
            ],
            temporal_links=[
                TemporalLink(
                    event_a_id="a", event_b_id="b",
                    link_type="before", strength=0.9,
                ),
            ],
        )
        warnings = _validate_temporal_consistency(result)
        assert len(warnings) == 0

    def test_temporal_consistency_violation(self):
        from app.services.timeline_reconstruction_service import _validate_temporal_consistency

        result = TimelineReconstructionResult(
            confirmed_sequence=[
                TimelineEvent(event_id="a", description="An event marked at position 1", position=1),
                TimelineEvent(event_id="b", description="An event marked at position 0", position=0),
            ],
            temporal_links=[
                TemporalLink(
                    event_a_id="a", event_b_id="b",
                    link_type="before", strength=0.9,  # says a before b, but a.pos > b.pos
                ),
            ],
        )
        warnings = _validate_temporal_consistency(result)
        assert len(warnings) == 1

    def test_ensure_all_events_placed(self):
        from app.services.timeline_reconstruction_service import _ensure_all_events_placed

        result = TimelineReconstructionResult(
            confirmed_sequence=[
                TimelineEvent(event_id="a", description="Event alpha at position 0", position=0),
            ],
        )
        input_ids = {"a", "b"}  # b is missing
        result = _ensure_all_events_placed(input_ids, result)

        all_ids = {e.event_id for e in result.full_sequence}
        assert "b" in all_ids
        assert len(result.uncertain_events) == 1

    def test_ensure_reasoning_complete(self):
        from app.services.timeline_reconstruction_service import _ensure_reasoning_complete

        result = TimelineReconstructionResult(
            confirmed_sequence=[
                TimelineEvent(event_id="a", description="Event alpha at position 0", position=0, placement_confidence="confirmed"),
                TimelineEvent(event_id="b", description="Event beta at position 1", position=1, placement_confidence="probable"),
            ],
            reasoning=[
                PlacementReasoning(
                    event_id="a", placed_at=0,
                    reason="Has an explicit timestamp making it the anchor point",
                    confidence="confirmed",
                ),
            ],
        )
        result = _ensure_reasoning_complete({"a", "b"}, result)
        assert len(result.reasoning) == 2
        reason_ids = {r.event_id for r in result.reasoning}
        assert "b" in reason_ids


# ============================================================================
# Service Integration Tests (mocked LLM)
# ============================================================================

class TestTimelineReconstructionService:
    """Tests for the full reasoning pipeline with mocked LLM."""

    @pytest.fixture()
    def mock_llm_response(self):
        """Realistic LLM response for a 3-event timeline."""
        output = {
            "confirmed_sequence": [
                {
                    "event_id": "evt-A",
                    "description": "Entered the room",
                    "time": "9 PM",
                    "time_uncertainty": "approximate",
                    "location": "room",
                    "actors": ["witness"],
                    "original_confidence": 0.7,
                    "position": 0,
                    "placement_confidence": "confirmed",
                },
            ],
            "probable_sequence": [
                {
                    "event_id": "evt-B",
                    "description": "Heard a loud noise",
                    "time": None,
                    "time_uncertainty": "relative",
                    "location": None,
                    "actors": ["witness"],
                    "original_confidence": 0.6,
                    "position": 1,
                    "placement_confidence": "probable",
                },
            ],
            "uncertain_events": [
                {
                    "event_id": "evt-C",
                    "description": "Saw a broken window",
                    "time": None,
                    "time_uncertainty": None,
                    "location": "room",
                    "actors": ["witness"],
                    "original_confidence": 0.8,
                    "position": 2,
                    "placement_confidence": "uncertain",
                },
            ],
            "reasoning": [
                {
                    "event_id": "evt-A",
                    "placed_at": 0,
                    "reason": "Has an explicit timestamp of 9 PM, making it the temporal anchor for the sequence",
                    "confidence": "confirmed",
                    "evidence": ["explicit timestamp: 9 PM"],
                },
                {
                    "event_id": "evt-B",
                    "placed_at": 1,
                    "reason": "Described as happening after entering, placing it after evt-A with reasonable confidence",
                    "confidence": "probable",
                    "evidence": ["relative marker: after entering"],
                },
                {
                    "event_id": "evt-C",
                    "placed_at": 2,
                    "reason": "No temporal information. Placed after evt-B by narrative flow only, which is weak evidence",
                    "confidence": "uncertain",
                    "evidence": ["narrative flow: mentioned last"],
                },
            ],
            "temporal_links": [
                {
                    "event_a_id": "evt-A",
                    "event_b_id": "evt-B",
                    "link_type": "before",
                    "reason": "evt-B described as happening after entering (evt-A)",
                    "strength": 0.85,
                },
                {
                    "event_a_id": "evt-A",
                    "event_b_id": "evt-C",
                    "link_type": "before",
                    "reason": "Must enter room before seeing what is inside it",
                    "strength": 0.9,
                },
                {
                    "event_a_id": "evt-B",
                    "event_b_id": "evt-C",
                    "link_type": "unknown",
                    "reason": "No evidence establishes ordering between these events",
                    "strength": 0.3,
                },
            ],
        }
        return LLMResponse(
            content=json.dumps(output),
            model="gpt-4o",
            usage={"prompt_tokens": 800, "completion_tokens": 600, "total_tokens": 1400},
        )

    @pytest.fixture()
    def mock_llm(self, mock_llm_response):
        llm = MagicMock()
        llm.complete = AsyncMock(return_value=mock_llm_response)
        return llm

    @pytest.fixture()
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture()
    def sample_events(self):
        return [
            {
                "id": "evt-A",
                "description": "Entered the room",
                "time": "9 PM",
                "time_uncertainty": "approximate",
                "location": "room",
                "actors": ["witness"],
                "confidence": 0.7,
            },
            {
                "id": "evt-B",
                "description": "Heard a loud noise",
                "time": None,
                "time_uncertainty": "relative",
                "location": None,
                "actors": ["witness"],
                "confidence": 0.6,
            },
            {
                "id": "evt-C",
                "description": "Saw a broken window",
                "time": None,
                "time_uncertainty": None,
                "location": "room",
                "actors": ["witness"],
                "confidence": 0.8,
            },
        ]

    @pytest.mark.asyncio
    async def test_reconstruct_from_events(self, mock_db, mock_llm, sample_events):
        from app.services.timeline_reconstruction_service import TimelineReconstructionService

        svc = TimelineReconstructionService(db=mock_db, llm=mock_llm)
        result = await svc.reconstruct_from_events(sample_events)

        assert isinstance(result, TimelineReconstructionResult)
        assert len(result.confirmed_sequence) == 1
        assert len(result.probable_sequence) == 1
        assert len(result.uncertain_events) == 1
        assert result.event_count == 3

        # Verify reasoning exists for all events
        reasoning_ids = {r.event_id for r in result.reasoning}
        assert reasoning_ids == {"evt-A", "evt-B", "evt-C"}

        # Verify temporal links
        assert len(result.temporal_links) == 3

        # Verify ordering
        full = result.full_sequence
        assert full[0].event_id == "evt-A"
        assert full[0].placement_confidence == PlacementConfidence.CONFIRMED

    @pytest.mark.asyncio
    async def test_fallback_on_total_failure(self, mock_db, sample_events):
        """If LLM returns garbage, fallback should produce all-uncertain timeline."""
        bad_response = LLMResponse(
            content="This is not JSON at all, just text with no structure",
            model="gpt-4o",
            usage={},
        )
        llm = MagicMock()
        llm.complete = AsyncMock(return_value=bad_response)

        from app.services.timeline_reconstruction_service import TimelineReconstructionService

        svc = TimelineReconstructionService(db=mock_db, llm=llm)
        result = await svc.reconstruct_from_events(sample_events)

        # Fallback should put all events in uncertain
        assert len(result.confirmed_sequence) == 0
        assert len(result.probable_sequence) == 0
        assert len(result.uncertain_events) == 3
        assert result.reconstruction_metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_missing_events_recovered(self, mock_db):
        """If LLM omits an event, it should be added to uncertain."""
        partial_output = {
            "confirmed_sequence": [
                {
                    "event_id": "evt-A",
                    "description": "Entered the room",
                    "position": 0,
                    "placement_confidence": "confirmed",
                },
            ],
            "probable_sequence": [],
            "uncertain_events": [],
            "reasoning": [
                {
                    "event_id": "evt-A",
                    "placed_at": 0,
                    "reason": "Has timestamp making it the definitive anchor point",
                    "confidence": "confirmed",
                },
            ],
            "temporal_links": [],
        }
        response = LLMResponse(
            content=json.dumps(partial_output),
            model="gpt-4o",
            usage={},
        )
        llm = MagicMock()
        llm.complete = AsyncMock(return_value=response)

        from app.services.timeline_reconstruction_service import TimelineReconstructionService

        svc = TimelineReconstructionService(db=mock_db, llm=llm)
        result = await svc.reconstruct_from_events([
            {"id": "evt-A", "description": "Entered the room", "time": "9 PM"},
            {"id": "evt-B", "description": "Heard noise", "time": None},
        ])

        all_ids = {e.event_id for e in result.full_sequence}
        assert "evt-B" in all_ids  # recovered
        assert len(result.uncertain_events) >= 1
