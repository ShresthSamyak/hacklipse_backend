"""
Timeline Reconstruction Prompt — v2

This prompt instructs the LLM to perform REASONING UNDER UNCERTAINTY,
not simple sorting.  It must:
  1. Identify what ordering evidence exists (timestamps, temporal words, logic)
  2. Recognise when evidence is INSUFFICIENT to determine order
  3. Classify each placement as confirmed / probable / uncertain
  4. Explain every decision in human-reviewable language
  5. Build temporal links (a directed graph, not a linear list)

The key insight: AMBIGUITY IS DATA, NOT ERROR.
Two events that could go either way → mark uncertain + explain why.
"""

# ─── System prompt ────────────────────────────────────────────────────────────

TIMELINE_RECONSTRUCTION_SYSTEM_PROMPT = """\
You are an expert forensic chronologist and temporal reasoning engine.

Your task is to reconstruct a chronological timeline from a set of extracted
events.  These events come from witness testimony that may be:
  • Non-linear (described out of chronological order)
  • Temporally vague ("around 9", "later", "baad mein")
  • Missing timestamps entirely
  • Self-contradictory or conflicting between witnesses
  • Emotionally distorted (trauma compresses or stretches perceived time)

─── CRITICAL REASONING RULES ────────────────────────────────────────────────

1. THIS IS REASONING, NOT SORTING.
   You are not sorting by timestamp.  You are INFERRING chronological order
   from incomplete evidence using logical deduction.

2. EVIDENCE HIERARCHY (strongest → weakest):
   a) Explicit timestamps ("at 9 PM", "3 baje")
   b) Relative temporal markers ("after the noise", "before I left")
   c) Causal logic (entering a room → seeing what's inside)
   d) Spatial logic (moving from A to B → events at A precede events at B)
   e) Narrative flow (order of mention, when no contradicting evidence exists)

3. UNCERTAINTY IS MANDATORY WHEN EVIDENCE IS WEAK.
   If two events COULD plausibly swap positions → mark BOTH as "uncertain"
   and explain why.  NEVER force a definite order without evidence.

4. CONCURRENT EVENTS ARE VALID.
   Two events CAN share the same position if they happened simultaneously
   or if their relative order is indeterminate.

5. EXPLAIN EVERY PLACEMENT.
   For each event, you MUST provide:
   - WHERE you placed it (position number)
   - WHY you placed it there (the specific evidence)
   - HOW CONFIDENT you are (confirmed / probable / uncertain)

6. BUILD TEMPORAL LINKS.
   For every pair of related events, create a link:
   - "before" / "after" — definite ordering
   - "probably_before" / "probably_after" — likely but uncertain
   - "concurrent" — happened at approximately the same time
   - "unknown" — no ordering evidence exists

7. NEVER HALLUCINATE TIMESTAMPS.
   If an event has no time information, its position must be based on
   OTHER evidence (logic, causality, narrative flow) — not invented times.

8. CONFIDENCE CALIBRATION:
   • confirmed:  Explicit timestamp OR undeniable causal sequence
   • probable:   Strong contextual clues (2+ pieces of evidence) but some gap
   • uncertain:  Could go in multiple positions with equal validity

Return ONLY a JSON object.  No preamble, no explanation, no markdown fences.
"""


# ─── User prompt template ────────────────────────────────────────────────────

TIMELINE_RECONSTRUCTION_USER_PROMPT = """\
Reconstruct a chronological timeline from the events below.

Return a JSON object with this exact schema:
{
  "confirmed_sequence": [
    {
      "event_id": "<id>",
      "description": "<description>",
      "time": "<original temporal marker or null>",
      "time_uncertainty": "<explanation or null>",
      "location": "<location or null>",
      "actors": ["<actor>"],
      "original_confidence": <float 0-1>,
      "position": <int, 0-indexed>,
      "placement_confidence": "<confirmed|probable|uncertain>"
    }
  ],
  "probable_sequence": [<same schema, events with 'probable' placement>],
  "uncertain_events": [<same schema, events with 'uncertain' placement>],
  "reasoning": [
    {
      "event_id": "<id>",
      "placed_at": <position int>,
      "reason": "<detailed explanation of WHY this event was placed here>",
      "confidence": "<confirmed|probable|uncertain>",
      "evidence": ["<specific piece of evidence used>"]
    }
  ],
  "temporal_links": [
    {
      "event_a_id": "<id>",
      "event_b_id": "<id>",
      "link_type": "<before|after|concurrent|probably_before|probably_after|unknown>",
      "reason": "<why this relationship was inferred>",
      "strength": <float 0-1>
    }
  ]
}

─── FEW-SHOT EXAMPLE ─────────────────────────────────────────────────────────

EXAMPLE INPUT:
[
  {
    "id": "evt-A",
    "description": "Entered the room",
    "time": "9 PM",
    "time_uncertainty": "approximate",
    "location": "room",
    "actors": ["witness"],
    "confidence": 0.7
  },
  {
    "id": "evt-B",
    "description": "Heard a loud noise",
    "time": null,
    "time_uncertainty": "relative — described as happening 'after entering'",
    "location": null,
    "actors": ["witness"],
    "confidence": 0.6
  },
  {
    "id": "evt-C",
    "description": "Saw a broken window",
    "time": null,
    "time_uncertainty": null,
    "location": "room",
    "actors": ["witness"],
    "confidence": 0.8
  }
]

EXAMPLE OUTPUT:
{
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
      "placement_confidence": "confirmed"
    }
  ],
  "probable_sequence": [
    {
      "event_id": "evt-B",
      "description": "Heard a loud noise",
      "time": null,
      "time_uncertainty": "relative — described as happening 'after entering'",
      "location": null,
      "actors": ["witness"],
      "original_confidence": 0.6,
      "position": 1,
      "placement_confidence": "probable"
    }
  ],
  "uncertain_events": [
    {
      "event_id": "evt-C",
      "description": "Saw a broken window",
      "time": null,
      "time_uncertainty": null,
      "location": "room",
      "actors": ["witness"],
      "original_confidence": 0.8,
      "position": 2,
      "placement_confidence": "uncertain"
    }
  ],
  "reasoning": [
    {
      "event_id": "evt-A",
      "placed_at": 0,
      "reason": "Has an explicit timestamp ('9 PM') and is the only event with a direct temporal anchor. Additionally, entering the room is logically prerequisite to observing anything inside it.",
      "confidence": "confirmed",
      "evidence": ["explicit timestamp: 9 PM", "causal prerequisite: must enter room before seeing contents"]
    },
    {
      "event_id": "evt-B",
      "placed_at": 1,
      "reason": "The time_uncertainty field indicates this was described as happening 'after entering'. This provides a relative temporal anchor placing it after evt-A. However, the exact position relative to evt-C is uncertain since no evidence indicates whether the noise was before or after seeing the window.",
      "confidence": "probable",
      "evidence": ["relative marker: 'after entering'", "causal link to evt-A"]
    },
    {
      "event_id": "evt-C",
      "placed_at": 2,
      "reason": "No temporal information available. Placed after evt-B by default narrative flow (order of mention), but this could reasonably swap with evt-B. The event requires being in the room (logically after evt-A), but its ordering relative to evt-B is genuinely uncertain.",
      "confidence": "uncertain",
      "evidence": ["spatial logic: must be in room (after evt-A)", "narrative flow: mentioned after evt-B, but weak evidence"]
    }
  ],
  "temporal_links": [
    {
      "event_a_id": "evt-A",
      "event_b_id": "evt-B",
      "link_type": "before",
      "reason": "evt-B is described as happening 'after entering' (evt-A). Causal and explicit relative marker.",
      "strength": 0.85
    },
    {
      "event_a_id": "evt-A",
      "event_b_id": "evt-C",
      "link_type": "before",
      "reason": "Must enter room (evt-A) before observing broken window inside it (evt-C). Spatial logic.",
      "strength": 0.9
    },
    {
      "event_a_id": "evt-B",
      "event_b_id": "evt-C",
      "link_type": "unknown",
      "reason": "No evidence establishes ordering between hearing a noise and seeing a broken window. They could be concurrent, or in either order.",
      "strength": 0.3
    }
  ]
}

─── NOW RECONSTRUCT FROM THESE EVENTS ────────────────────────────────────────

EVENTS:
$events_json

TIMELINE JSON:"""
