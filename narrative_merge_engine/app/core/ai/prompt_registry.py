"""
Prompt Registry — centralised store for all LLM prompt templates.

Prompts are versioned strings kept here (or loaded from disk/DB).
Services reference prompts by key, never inline them.
"""

from __future__ import annotations

from string import Template
from typing import Any


class PromptRegistry:
    """
    Manages versioned prompt templates.

    Usage:
        prompt = registry.render("event_extraction_v1", testimony_text="...")
    """

    _templates: dict[str, str] = {
        # ── Testimony ingestion ───────────────────────────────────────────
        "testimony_summary_v1": (
            "You are an expert analyst. Summarise the following witness testimony "
            "into a concise paragraph, preserving all factual claims.\n\n"
            "TESTIMONY:\n$testimony_text\n\nSUMMARY:"
        ),

        # ── Event extraction ─────────────────────────────────────────────
        "event_extraction_v1": (
            "Extract discrete events from the testimony below. "
            "Return a JSON array of objects with keys: "
            "id, description, timestamp_hint, participants, location, confidence.\n\n"
            "TESTIMONY:\n$testimony_text\n\nEVENTS JSON:"
        ),

        # ── Timeline reconstruction ──────────────────────────────────────
        "timeline_alignment_v1": (
            "You are given a set of events from multiple testimonies. "
            "Order them chronologically, resolve ambiguous timestamps using context, "
            "and return a unified JSON timeline.\n\n"
            "EVENTS:\n$events_json\n\nTIMELINE JSON:"
        ),

        # ── Conflict detection ───────────────────────────────────────────
        "conflict_detection_v1": (
            "Identify contradictions between the following events from different testimonies. "
            "Return a JSON array of conflicts, each with keys: "
            "event_a_id, event_b_id, conflict_type, description, severity (low|medium|high).\n\n"
            "EVENTS:\n$events_json\n\nCONFLICTS JSON:"
        ),

        # ── Question generation ──────────────────────────────────────────
        "question_generation_v1": (
            "Based on the conflicts and gaps in the timeline below, "
            "generate clarifying questions that an investigator should ask. "
            "Return a JSON array of questions with keys: "
            "id, question, target_event_ids, priority (low|medium|high).\n\n"
            "TIMELINE:\n$timeline_json\nCONFLICTS:\n$conflicts_json\n\nQUESTIONS JSON:"
        ),

        # ── Merge / synthesis ────────────────────────────────────────────
        "narrative_merge_v1": (
            "Synthesise the following testimonies into a single coherent narrative. "
            "Flag unresolved conflicts with [CONFLICT] markers. "
            "Be factual and neutral.\n\n"
            "TESTIMONIES:\n$testimonies_json\n\nMERGED NARRATIVE:"
        ),
    }

    def get(self, key: str) -> str:
        if key not in self._templates:
            raise KeyError(f"Prompt template '{key}' not found in registry.")
        return self._templates[key]

    def render(self, key: str, **variables: Any) -> str:
        """Render a prompt template with the given variables."""
        template = Template(self.get(key))
        return template.safe_substitute(**variables)

    def register(self, key: str, template: str, *, overwrite: bool = False) -> None:
        """Dynamically register or update a prompt template at runtime."""
        if key in self._templates and not overwrite:
            raise ValueError(f"Prompt '{key}' already exists. Pass overwrite=True to replace.")
        self._templates[key] = template

    def list_keys(self) -> list[str]:
        return list(self._templates.keys())


# Module-level singleton
prompt_registry = PromptRegistry()
