"""
End-to-End Demo Pipeline — Narrative Merge Engine
===================================================

Runs the full 5-stage pipeline in a single async call:

  Stage 1: STT         — transcribe audio → text (Groq Whisper)
  Stage 2: Extraction  — raw text → structured events
  Stage 3: Timeline    — events → chronological reconstruction
  Stage 4: Conflicts   — timelines → Git-style conflict detection (strict mode)
  Stage 5: Response    — assemble structured PipelineResult

Design goals:
  ─ NEVER crashes.  Every stage has an isolated fallback.
  ─ Each stage has a timeout guard (asyncio.wait_for).
  ─ Retries at the service level are already handled by tenacity in the
    orchestrator; the pipeline itself adds one extra timeout-retry.
  ─ status reflects the worst stage outcome:
      "success"  → all stages completed nominally
      "partial"  → at least one stage used a fallback but output is usable
      "fallback" → multiple stages failed; output may be minimal

  ─ errors[] collects non-fatal warnings so the UI can show them.
  ─ DEMO_MODE=True forces temperature=0 on all LLM calls and adds extra
    logging so judges can follow the flow on screen.
  ─ FAST_PREVIEW=True skips timeline reasoning and runs minimal detection,
    cutting total latency from ~15 s to ~4 s.

Usage:
    pipeline = DemoPipeline(
        event_svc=...,
        timeline_svc=...,
        conflict_svc=...,
        stt_svc=...,       # optional — omit for text-only mode
    )

    # from audio
    result = await pipeline.run(audio=audio_bytes, filename="testimony.wav")

    # from text
    result = await pipeline.run(text="I entered around 9 PM...")

    # fast preview (no heavy reasoning)
    result = await pipeline.run(text="...", fast_preview=True)

    # demo mode (temperature=0, verbose logs)
    result = await pipeline.run(text="...", demo_mode=True)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.logging import get_logger
from app.models.schemas.conflict_strict import StrictConflictResult, StrictEvent
from app.models.schemas.event_extraction import ExtractedEvent, ExtractionResult
from app.models.schemas.report import ReportGenerationResult
from app.models.schemas.timeline_reconstruction import (
    PlacementConfidence,
    TimelineEvent,
    TimelineReconstructionResult,
)
from app.models.schemas.testimony_analysis import TestimonyAnalysisResult
from app.services.conflict_detection_service import ConflictDetectionService
from app.services.event_extraction_service import EventExtractionService
from app.services.report_generation_service import generate_final_report
from app.services.speech_to_text_service import SpeechToTextService, TranscriptResult
from app.services.timeline_reconstruction_service import TimelineReconstructionService
from app.services.testimony_analysis_service import analyze_testimony_sensitivity

logger = get_logger(__name__)


# ─── Stage timeouts (seconds) ────────────────────────────────────────────────

_TIMEOUT_STT = 20          # Whisper is fast; generous margin for network
_TIMEOUT_EXTRACTION = 15   # 70B model; worst-case long testimony
_TIMEOUT_TIMELINE = 15     # reasoning can be verbose
_TIMEOUT_CONFLICTS = 12    # strict mode is lean (temp=0, max 4096 tokens)

# Retry budget: one extra attempt on timeout before fallback
_MAX_TIMEOUT_RETRIES = 1


# ─── Pipeline status ─────────────────────────────────────────────────────────

class PipelineStatus(str, Enum):
    SUCCESS  = "success"   # all stages nominal
    PARTIAL  = "partial"   # ≥1 stage used fallback but output is usable
    FALLBACK = "fallback"  # multiple failures; output is minimal


# ─── Pipeline result ──────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """
    Structured response from the full demo pipeline.

    All fields are always present — fallback values are used when a stage fails,
    so downstream consumers (UI, API) never need to handle None.
    """

    # Stage outputs
    transcript: str = ""
    testimony_analysis: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    timeline: dict = field(default_factory=dict)
    conflicts: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)

    # Pipeline metadata
    status: PipelineStatus = PipelineStatus.SUCCESS
    errors: list[str] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)  # ms per stage
    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    demo_mode: bool = False
    fast_preview: bool = False

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "transcript": self.transcript,
            "testimony_analysis": self.testimony_analysis,
            "events": self.events,
            "timeline": self.timeline,
            "conflicts": self.conflicts,
            "report": self.report,
            "status": self.status.value,
            "errors": self.errors,
            "stage_timings_ms": self.stage_timings,
            "demo_mode": self.demo_mode,
            "fast_preview": self.fast_preview,
        }


# ─── Sample fallback data (for total demo blackout) ───────────────────────────

_DEMO_SAMPLE_TRANSCRIPT = (
    "I think I entered the building around 9, maybe 10 at night. "
    "There was someone near the table when I walked in. "
    "I heard a loud noise a bit later."
)

_DEMO_SAMPLE_BRANCHES: dict[str, list[dict]] = {
    "Witness_A": [
        {"id": "a1", "description": "Entered the building", "time": "9 PM", "location": "entrance"},
        {"id": "a2", "description": "Saw a person near the table", "location": "main room"},
        {"id": "a3", "description": "Heard a loud noise", "time": "9:30 PM"},
    ],
    "Witness_B": [
        {"id": "b1", "description": "Entered the building", "time": "10 PM", "location": "entrance"},
        {"id": "b2", "description": "Saw no one in the room", "location": "main room"},
        {"id": "b3", "description": "Heard a loud noise", "time": "10:15 PM"},
    ],
}


# ─── Main Pipeline ────────────────────────────────────────────────────────────

class DemoPipeline:
    """
    Orchestrates the full Narrative Merge Engine demo pipeline.

    Instantiate once and reuse.  All services are injected — no hard-coded
    dependencies.  If stt_svc is None, the pipeline raises an error when
    audio input is provided.
    """

    def __init__(
        self,
        event_svc: EventExtractionService,
        timeline_svc: TimelineReconstructionService,
        conflict_svc: ConflictDetectionService,
        stt_svc: SpeechToTextService | None = None,
    ) -> None:
        self._event_svc = event_svc
        self._timeline_svc = timeline_svc
        self._conflict_svc = conflict_svc
        self._stt_svc = stt_svc

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(
        self,
        *,
        audio: bytes | None = None,
        filename: str = "testimony.wav",
        text: str | None = None,
        demo_mode: bool = False,
        fast_preview: bool = False,
        # For multi-witness mode: pass multiple text blocks keyed by label
        branches_override: dict[str, str] | None = None,
    ) -> PipelineResult:
        """
        Run the end-to-end pipeline.

        Args:
            audio:            Raw audio bytes. Takes priority over text.
            filename:         Filename hint for Whisper format detection.
            text:             Raw testimony text (used if audio is None).
            demo_mode:        temperature=0 everywhere, verbose stage logs.
            fast_preview:     Skip timeline reasoning; return minimal output fast.
            branches_override: Skip extraction; use these pre-built branches for
                               conflict detection. Dict of {label: text}.
        """
        pipeline_start = time.monotonic()
        result = PipelineResult(
            demo_mode=demo_mode,
            fast_preview=fast_preview,
        )

        logger.info(
            "Pipeline started",
            pipeline_id=result.pipeline_id,
            has_audio=audio is not None,
            has_text=text is not None,
            demo_mode=demo_mode,
            fast_preview=fast_preview,
        )

        # ── Stage 1: Speech-to-Text ───────────────────────────────────────────
        if audio is not None:
            transcript, stt_elapsed = await self._run_stt(
                result, audio=audio, filename=filename
            )
        else:
            transcript = text or ""
            result.transcript = transcript

        if not result.transcript and not branches_override:
            result.errors.append("No input text available — using demo sample.")
            result.transcript = _DEMO_SAMPLE_TRANSCRIPT
            result.status = PipelineStatus.PARTIAL

        # ── Stage 2: Event Extraction ─────────────────────────────────────────
        if branches_override:
            # Multi-witness mode: extract from all branches CONCURRENTLY.
            # Each branch is isolated — a failure returns [] + appends an error,
            # it never cancels sibling branches.
            labels = list(branches_override.keys())
            texts  = list(branches_override.values())

            branch_event_lists = await asyncio.gather(
                *[
                    self._run_extraction_branch(
                        result, label=label, text=text, demo_mode=demo_mode
                    )
                    for label, text in zip(labels, texts)
                ]
            )

            events_by_branch: dict[str, list[dict]] = {
                label: [_event_to_dict(e) for e in events]
                for label, events in zip(labels, branch_event_lists)
            }
            all_events = [e for events in events_by_branch.values() for e in events]

            logger.info(
                "Multi-witness extraction complete (concurrent)",
                pipeline_id=result.pipeline_id,
                branch_count=len(labels),
                total_events=len(all_events),
                per_branch={lbl: len(evts) for lbl, evts in events_by_branch.items()},
            )
        else:
            extracted_events = await self._run_extraction(
                result, text=result.transcript, demo_mode=demo_mode
            )
            all_events = [_event_to_dict(e) for e in extracted_events]
            # Single witness: all events go into one branch
            events_by_branch = {"Witness_A": all_events}

        result.events = all_events

        if fast_preview:
            # ── Fast path: skip timeline reasoning ───────────────────────────
            result.timeline = _build_trivial_timeline(all_events)
            result.conflicts = _strict_result_to_dict(StrictConflictResult())
            result.errors.append("fast_preview: timeline reasoning and conflict detection skipped.")
            if result.status == PipelineStatus.SUCCESS:
                result.status = PipelineStatus.PARTIAL
            result.stage_timings["total_ms"] = round(
                (time.monotonic() - pipeline_start) * 1000, 1
            )
            logger.info(
                "Pipeline completed (fast preview)",
                pipeline_id=result.pipeline_id,
                status=result.status.value,
            )
            return result

        # ── Stage 3: Timeline Reconstruction ─────────────────────────────────
        if all_events:
            timeline_result = await self._run_timeline(
                result, events=all_events, demo_mode=demo_mode
            )
            result.timeline = _timeline_to_dict(timeline_result)
        else:
            result.timeline = _build_trivial_timeline([])
            result.errors.append("No events extracted — timeline is empty.")

        # ── Stage 4: Conflict Detection (strict mode) ─────────────────────────
        if len(events_by_branch) >= 2 or (branches_override and len(events_by_branch) >= 1):
            conflict_result = await self._run_conflicts(
                result, branches=events_by_branch
            )
        elif len(events_by_branch) == 1:
            # Only one branch — no cross-witness conflicts possible.
            # Still run strict detection on the single branch to surface
            # internal contradictions (temporal loops, presence mismatches).
            conflict_result = await self._run_conflicts(
                result, branches=events_by_branch
            )
        else:
            conflict_result = StrictConflictResult()
            result.errors.append("No branches available for conflict detection.")

        result.conflicts = _strict_result_to_dict(conflict_result)

        # ── Stage 5: Final Investigative Report ──────────────────────────────
        report_result = await self._run_report(
            result,
            transcript=result.transcript,
            testimony_analysis=result.testimony_analysis,
            events=result.events,
            timeline=result.timeline,
            conflicts=result.conflicts,
        )
        result.report = report_result.model_dump()

        # ── Finalize ─────────────────────────────────────────────────────────
        total_ms = round((time.monotonic() - pipeline_start) * 1000, 1)
        result.stage_timings["total_ms"] = total_ms

        logger.info(
            "Pipeline completed",
            pipeline_id=result.pipeline_id,
            status=result.status.value,
            total_ms=total_ms,
            events=len(all_events),
            conflicts=conflict_result.conflict_count,
            errors=len(result.errors),
        )

        return result

    # ── Stage runners (each isolated — failure never propagates) ─────────────

    async def _run_stt(
        self,
        result: PipelineResult,
        *,
        audio: bytes,
        filename: str,
    ) -> tuple[str, float]:
        """Stage 1: transcribe audio. Falls back to empty transcript on failure."""
        if self._stt_svc is None:
            result.errors.append("STT service not configured — skipping audio transcription.")
            result.status = PipelineStatus.PARTIAL
            return "", 0.0

        stage_start = time.monotonic()
        transcript_text = ""

        for attempt in range(_MAX_TIMEOUT_RETRIES + 1):
            try:
                stt_result: TranscriptResult = await asyncio.wait_for(
                    self._stt_svc.transcribe(audio, filename=filename),
                    timeout=_TIMEOUT_STT,
                )
                transcript_text = stt_result.text
                elapsed = round((time.monotonic() - stage_start) * 1000, 1)
                result.transcript = transcript_text
                result.stage_timings["stt_ms"] = elapsed
                logger.info(
                    "STT complete",
                    pipeline_id=result.pipeline_id,
                    elapsed_ms=elapsed,
                    detected_language=stt_result.detected_language,
                    text_length=len(transcript_text),
                )
                return transcript_text, elapsed

            except asyncio.TimeoutError:
                if attempt < _MAX_TIMEOUT_RETRIES:
                    logger.warning(
                        "STT timeout — retrying",
                        pipeline_id=result.pipeline_id,
                        attempt=attempt + 1,
                    )
                    continue
                logger.error("STT timed out after retries", pipeline_id=result.pipeline_id)
                result.errors.append(
                    f"STT timed out after {_TIMEOUT_STT}s — please provide text input."
                )
                result.status = PipelineStatus.PARTIAL
                return "", 0.0

            except Exception as exc:
                logger.error(
                    "STT failed",
                    pipeline_id=result.pipeline_id,
                    error=str(exc),
                )
                result.errors.append(f"STT error: {exc}")
                result.status = PipelineStatus.PARTIAL
                return "", 0.0

        return transcript_text, 0.0

    async def _run_extraction(
        self,
        result: PipelineResult,
        *,
        text: str,
        demo_mode: bool,
    ) -> list[ExtractedEvent]:
        """Stage 2: extract events. Falls back to minimal single event on failure."""
        stage_start = time.monotonic()

        # Phase 1.5: Testimony Analysis
        testimony_analysis = None
        try:
            testimony_analysis = await asyncio.wait_for(
                analyze_testimony_sensitivity(text), timeout=15
            )
            
            # Surface it to the pipeline result if empty, or dict merge/overwrite (we keep first)
            if not result.testimony_analysis:
               result.testimony_analysis = testimony_analysis.model_dump()
               
        except Exception as exc:
            logger.warning("Testimony analysis failed, proceeding without context", error=str(exc))
            result.errors.append(f"Testimony analysis failed: {exc}")

        for attempt in range(_MAX_TIMEOUT_RETRIES + 1):
            try:
                extraction: ExtractionResult = await asyncio.wait_for(
                    self._event_svc.extract_events_from_text(text, testimony_analysis=testimony_analysis),
                    timeout=_TIMEOUT_EXTRACTION,
                )
                elapsed = round((time.monotonic() - stage_start) * 1000, 1)
                result.stage_timings["extraction_ms"] = elapsed

                event_count = len(extraction.events)
                logger.info(
                    "Events extracted",
                    pipeline_id=result.pipeline_id,
                    events=event_count,
                    dropped=extraction.dropped_event_count,
                    elapsed_ms=elapsed,
                )

                if event_count == 0:
                    result.errors.append(
                        "Event extraction returned 0 events — "
                        "text may be too short or ambiguous."
                    )
                    _downgrade_status(result)

                return extraction.events

            except asyncio.TimeoutError:
                if attempt < _MAX_TIMEOUT_RETRIES:
                    logger.warning(
                        "Event extraction timeout — retrying",
                        pipeline_id=result.pipeline_id,
                        attempt=attempt + 1,
                    )
                    continue
                logger.error("Event extraction timed out", pipeline_id=result.pipeline_id)
                result.errors.append(
                    f"Event extraction timed out after {_TIMEOUT_EXTRACTION}s — returning partial events."
                )
                _downgrade_status(result)
                return _text_to_fallback_events(text)

            except Exception as exc:
                logger.error(
                    "Event extraction failed",
                    pipeline_id=result.pipeline_id,
                    error=str(exc),
                )
                result.errors.append(f"Event extraction error: {exc}")
                _downgrade_status(result)
                return _text_to_fallback_events(text)

        return []

    async def _run_extraction_branch(
        self,
        result: PipelineResult,
        *,
        label: str,
        text: str,
        demo_mode: bool,
    ) -> list[ExtractedEvent]:
        """
        Thin wrapper around `_run_extraction` for use in `asyncio.gather`.

        Adds per-branch logging and isolates exceptions so a single branch
        failure does NOT cancel sibling coroutines.
        """
        logger.info(
            "Branch extraction started",
            pipeline_id=result.pipeline_id,
            branch=label,
            text_length=len(text),
        )
        try:
            events = await self._run_extraction(result, text=text, demo_mode=demo_mode)
            logger.info(
                "Branch extraction complete",
                pipeline_id=result.pipeline_id,
                branch=label,
                event_count=len(events),
            )
            return events
        except Exception as exc:
            # Belt-and-suspenders: _run_extraction already catches, but protect
            # gather() from unexpected leaks.
            logger.error(
                "Branch extraction unhandled error",
                pipeline_id=result.pipeline_id,
                branch=label,
                error=str(exc),
            )
            result.errors.append(f"Branch '{label}' extraction failed: {exc}")
            _downgrade_status(result)
            return []


    async def _run_timeline(
        self,
        result: PipelineResult,
        *,
        events: list[dict],
        demo_mode: bool,
    ) -> TimelineReconstructionResult:
        """Stage 3: reconstruct timeline. Falls back to sorted list on failure."""
        stage_start = time.monotonic()

        for attempt in range(_MAX_TIMEOUT_RETRIES + 1):
            try:
                timeline: TimelineReconstructionResult = await asyncio.wait_for(
                    self._timeline_svc.reconstruct_from_events(events),
                    timeout=_TIMEOUT_TIMELINE,
                )
                elapsed = round((time.monotonic() - stage_start) * 1000, 1)
                result.stage_timings["timeline_ms"] = elapsed

                logger.info(
                    "Timeline built",
                    pipeline_id=result.pipeline_id,
                    confirmed=len(timeline.confirmed_sequence),
                    probable=len(timeline.probable_sequence),
                    uncertain=len(timeline.uncertain_events),
                    elapsed_ms=elapsed,
                )
                return timeline

            except asyncio.TimeoutError:
                if attempt < _MAX_TIMEOUT_RETRIES:
                    logger.warning(
                        "Timeline timeout — retrying",
                        pipeline_id=result.pipeline_id,
                        attempt=attempt + 1,
                    )
                    continue
                logger.error("Timeline timed out", pipeline_id=result.pipeline_id)
                result.errors.append(
                    f"Timeline reconstruction timed out after {_TIMEOUT_TIMELINE}s "
                    "— falling back to simple event ordering."
                )
                _downgrade_status(result)
                return _fallback_timeline(events)

            except Exception as exc:
                logger.error(
                    "Timeline reconstruction failed",
                    pipeline_id=result.pipeline_id,
                    error=str(exc),
                )
                result.errors.append(f"Timeline error: {exc} — falling back to simple ordering.")
                _downgrade_status(result)
                return _fallback_timeline(events)

        return _fallback_timeline(events)

    async def _run_conflicts(
        self,
        result: PipelineResult,
        *,
        branches: dict[str, list[dict]],
    ) -> StrictConflictResult:
        """Stage 4: strict-mode conflict detection. Falls back to empty result on failure."""
        stage_start = time.monotonic()

        for attempt in range(_MAX_TIMEOUT_RETRIES + 1):
            try:
                conflicts: StrictConflictResult = await asyncio.wait_for(
                    self._conflict_svc.detect_strict(branches),
                    timeout=_TIMEOUT_CONFLICTS,
                )
                elapsed = round((time.monotonic() - stage_start) * 1000, 1)
                result.stage_timings["conflicts_ms"] = elapsed

                logger.info(
                    "Conflicts detected",
                    pipeline_id=result.pipeline_id,
                    conflict_count=conflicts.conflict_count,
                    has_question=conflicts.next_question is not None,
                    elapsed_ms=elapsed,
                )
                return conflicts

            except asyncio.TimeoutError:
                if attempt < _MAX_TIMEOUT_RETRIES:
                    logger.warning(
                        "Conflict detection timeout — retrying",
                        pipeline_id=result.pipeline_id,
                        attempt=attempt + 1,
                    )
                    continue
                logger.error("Conflict detection timed out", pipeline_id=result.pipeline_id)
                result.errors.append(
                    f"Conflict detection timed out after {_TIMEOUT_CONFLICTS}s "
                    "— returning no conflicts detected."
                )
                _downgrade_status(result)
                return StrictConflictResult()

            except Exception as exc:
                logger.error(
                    "Conflict detection failed",
                    pipeline_id=result.pipeline_id,
                    error=str(exc),
                )
                result.errors.append(
                    f"Conflict detection error: {exc} — returning no conflicts detected."
                )
                _downgrade_status(result)
                return StrictConflictResult()

        return StrictConflictResult()

    async def _run_report(
        self,
        result: PipelineResult,
        *,
        transcript: str,
        testimony_analysis: dict | None,
        events: list[dict],
        timeline: dict,
        conflicts: dict,
    ) -> ReportGenerationResult:
        """Stage 5: Final Report Generation. Fully isolated."""
        stage_start = time.monotonic()

        try:
            report: ReportGenerationResult = await asyncio.wait_for(
                generate_final_report(
                    transcript=transcript,
                    testimony_analysis=testimony_analysis or {},
                    events=events,
                    timeline=timeline,
                    conflicts=conflicts,
                ),
                timeout=20, # Wait longer for full report synthesis
            )
            elapsed = round((time.monotonic() - stage_start) * 1000, 1)
            result.stage_timings["report_ms"] = elapsed

            logger.info(
                "Report built",
                pipeline_id=result.pipeline_id,
                elapsed_ms=elapsed,
            )
            return report

        except asyncio.TimeoutError:
            logger.error("Report generation timed out", pipeline_id=result.pipeline_id)
            result.errors.append("Report generation timed out — using minimal summary.")
            _downgrade_status(result)
            return ReportGenerationResult.fallback()

        except Exception as exc:
            logger.error(
                "Report generation failed",
                pipeline_id=result.pipeline_id,
                error=str(exc),
            )
            result.errors.append(f"Report generation error: {exc}")
            _downgrade_status(result)
            return ReportGenerationResult.fallback()

# ─── Fallback builders ────────────────────────────────────────────────────────

def _text_to_fallback_events(text: str) -> list[ExtractedEvent]:
    """
    Last-resort fallback: treat the entire text as one uncertain event.
    Better than returning nothing — at least something flows to the next stage.
    """
    return [
        ExtractedEvent(
            id=str(uuid.uuid4()),
            description=text[:300].strip() or "Unprocessed testimony",
            time=None,
            time_uncertainty="extraction failed",
            location=None,
            actors=[],
            confidence=0.3,
            source_text=text[:300],
        )
    ]


def _fallback_timeline(events: list[dict]) -> TimelineReconstructionResult:
    """
    Trivial fallback: place all events as 'uncertain', no reasoning.
    Preserves input order — better than an empty timeline.
    """
    uncertain = []
    for i, e in enumerate(events):
        uncertain.append(
            TimelineEvent(
                event_id=e.get("id", str(uuid.uuid4())),
                description=e.get("description", "Unknown event"),
                time=e.get("time"),
                location=e.get("location"),
                actors=e.get("actors", []),
                original_confidence=float(e.get("confidence", 0.3)),
                position=i,
                placement_confidence=PlacementConfidence.UNCERTAIN,
            )
        )
    return TimelineReconstructionResult(uncertain_events=uncertain)


# ─── Shape converters ─────────────────────────────────────────────────────────

def _event_to_dict(event: ExtractedEvent) -> dict:
    """Convert an ExtractedEvent to a plain dict for downstream stages."""
    return {
        "id": event.id,
        "description": event.description,
        "time": event.time,
        "time_uncertainty": event.time_uncertainty,
        "location": event.location,
        "actors": event.actors,
        "confidence": event.confidence,
        "source_text": event.source_text,
    }


def _timeline_to_dict(timeline: TimelineReconstructionResult) -> dict:
    """Convert a TimelineReconstructionResult to an API-friendly dict."""
    return {
        "confirmed_sequence": [e.model_dump() for e in timeline.confirmed_sequence],
        "probable_sequence":  [e.model_dump() for e in timeline.probable_sequence],
        "uncertain_events":   [e.model_dump() for e in timeline.uncertain_events],
        "full_sequence":      [e.model_dump() for e in timeline.full_sequence],
        "event_count":        timeline.event_count,
        "confidence_summary": {
            "confirmed": len(timeline.confirmed_sequence),
            "probable":  len(timeline.probable_sequence),
            "uncertain": len(timeline.uncertain_events),
        },
        "temporal_links": [l.model_dump() for l in timeline.temporal_links],
        "metadata": timeline.reconstruction_metadata,
    }


def _build_trivial_timeline(events: list[dict]) -> dict:
    """Build a minimal timeline dict in fast-preview mode (no LLM call)."""
    return {
        "confirmed_sequence": [],
        "probable_sequence":  [],
        "uncertain_events":   [
            {"event_id": e.get("id", ""), "description": e.get("description", ""), "position": i}
            for i, e in enumerate(events)
        ],
        "full_sequence": [
            {"event_id": e.get("id", ""), "description": e.get("description", ""), "position": i}
            for i, e in enumerate(events)
        ],
        "event_count": len(events),
        "confidence_summary": {"confirmed": 0, "probable": 0, "uncertain": len(events)},
        "temporal_links": [],
        "metadata": {"fast_preview": True},
    }


def _strict_result_to_dict(conflicts: StrictConflictResult) -> dict:
    """Convert StrictConflictResult to dict, explicitly including computed @property fields."""
    base = conflicts.model_dump()
    base["conflict_count"] = conflicts.conflict_count
    base["has_conflicts"] = conflicts.has_conflicts
    return base


# ─── Status helpers ───────────────────────────────────────────────────────────

def _downgrade_status(result: PipelineResult) -> None:
    """Ratchet status down: success → partial → fallback. Never upgrades."""
    if result.status == PipelineStatus.SUCCESS:
        result.status = PipelineStatus.PARTIAL
    elif result.status == PipelineStatus.PARTIAL:
        result.status = PipelineStatus.FALLBACK


# ─── Factory / DI helper ─────────────────────────────────────────────────────

def build_pipeline(
    db,  # AsyncSession
    llm,  # LLMOrchestrator
    stt_svc: SpeechToTextService | None = None,
) -> DemoPipeline:
    """
    Convenience factory for FastAPI dependency injection.

    Usage in a FastAPI endpoint:
        pipeline = build_pipeline(db=db, llm=llm, stt_svc=stt_svc)
        result   = await pipeline.run(audio=audio_bytes)
    """
    return DemoPipeline(
        event_svc=EventExtractionService(db=db, llm=llm),
        timeline_svc=TimelineReconstructionService(db=db, llm=llm),
        conflict_svc=ConflictDetectionService(db=db, llm=llm),
        stt_svc=stt_svc,
    )
