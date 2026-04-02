"""
Prompt Registry — centralised store for all LLM prompt templates.

Prompts are versioned strings kept here (or loaded from dedicated prompt files).
Services reference prompts by key, never inline them.

Template variables use Python's `string.Template` syntax: $variable_name
"""

from __future__ import annotations

from string import Template
from typing import Any

# Import dedicated prompt modules
from app.core.ai.prompts.event_extraction_v2 import (
    EVENT_EXTRACTION_SYSTEM_PROMPT,
    EVENT_EXTRACTION_USER_PROMPT,
)
from app.core.ai.prompts.timeline_reconstruction_v2 import (
    TIMELINE_RECONSTRUCTION_SYSTEM_PROMPT,
    TIMELINE_RECONSTRUCTION_USER_PROMPT,
)


class PromptRegistry:
    """
    Manages versioned prompt templates.

    Usage:
        prompt = registry.render("event_extraction_v2", testimony_text="...")
        system = registry.get_system_prompt("event_extraction_v2")
    """

    _templates: dict[str, str] = {
        # ── Testimony ingestion ───────────────────────────────────────────
        "testimony_summary_v1": (
            "You are an expert analyst. Summarise the following witness testimony "
            "into a concise paragraph, preserving all factual claims.\n\n"
            "TESTIMONY:\n$testimony_text\n\nSUMMARY:"
        ),

        # ── Event extraction (LEGACY — use v2 for production) ────────────
        "event_extraction_v1": (
            "Extract discrete events from the testimony below. "
            "Return a JSON array of objects with keys: "
            "id, description, timestamp_hint, participants, location, confidence.\n\n"
            "TESTIMONY:\n$testimony_text\n\nEVENTS JSON:"
        ),

        # ── Event extraction v2 (production prompt) ──────────────────────
        "event_extraction_v2": EVENT_EXTRACTION_USER_PROMPT,

        # ── Timeline reconstruction (LEGACY — use v2 for production) ────
        "timeline_alignment_v1": (
            "You are given a set of events from multiple testimonies. "
            "Order them chronologically, resolve ambiguous timestamps using context, "
            "and return a unified JSON timeline.\n\n"
            "EVENTS:\n$events_json\n\nTIMELINE JSON:"
        ),

        # ── Timeline reconstruction v2 (production prompt) ───────────────
        "timeline_reconstruction_v2": TIMELINE_RECONSTRUCTION_USER_PROMPT,

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

    # System prompts live separately — not all tasks need one
    _system_prompts: dict[str, str] = {
        "event_extraction_v2": EVENT_EXTRACTION_SYSTEM_PROMPT,
        "timeline_reconstruction_v2": TIMELINE_RECONSTRUCTION_SYSTEM_PROMPT,
    }

    def get(self, key: str) -> str:
        if key not in self._templates:
            raise KeyError(f"Prompt template '{key}' not found in registry.")
        return self._templates[key]

    def get_system_prompt(self, key: str) -> str | None:
        """Return the system prompt for a given task key, or None."""
        return self._system_prompts.get(key)

    def render(self, key: str, **variables: Any) -> str:
        """Render a prompt template with the given variables."""
        template = Template(self.get(key))
        return template.safe_substitute(**variables)

    def register(self, key: str, template: str, *, overwrite: bool = False) -> None:
        """Dynamically register or update a prompt template at runtime."""
        if key in self._templates and not overwrite:
            raise ValueError(f"Prompt '{key}' already exists. Pass overwrite=True to replace.")
        self._templates[key] = template

    def register_system_prompt(self, key: str, prompt: str, *, overwrite: bool = False) -> None:
        """Register a system prompt for a task key."""
        if key in self._system_prompts and not overwrite:
            raise ValueError(f"System prompt '{key}' already exists.")
        self._system_prompts[key] = prompt

    def list_keys(self) -> list[str]:
        return list(self._templates.keys())


# Module-level singleton
prompt_registry = PromptRegistry()
