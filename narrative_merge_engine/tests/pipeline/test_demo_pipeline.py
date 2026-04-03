"""
Comprehensive unit tests for the DemoPipeline orchestrator.

Strategy:
  - All external services (EventExtractionService, TimelineReconstructionService,
    ConflictDetectionService, SpeechToTextService) are mocked with AsyncMock.
  - Tests validate DemoPipeline's fault isolation: a failure in one stage must
    NOT crash the pipeline — it degrades status and appends an error.
  - No real LLM or DB calls are made.

Test groups:
  1. Happy path   — all stages succeed → PipelineStatus.SUCCESS
  2. STT failures — audio-mode failures gracefully fall back to text
  3. Extraction   — timeout + exception fallbacks + 0-event result
  4. Timeline     — timeout + exception → _fallback_timeline shapes
  5. Conflicts    — timeout + exception → StrictConflictResult default
  6. Multi-witness concurrent extraction — both branches run, isolation hold
  7. fast_preview — timeline + conflict stages are skipped
  8. Full blackout — every stage fails → FALLBACK status, sample data used
  9. Status ratchet — SUCCESS → PARTIAL → FALLBACK never reverses
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas.conflict_strict import StrictConflictResult, StrictEvent
from app.models.schemas.event_extraction import ExtractedEvent, ExtractionResult
from app.models.schemas.timeline_reconstruction import (
    PlacementConfidence,
    TimelineEvent,
    TimelineReconstructionResult,
)
from app.services.demo_pipeline import (
    DemoPipeline,
    PipelineResult,
    PipelineStatus,
    _DEMO_SAMPLE_TRANSCRIPT,
    _downgrade_status,
    _event_to_dict,
    _fallback_timeline,
    _text_to_fallback_events,
)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_event(
    description: str = "Something happened",
    eid: str | None = None,
    confidence: float = 0.75,
) -> ExtractedEvent:
    return ExtractedEvent(
        id=eid or str(uuid.uuid4()),
        description=description,
        time="around midnight",
        time_uncertainty="hedged",
        location="lobby",
        actors=["witness"],
        confidence=confidence,
        source_text=description.lower(),
    )


def _make_extraction_result(*events: ExtractedEvent) -> ExtractionResult:
    return ExtractionResult(
        events=list(events),
        raw_event_count=len(events),
        dropped_event_count=0,
        extraction_metadata={"elapsed_ms": 100.0},
    )


def _make_timeline(events: list[ExtractedEvent]) -> TimelineReconstructionResult:
    probable = [
        TimelineEvent(
            event_id=e.id,
            description=e.description,
            position=i,
            placement_confidence=PlacementConfidence.PROBABLE,
        )
        for i, e in enumerate(events)
    ]
    return TimelineReconstructionResult(probable_sequence=probable)


def _make_pipeline(
    extraction_result: ExtractionResult | None = None,
    timeline_result: TimelineReconstructionResult | None = None,
    conflict_result: StrictConflictResult | None = None,
    stt_text: str = "some transcribed testimony text",
    extraction_side_effect=None,
    timeline_side_effect=None,
    conflict_side_effect=None,
) -> DemoPipeline:
    """Build a DemoPipeline with fully mocked services."""
    event_svc = MagicMock()
    timeline_svc = MagicMock()
    conflict_svc = MagicMock()
    stt_svc = MagicMock()

    # Default extraction
    if extraction_side_effect is not None:
        event_svc.extract_events_from_text = AsyncMock(side_effect=extraction_side_effect)
    else:
        result = extraction_result or _make_extraction_result(_make_event())
        event_svc.extract_events_from_text = AsyncMock(return_value=result)

    # Default timeline
    if timeline_side_effect is not None:
        timeline_svc.reconstruct_from_events = AsyncMock(side_effect=timeline_side_effect)
    else:
        tl = timeline_result or _make_timeline([_make_event()])
        timeline_svc.reconstruct_from_events = AsyncMock(return_value=tl)

    # Default conflicts
    if conflict_side_effect is not None:
        conflict_svc.detect_strict = AsyncMock(side_effect=conflict_side_effect)
    else:
        cr = conflict_result or StrictConflictResult()
        conflict_svc.detect_strict = AsyncMock(return_value=cr)

    # STT
    from app.services.speech_to_text_service import TranscriptResult
    stt_svc.transcribe = AsyncMock(
        return_value=TranscriptResult(text=stt_text, detected_language="en")
    )

    pipeline = DemoPipeline(
        event_svc=event_svc,
        timeline_svc=timeline_svc,
        conflict_svc=conflict_svc,
        stt_svc=stt_svc,
    )

    # Patch testimony analysis — avoids real Groq calls
    patcher_testimony = patch(
        "app.services.demo_pipeline.analyze_testimony_sensitivity",
        new_callable=AsyncMock
    )
    mock_analyze = patcher_testimony.start()
    from app.models.schemas.testimony_analysis import TestimonyAnalysisResult, EmotionCategory, ConfidenceLevel
    mock_analyze.return_value = TestimonyAnalysisResult(
        emotion=EmotionCategory.NEUTRAL,
        uncertainty_signals=[],
        confidence_level=ConfidenceLevel.MEDIUM
    )

    # Patch report generation — avoids real primary LLM calls
    patcher_report = patch(
        "app.services.demo_pipeline.generate_final_report",
        new_callable=AsyncMock
    )
    mock_report = patcher_report.start()
    from app.models.schemas.report import ReportGenerationResult
    mock_report.return_value = ReportGenerationResult(
        summary="Test summary.",
        key_events=["Event A occurred.", "Event B followed."],
        conflicts=[],
        emotional_analysis="Witness appeared calm.",
        uncertainty_analysis="No significant uncertainty detected.",
        recommended_next_steps=["Review CCTV footage."],
    )

    import atexit
    atexit.register(patcher_testimony.stop)
    atexit.register(patcher_report.stop)

    return pipeline


# ══════════════════════════════════════════════════════════════════════════════
# 1. Happy path
# ══════════════════════════════════════════════════════════════════════════════

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_text_input_success(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="I entered around 9 PM")

        assert isinstance(result, PipelineResult)
        assert result.status == PipelineStatus.SUCCESS
        assert result.errors == []
        assert len(result.events) >= 1
        assert "probable_sequence" in result.timeline or "confirmed_sequence" in result.timeline
        assert "conflict_count" in result.conflicts or isinstance(result.conflicts, dict)
        assert result.pipeline_id is not None

    @pytest.mark.asyncio
    async def test_result_always_has_all_keys(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="witness saw a dark figure")

        d = result.to_dict()
        required_keys = {
            "pipeline_id", "transcript", "events", "timeline",
            "conflicts", "status", "errors", "stage_timings_ms",
            "demo_mode", "fast_preview",
        }
        assert required_keys.issubset(d.keys())

    @pytest.mark.asyncio
    async def test_demo_mode_flag_propagates(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="something happened", demo_mode=True)
        assert result.demo_mode is True

    @pytest.mark.asyncio
    async def test_stage_timings_populated(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="the witness left at noon")
        assert "extraction_ms" in result.stage_timings
        assert "timeline_ms" in result.stage_timings
        assert "conflicts_ms" in result.stage_timings
        assert "total_ms" in result.stage_timings
        assert result.stage_timings["total_ms"] >= 0  # may be 0.0 when services are mocked


# ══════════════════════════════════════════════════════════════════════════════
# 2. STT failures
# ══════════════════════════════════════════════════════════════════════════════

class TestSTTFailures:
    @pytest.mark.asyncio
    async def test_stt_timeout_falls_back_gracefully(self):
        pipeline = _make_pipeline(stt_text="anything")
        pipeline._stt_svc.transcribe = AsyncMock(side_effect=asyncio.TimeoutError())

        result = await pipeline.run(audio=b"fake-audio", filename="test.wav")

        # Pipeline must not crash
        assert isinstance(result, PipelineResult)
        assert result.status != PipelineStatus.SUCCESS  # must degrade
        assert any("STT" in e or "timed out" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_stt_exception_falls_back_gracefully(self):
        pipeline = _make_pipeline()
        pipeline._stt_svc.transcribe = AsyncMock(
            side_effect=RuntimeError("Whisper API connection refused")
        )

        result = await pipeline.run(audio=b"bytes", filename="speech.webm")
        assert isinstance(result, PipelineResult)
        assert any("STT" in e or "error" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_no_audio_no_text_uses_sample(self):
        pipeline = _make_pipeline()
        result = await pipeline.run()  # nothing provided

        assert _DEMO_SAMPLE_TRANSCRIPT in result.transcript or result.transcript != ""
        assert any("sample" in e.lower() or "No input" in e for e in result.errors)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Extraction failures
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractionFailures:
    @pytest.mark.asyncio
    async def test_extraction_timeout_returns_fallback_event(self):
        pipeline = _make_pipeline(extraction_side_effect=asyncio.TimeoutError())
        result = await pipeline.run(text="I was at the store when it happened")

        assert isinstance(result, PipelineResult)
        assert result.status != PipelineStatus.SUCCESS
        assert len(result.events) >= 1  # fallback event present
        assert any("timed out" in e or "extraction" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_extraction_exception_returns_fallback_event(self):
        pipeline = _make_pipeline(extraction_side_effect=ValueError("LLM returned gibberish"))
        result = await pipeline.run(text="I saw someone near the door")

        assert isinstance(result, PipelineResult)
        assert len(result.events) >= 1  # fallback event

    @pytest.mark.asyncio
    async def test_zero_events_degrades_status(self):
        empty_result = _make_extraction_result()  # no events
        pipeline = _make_pipeline(extraction_result=empty_result)
        result = await pipeline.run(text="uh... I think... I don't know")

        assert result.status != PipelineStatus.SUCCESS
        assert any("0 events" in e or "empty" in e.lower() or "too short" in e.lower()
                   for e in result.errors)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Timeline failures
# ══════════════════════════════════════════════════════════════════════════════

class TestTimelineFailures:
    @pytest.mark.asyncio
    async def test_timeline_timeout_uses_fallback_ordering(self):
        pipeline = _make_pipeline(timeline_side_effect=asyncio.TimeoutError())
        result = await pipeline.run(text="something occurred and then another thing")

        assert isinstance(result, PipelineResult)
        assert result.status != PipelineStatus.SUCCESS
        # Fallback timeline still has uncertain_events
        assert "uncertain_events" in result.timeline
        assert any("timeline" in e.lower() or "timed out" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_timeline_exception_uses_fallback_ordering(self):
        pipeline = _make_pipeline(
            timeline_side_effect=RuntimeError("Timeline LLM call crashed")
        )
        result = await pipeline.run(text="I heard the noise and then ran outside")

        assert isinstance(result, PipelineResult)
        assert "uncertain_events" in result.timeline

    @pytest.mark.asyncio
    async def test_no_events_skips_timeline(self):
        """If extraction yields nothing, timeline must still be a valid dict."""
        empty_result = _make_extraction_result()
        pipeline = _make_pipeline(extraction_result=empty_result)
        result = await pipeline.run(text="...")

        assert isinstance(result.timeline, dict)
        assert "uncertain_events" in result.timeline or "event_count" in result.timeline


# ══════════════════════════════════════════════════════════════════════════════
# 5. Conflict detection failures
# ══════════════════════════════════════════════════════════════════════════════

class TestConflictFailures:
    @pytest.mark.asyncio
    async def test_conflict_timeout_returns_empty_result(self):
        pipeline = _make_pipeline(conflict_side_effect=asyncio.TimeoutError())
        result = await pipeline.run(text="I arrived at 9. My friend said 10.")

        assert isinstance(result, PipelineResult)
        assert result.status != PipelineStatus.SUCCESS
        assert "conflict_count" in result.conflicts
        assert result.conflicts["conflict_count"] == 0
        assert any("conflict" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_conflict_exception_returns_empty_result(self):
        pipeline = _make_pipeline(
            conflict_side_effect=RuntimeError("Groq 503 Service Unavailable")
        )
        result = await pipeline.run(text="we were both there but at different times")

        assert isinstance(result, PipelineResult)
        assert result.conflicts["has_conflicts"] is False

    @pytest.mark.asyncio
    async def test_conflicts_populated_on_success(self):
        conflict = StrictConflictResult(
            confirmed_events=[
                StrictEvent(event_id="e1", description="Heard noise", witnesses=["A", "B"])
            ],
        )
        pipeline = _make_pipeline(conflict_result=conflict)
        result = await pipeline.run(text="we both heard the noise at the scene")

        assert result.conflicts["conflict_count"] == 0  # no conflicts in this result
        assert len(result.conflicts["confirmed_events"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. Multi-witness concurrent extraction
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiWitnessExtraction:
    @pytest.mark.asyncio
    async def test_both_branches_extracted_concurrently(self):
        call_log: list[str] = []

        async def extraction_side_effect(text: str, **kwargs) -> ExtractionResult:
            call_log.append(text[:20])
            await asyncio.sleep(0)  # yield to event loop
            return _make_extraction_result(_make_event(f"event from: {text[:20]}"))

        pipeline = _make_pipeline()
        pipeline._event_svc.extract_events_from_text = AsyncMock(
            side_effect=extraction_side_effect
        )

        branches = {
            "Witness_A": "I entered at 9 PM and saw no one.",
            "Witness_B": "I arrived at 10 PM and saw the suspect.",
        }
        result = await pipeline.run(branches_override=branches)

        assert len(call_log) == 2  # both were called
        assert len(result.events) == 2
        assert result.status == PipelineStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_single_branch_failure_does_not_cancel_sibling(self):
        call_count = 0

        async def extraction_side_effect(text: str, **kwargs) -> ExtractionResult:
            nonlocal call_count
            call_count += 1
            if "B" in text or "suspect" in text:
                raise RuntimeError("Branch B extraction failed")
            return _make_extraction_result(_make_event("Branch A event"))

        pipeline = _make_pipeline()
        pipeline._event_svc.extract_events_from_text = AsyncMock(
            side_effect=extraction_side_effect
        )

        branches = {
            "Witness_A": "I entered at 9 PM and saw the door open.",
            "Witness_B": "suspect was visible",  # will raise
        }
        result = await pipeline.run(branches_override=branches)

        # Pipeline must not crash; Branch A events survive
        assert isinstance(result, PipelineResult)
        assert len(result.events) >= 1  # A's event present
        # Status degraded due to Branch B failure
        assert result.status != PipelineStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_three_branches_all_extracted(self):
        pipeline = _make_pipeline()

        branches = {
            "A": "I was at the front door when it started.",
            "B": "I heard a loud crash from the kitchen.",
            "C": "There was shouting from upstairs.",
        }
        result = await pipeline.run(branches_override=branches)

        # 1 event per branch × 3 = 3 total
        assert len(result.events) == 3
        assert result.status == PipelineStatus.SUCCESS


# ══════════════════════════════════════════════════════════════════════════════
# 7. fast_preview mode
# ══════════════════════════════════════════════════════════════════════════════

class TestFastPreview:
    @pytest.mark.asyncio
    async def test_fast_preview_skips_timeline_and_conflicts(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="I saw someone leave", fast_preview=True)

        assert result.fast_preview is True
        # Timeline and conflict services must NOT have been called
        pipeline._timeline_svc.reconstruct_from_events.assert_not_called()
        pipeline._conflict_svc.detect_strict.assert_not_called()

    @pytest.mark.asyncio
    async def test_fast_preview_returns_trivial_timeline(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="something happened fast", fast_preview=True)

        # Trivial timeline has uncertain_events and fast_preview metadata
        assert result.timeline.get("metadata", {}).get("fast_preview") is True
        assert "uncertain_events" in result.timeline

    @pytest.mark.asyncio
    async def test_fast_preview_status_is_partial(self):
        """fast_preview always produces at least PARTIAL (since we skipped stages)."""
        pipeline = _make_pipeline()
        result = await pipeline.run(text="the event timeline was incomplete", fast_preview=True)
        assert result.status != PipelineStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_fast_preview_has_events(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(text="I left before midnight", fast_preview=True)
        assert len(result.events) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 8. Full blackout — every stage fails
# ══════════════════════════════════════════════════════════════════════════════

class TestFullBlackout:
    @pytest.mark.asyncio
    async def test_all_stages_fail_status_is_fallback(self):
        pipeline = _make_pipeline(
            extraction_side_effect=RuntimeError("service down"),
            timeline_side_effect=RuntimeError("service down"),
            conflict_side_effect=RuntimeError("service down"),
        )
        pipeline._stt_svc.transcribe = AsyncMock(side_effect=RuntimeError("STT down"))

        # Even with audio — should not crash
        result = await pipeline.run(audio=b"audio", filename="b.wav")

        assert isinstance(result, PipelineResult)
        assert result.status == PipelineStatus.FALLBACK
        assert len(result.errors) >= 2  # at least extraction + conflicts

    @pytest.mark.asyncio
    async def test_all_stages_fail_output_all_keys_present(self):
        pipeline = _make_pipeline(
            extraction_side_effect=RuntimeError("down"),
            timeline_side_effect=RuntimeError("down"),
            conflict_side_effect=RuntimeError("down"),
        )
        result = await pipeline.run(text="anything")

        d = result.to_dict()
        for key in ["pipeline_id", "transcript", "events", "timeline",
                    "conflicts", "status", "errors", "stage_timings_ms"]:
            assert key in d, f"Missing key '{key}' in blackout result"


# ══════════════════════════════════════════════════════════════════════════════
# 9. Status ratchet
# ══════════════════════════════════════════════════════════════════════════════

class TestStatusRatchet:
    def test_success_to_partial(self):
        result = PipelineResult()
        assert result.status == PipelineStatus.SUCCESS
        _downgrade_status(result)
        assert result.status == PipelineStatus.PARTIAL

    def test_partial_to_fallback(self):
        result = PipelineResult(status=PipelineStatus.PARTIAL)
        _downgrade_status(result)
        assert result.status == PipelineStatus.FALLBACK

    def test_fallback_stays_fallback(self):
        result = PipelineResult(status=PipelineStatus.FALLBACK)
        _downgrade_status(result)
        _downgrade_status(result)  # extra calls must not break anything
        assert result.status == PipelineStatus.FALLBACK

    def test_status_never_upgrades(self):
        result = PipelineResult(status=PipelineStatus.FALLBACK)
        # Directly setting to SUCCESS (simulating a bad caller) and ratcheting back
        result.status = PipelineStatus.SUCCESS  # hypothetical bad assignment
        _downgrade_status(result)
        assert result.status == PipelineStatus.PARTIAL  # not FALLBACK — ratchet starts fresh


# ══════════════════════════════════════════════════════════════════════════════
# 10. Utility / helper unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_text_to_fallback_events_returns_one_event(self):
        events = _text_to_fallback_events("I saw something at the entrance.")
        assert len(events) == 1
        assert events[0].confidence == pytest.approx(0.3)

    def test_text_to_fallback_events_truncates_long_text(self):
        long_text = "x" * 1000
        events = _text_to_fallback_events(long_text)
        assert len(events[0].source_text) <= 300

    def test_fallback_timeline_preserves_event_order(self):
        events = [
            {"id": "a", "description": "First event"},
            {"id": "b", "description": "Second event"},
            {"id": "c", "description": "Third event"},
        ]
        tl = _fallback_timeline(events)
        ids = [e.event_id for e in tl.uncertain_events]
        assert ids == ["a", "b", "c"]

    def test_event_to_dict_shape(self):
        ev = _make_event("Witness entered the building")
        d = _event_to_dict(ev)
        required = {"id", "description", "time", "time_uncertainty",
                    "location", "actors", "confidence", "source_text"}
        assert required.issubset(d.keys())
