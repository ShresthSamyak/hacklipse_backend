"""
Response parser: extract structured data from LLM text output.
All LLM outputs are JSON strings embedded in prose; this strips the wrapper.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.exceptions import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Matches ```json ... ``` or ``` ... ``` blocks
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """
    Extract and parse the first JSON block from an LLM response.

    Strategies (in order):
      1. Direct parse (the whole string is valid JSON).
      2. Extract from markdown code fence.
      3. Find the first '[' or '{' and attempt to parse from there.

    Raises ValidationError if no valid JSON can be found.
    """
    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Markdown fence
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. First bracket search
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # scan backwards from end for matching closer
        end = text.rfind(end_char)
        if end == -1 or end <= start:
            continue
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            continue

    logger.warning("Failed to extract JSON from LLM response", text_preview=text[:200])
    raise ValidationError(
        "LLM response did not contain parseable JSON",
        detail={"preview": text[:500]},
    )


def extract_text(text: str) -> str:
    """Strip markdown code fences and return plain text."""
    cleaned = _JSON_BLOCK_RE.sub("", text)
    return cleaned.strip()
