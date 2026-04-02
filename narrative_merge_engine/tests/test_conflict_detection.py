"""
Tests for the Conflict Detection & Merge Intelligence Layer.

Covers:
  - Pydantic schema validation (DetectedConflict, MergeConflictBlock, etc.)
  - Git-style merge block rendering
  - Impact scoring and normalisation
  - Category and severity normalisation
  - Pre-processing helpers (branch grouping, overlap analysis)
  - Post-validation (conflict ID linking, impact consistency)
  - Service-level detection with mocked LLM (full pipeline)
  - Edge cases: no conflicts, single branch, all uncertain, fallback mode
  - NextBestQuestion validation
  - Conflict graph edge typing
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.ai.base_provider import LLMResponse
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


# ============================================================================
# Schema Tests
# ============================================================================

class TestMergeConflictBlock:
    """Tests for the Git-style merge conflict renderer."""

    def test_render_basic(self):
        block = MergeConflictBlock(
            branch_a_label="Witness_A",
            branch_a_text="Entered at 9 PM",
            branch_b_label="Witness_B",
            branch_b_text="Entered at 10 PM",
        )
        rendered = block.render()
        assert "<<<<<<< Witness_A" in rendered
        assert "Entered at 9 PM" in rendered
        assert "=======" in rendered
        assert "Entered at 10 PM" in rendered
        assert ">>>>>>> Witness_B" in rendered

    def test_render_multiline(self):
        block = MergeConflictBlock(
            branch_a_label="Timeline_A",
            branch_a_text="Saw a person near table\nPerson was wearing blue",
            branch_b_label="Timeline_B",
            branch_b_text="Saw no one",
        )
        rendered = block.render()
        assert "Saw a person near table\nPerson was wearing blue" in rendered
        assert "Saw no one" in rendered


class TestDetectedConflict:
    """Tests for the DetectedConflict model."""

    def test_basic_conflict(self):
        conflict = DetectedConflict(
            category="temporal",
            severity="high",
            description="Entry time disagrees: 9 PM vs 10 PM",
            event_a_id="a1",
            event_b_id="b1",
            merge_block=MergeConflictBlock(
                branch_a_label="A", branch_a_text="9 PM",
                branch_b_label="B", branch_b_text="10 PM",
            ),
        )
        assert conflict.category == ConflictCategory.TEMPORAL
        assert conflict.severity == ConflictSeverityLevel.HIGH

    def test_category_normalisation(self):
        for input_val, expected in [
            ("temporal", ConflictCategory.TEMPORAL),
            ("time", ConflictCategory.TEMPORAL),
            ("timing", ConflictCategory.TEMPORAL),
            ("spatial", ConflictCategory.SPATIAL),
            ("location", ConflictCategory.SPATIAL),
            ("place", ConflictCategory.SPATIAL),
            ("logical", ConflictCategory.LOGICAL),
            ("factual", ConflictCategory.LOGICAL),
            ("contradiction", ConflictCategory.LOGICAL),
            ("entity", ConflictCategory.ENTITY),
            ("person", ConflictCategory.ENTITY),
            ("participant", ConflictCategory.ENTITY),
            ("sequence", ConflictCategory.SEQUENCE),
            ("order", ConflictCategory.SEQUENCE),
            ("causal", ConflictCategory.CAUSAL),
        ]:
            conflict = DetectedConflict(
                category=input_val,
                description=f"Test conflict for category normalisation {input_val}",
                event_a_id="a", event_b_id="b",
                merge_block=MergeConflictBlock(
                    branch_a_label="A", branch_a_text="x",
                    branch_b_label="B", branch_b_text="y",
                ),
            )
            assert conflict.category == expected, f"Failed for {input_val}"

    def test_severity_normalisation(self):
        for input_val, expected in [
            ("low", ConflictSeverityLevel.LOW),
            ("minor", ConflictSeverityLevel.LOW),
            ("medium", ConflictSeverityLevel.MEDIUM),
            ("moderate", ConflictSeverityLevel.MEDIUM),
            ("high", ConflictSeverityLevel.HIGH),
            ("major", ConflictSeverityLevel.HIGH),
            ("critical", ConflictSeverityLevel.CRITICAL),
            ("extreme", ConflictSeverityLevel.CRITICAL),
        ]:
            conflict = DetectedConflict(
                category="temporal",
                severity=input_val,
                description=f"Test severity mapping for the value {input_val}",
                event_a_id="a", event_b_id="b",
                merge_block=MergeConflictBlock(
                    branch_a_label="A", branch_a_text="x",
                    branch_b_label="B", branch_b_text="y",
                ),
            )
            assert conflict.severity == expected, f"Failed for {input_val}"


class TestConflictImpact:
    """Tests for impact scoring."""

    def test_basic_impact(self):
        impact = ConflictImpact(
            impact_score=0.85,
            affected_event_count=3,
            reasoning="High impact due to temporal anchor disruption",
        )
        assert impact.impact_score == 0.85
        assert impact.affected_event_count == 3

    def test_clamp_percentage_string(self):
        impact = ConflictImpact(
            impact_score="75%",
            affected_event_count=2,
        )
        assert impact.impact_score == 0.75

    def test_clamp_over_one(self):
        impact = ConflictImpact(
            impact_score=85,
            affected_event_count=1,
        )
        assert impact.impact_score == 0.85


class TestMergedEvent:
    """Tests for partial merge event status."""

    def test_status_normalisation(self):
        for input_val, expected in [
            ("confirmed", MergeStatus.CONFIRMED),
            ("agreed", MergeStatus.CONFIRMED),
            ("conflicted", MergeStatus.CONFLICTED),
            ("disputed", MergeStatus.CONFLICTED),
            ("uncertain", MergeStatus.UNCERTAIN),
            ("unknown", MergeStatus.UNCERTAIN),
        ]:
            event = MergedEvent(
                event_id="e1",
                description="Test merged event",
                status=input_val,
            )
            assert event.status == expected, f"Failed for {input_val}"


class TestNextBestQuestion:
    """Tests for the investigator question model."""

    def test_valid_question(self):
        nbq = NextBestQuestion(
            question="Can you describe what you were doing just before you entered?",
            target_conflict_id="conflict-1",
            why_this_question="This resolves the foundational temporal anchor conflict",
            expected_resolution="Establishes actual entry time",
        )
        assert "before you entered" in nbq.question

    def test_min_length_enforcement(self):
        with pytest.raises(Exception):
            NextBestQuestion(
                question="When?",  # too short for a meaningful investigator question
                why_this_question="Important because it resolves the temporal anchor",
            )


class TestConflictGraphEdge:
    """Tests for graph edge typing."""

    def test_edge_type_normalisation(self):
        for input_val, expected in [
            ("agreement", GraphEdgeType.AGREEMENT),
            ("agree", GraphEdgeType.AGREEMENT),
            ("match", GraphEdgeType.AGREEMENT),
            ("conflict", GraphEdgeType.CONFLICT),
            ("disagree", GraphEdgeType.CONFLICT),
            ("contradiction", GraphEdgeType.CONFLICT),
            ("partial", GraphEdgeType.PARTIAL),
            ("overlap", GraphEdgeType.PARTIAL),
            ("independent", GraphEdgeType.INDEPENDENT),
            ("unrelated", GraphEdgeType.INDEPENDENT),
        ]:
            edge = ConflictGraphEdge(
                event_a_id="a", event_b_id="b",
                edge_type=input_val,
            )
            assert edge.edge_type == expected, f"Failed for {input_val}"


class TestConflictDetectionResult:
    """Tests for the top-level result model."""

    def test_highest_impact(self):
        result = ConflictDetectionResult(
            conflicts=[
                DetectedConflict(
                    category="temporal",
                    description="Low impact temporal conflict on minor times",
                    event_a_id="a1", event_b_id="b1",
                    merge_block=MergeConflictBlock(
                        branch_a_label="A", branch_a_text="x",
                        branch_b_label="B", branch_b_text="y",
                    ),
                    impact=ConflictImpact(impact_score=0.3, affected_event_count=1),
                ),
                DetectedConflict(
                    category="logical",
                    description="High impact logical conflict on key event",
                    event_a_id="a2", event_b_id="b2",
                    merge_block=MergeConflictBlock(
                        branch_a_label="A", branch_a_text="x",
                        branch_b_label="B", branch_b_text="y",
                    ),
                    impact=ConflictImpact(impact_score=0.9, affected_event_count=5),
                ),
            ],
        )
        highest = result.highest_impact_conflict
        assert highest is not None
        assert highest.impact.impact_score == 0.9

    def test_render_full_diff(self):
        result = ConflictDetectionResult(
            conflicts=[
                DetectedConflict(
                    category="temporal",
                    description="Time disagrees on entry between two witnesses",
                    event_a_id="a1", event_b_id="b1",
                    merge_block=MergeConflictBlock(
                        branch_a_label="Witness_A",
                        branch_a_text="Entered at 9 PM",
                        branch_b_label="Witness_B",
                        branch_b_text="Entered at 10 PM",
                    ),
                ),
            ],
        )
        diff = result.render_full_diff()
        assert "<<<<<<< Witness_A" in diff
        assert ">>>>>>> Witness_B" in diff
        assert "9 PM" in diff
        assert "10 PM" in diff


# ============================================================================
# Pre-processing Tests
# ============================================================================

class TestPreProcessing:
    """Tests for branch preparation helpers."""

    def test_build_branches_from_timeline(self):
        from app.services.conflict_detection_service import _build_branches_from_timeline

        events = [
            {"id": "a1", "testimony_id": "tid-aaaa-bbbb", "description": "Event A1"},
            {"id": "a2", "testimony_id": "tid-aaaa-bbbb", "description": "Event A2"},
            {"id": "b1", "testimony_id": "tid-cccc-dddd", "description": "Event B1"},
        ]
        branches = _build_branches_from_timeline(events)
        assert len(branches) == 2

    def test_analyse_branch_overlap(self):
        from app.services.conflict_detection_service import _analyse_branch_overlap

        branches = {
            "Witness_A": [
                {"id": "a1", "location": "entrance", "time": "9 PM"},
                {"id": "a2", "location": "dining room"},
            ],
            "Witness_B": [
                {"id": "b1", "location": "entrance", "time": "10 PM"},
            ],
        }
        overlap = _analyse_branch_overlap(branches)
        assert overlap["branch_count"] == 2
        assert overlap["total_events"] == 3
        assert overlap["unique_times"] == 2

    def test_prepare_branches_for_prompt(self):
        from app.services.conflict_detection_service import _prepare_branches_for_prompt

        branches = {
            "Witness_A": [{"id": "a1", "description": "Entered"}],
            "Witness_B": [{"id": "b1", "description": "Left"}],
        }
        result = _prepare_branches_for_prompt(branches)
        assert "BRANCH: Witness_A" in result
        assert "BRANCH: Witness_B" in result
        assert "Entered" in result


# ============================================================================
# Post-validation Tests
# ============================================================================

class TestPostValidation:
    """Tests for post-processing helpers."""

    def test_ensure_conflict_ids_linked(self):
        from app.services.conflict_detection_service import _ensure_conflict_ids_linked

        result = ConflictDetectionResult(
            conflicts=[
                DetectedConflict(
                    id="c1",
                    category="temporal",
                    description="Time conflict between entry events A and B",
                    event_a_id="a1", event_b_id="b1",
                    merge_block=MergeConflictBlock(
                        branch_a_label="A", branch_a_text="9PM",
                        branch_b_label="B", branch_b_text="10PM",
                    ),
                ),
            ],
            conflicted_events=[
                MergedEvent(event_id="a1", description="Entry", status="conflicted"),
            ],
        )
        result = _ensure_conflict_ids_linked(result)
        assert "c1" in result.conflicted_events[0].conflict_ids

    def test_validate_impact_consistency_mismatch(self):
        from app.services.conflict_detection_service import _validate_impact_consistency

        result = ConflictDetectionResult(
            conflicts=[
                DetectedConflict(
                    category="temporal",
                    severity="low",
                    description="Minor detail conflict but with high impact score",
                    event_a_id="a1", event_b_id="b1",
                    merge_block=MergeConflictBlock(
                        branch_a_label="A", branch_a_text="x",
                        branch_b_label="B", branch_b_text="y",
                    ),
                    impact=ConflictImpact(impact_score=0.9, affected_event_count=5),
                ),
            ],
        )
        warnings = _validate_impact_consistency(result)
        assert len(warnings) >= 1  # low severity + high impact = warning


# ============================================================================
# Service Integration Tests (mocked LLM)
# ============================================================================

class TestConflictDetectionService:
    """Tests for the full detection pipeline with mocked LLM."""

    @pytest.fixture()
    def mock_llm_response(self):
        """Realistic LLM response for 2-branch conflict detection."""
        output = {
            "conflicts": [
                {
                    "id": "conflict-1",
                    "category": "temporal",
                    "severity": "high",
                    "description": "Entry time mismatch: Witness A says 9 PM, Witness B says 10 PM",
                    "event_a_id": "a1",
                    "event_b_id": "b1",
                    "branch_a": "Witness_A",
                    "branch_b": "Witness_B",
                    "merge_block": {
                        "branch_a_label": "Witness_A",
                        "branch_a_text": "Entered at 9 PM",
                        "branch_b_label": "Witness_B",
                        "branch_b_text": "Entered at 10 PM",
                    },
                    "impact": {
                        "impact_score": 0.85,
                        "affected_event_count": 3,
                        "affected_event_ids": ["a2", "a3", "b2"],
                        "reasoning": "Entry time is the temporal anchor for everything",
                    },
                    "reasoning": "Mutually exclusive timestamps for the same event",
                },
                {
                    "id": "conflict-2",
                    "category": "logical",
                    "severity": "high",
                    "description": "Presence conflict: person vs no one in the room",
                    "event_a_id": "a2",
                    "event_b_id": "b2",
                    "branch_a": "Witness_A",
                    "branch_b": "Witness_B",
                    "merge_block": {
                        "branch_a_label": "Witness_A",
                        "branch_a_text": "Saw a person near the table",
                        "branch_b_label": "Witness_B",
                        "branch_b_text": "Saw no one in the room",
                    },
                    "impact": {
                        "impact_score": 0.6,
                        "affected_event_count": 1,
                        "affected_event_ids": [],
                        "reasoning": "Person presence affects motive analysis",
                    },
                    "reasoning": "Logically exclusive observations at same location",
                },
            ],
            "confirmed_events": [
                {
                    "event_id": "noise-shared",
                    "description": "Heard a loud noise",
                    "status": "confirmed",
                    "branches_confirming": ["Witness_A", "Witness_B"],
                },
            ],
            "conflicted_events": [
                {
                    "event_id": "a1",
                    "description": "Entry time",
                    "status": "conflicted",
                    "conflict_ids": ["conflict-1"],
                },
                {
                    "event_id": "a2",
                    "description": "Person presence",
                    "status": "conflicted",
                    "conflict_ids": ["conflict-2"],
                },
            ],
            "uncertain_events": [],
            "next_best_question": {
                "question": "Can you describe what you were doing just before you entered the room?",
                "target_conflict_id": "conflict-1",
                "why_this_question": "The entry time is the temporal anchor — resolving it reframes all downstream events",
                "expected_resolution": "Determines actual entry time via external reference points",
            },
            "conflict_graph": [
                {
                    "event_a_id": "a1", "event_b_id": "b1",
                    "edge_type": "conflict", "weight": 0.85,
                    "description": "Temporal: 9 PM vs 10 PM",
                },
                {
                    "event_a_id": "a2", "event_b_id": "b2",
                    "edge_type": "conflict", "weight": 0.6,
                    "description": "Logical: person vs no one",
                },
                {
                    "event_a_id": "a3", "event_b_id": "b3",
                    "edge_type": "agreement", "weight": 0.8,
                    "description": "Both heard a noise",
                },
            ],
        }
        return LLMResponse(
            content=json.dumps(output),
            model="gpt-4o",
            usage={"prompt_tokens": 1200, "completion_tokens": 800},
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
    def sample_branches(self):
        return {
            "Witness_A": [
                {"id": "a1", "description": "Entered at 9 PM", "time": "9 PM", "location": "entrance"},
                {"id": "a2", "description": "Saw a person near the table", "location": "dining room"},
                {"id": "a3", "description": "Heard a loud noise", "time": "9:30 PM"},
            ],
            "Witness_B": [
                {"id": "b1", "description": "Entered at 10 PM", "time": "10 PM", "location": "entrance"},
                {"id": "b2", "description": "Saw no one in the room", "location": "dining room"},
                {"id": "b3", "description": "Heard a loud noise", "time": "10:15 PM"},
            ],
        }

    @pytest.mark.asyncio
    async def test_detect_from_branches(self, mock_db, mock_llm, sample_branches):
        from app.services.conflict_detection_service import ConflictDetectionService

        svc = ConflictDetectionService(db=mock_db, llm=mock_llm)
        result = await svc.detect_from_branches(sample_branches)

        assert isinstance(result, ConflictDetectionResult)
        assert len(result.conflicts) == 2
        assert result.conflict_count == 2

        # Verify merge block rendering
        assert all(c.merge_block for c in result.conflicts)
        for c in result.conflicts:
            rendered = c.merge_block.render()
            assert "<<<<<<<" in rendered
            assert "=======" in rendered
            assert ">>>>>>>" in rendered

        # Verify partial merge
        assert len(result.confirmed_events) == 1
        assert len(result.conflicted_events) == 2

        # Verify next-best-question
        assert result.next_best_question is not None
        assert "conflict-1" in result.next_best_question.target_conflict_id

        # Verify conflict graph
        assert len(result.conflict_graph) == 3

        # Verify full diff string
        assert result.merge_diff
        assert "<<<<<<< Witness_A" in result.merge_diff

    @pytest.mark.asyncio
    async def test_highest_impact_identified(self, mock_db, mock_llm, sample_branches):
        from app.services.conflict_detection_service import ConflictDetectionService

        svc = ConflictDetectionService(db=mock_db, llm=mock_llm)
        result = await svc.detect_from_branches(sample_branches)

        highest = result.highest_impact_conflict
        assert highest is not None
        assert highest.impact.impact_score == 0.85
        assert highest.category == ConflictCategory.TEMPORAL

    @pytest.mark.asyncio
    async def test_fallback_on_total_failure(self, mock_db, sample_branches):
        """If LLM returns garbage, fallback should produce empty conflicts."""
        bad_response = LLMResponse(
            content="This is definitely not JSON at all",
            model="gpt-4o",
            usage={},
        )
        llm = MagicMock()
        llm.complete = AsyncMock(return_value=bad_response)

        from app.services.conflict_detection_service import ConflictDetectionService

        svc = ConflictDetectionService(db=mock_db, llm=llm)
        result = await svc.detect_from_branches(sample_branches)

        assert len(result.conflicts) == 0
        assert len(result.uncertain_events) > 0
        assert result.detection_metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_git_diff_rendering(self, mock_db, mock_llm, sample_branches):
        """Verify the full Git-style diff output."""
        from app.services.conflict_detection_service import ConflictDetectionService

        svc = ConflictDetectionService(db=mock_db, llm=mock_llm)
        result = await svc.detect_from_branches(sample_branches)

        diff = result.merge_diff
        # Should contain both conflict blocks
        assert diff.count("<<<<<<<") == 2
        assert diff.count(">>>>>>>") == 2
        assert "Witness_A" in diff
        assert "Witness_B" in diff
