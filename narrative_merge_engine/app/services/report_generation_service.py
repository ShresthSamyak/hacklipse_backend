import json
from typing import Any

from app.core.ai.base_provider import LLMRequest, LLMMessage
from app.core.ai.orchestrator import get_orchestrator
from app.core.ai.prompt_registry import prompt_registry
from app.core.ai.response_parser import extract_json
from app.core.logging import get_logger
from app.models.schemas.report import ReportGenerationResult

logger = get_logger(__name__)


async def generate_final_report(
    transcript: str,
    testimony_analysis: dict,
    events: list[dict],
    timeline: dict,
    conflicts: dict
) -> ReportGenerationResult:
    """
    Synthesize all pipeline artifacts into a final cohesive investigation report.
    Uses the PRIMARY LLM because it requires sophisticated reasoning and synthesis over the entire story matrix.
    """
    orchestrator = get_orchestrator()

    prompt = prompt_registry.render(
        "report_generation",
        transcript=transcript,
        testimony_analysis=json.dumps(testimony_analysis, indent=2),
        events=json.dumps(events, indent=2),
        timeline=json.dumps(timeline, indent=2),
        conflicts=json.dumps(conflicts, indent=2)
    )

    request = LLMRequest(
        messages=[LLMMessage(role="user", content=prompt)],
        temperature=0.3,
        max_tokens=2500,
    )

    logger.debug("Executing final report generation")

    try:
        response = await orchestrator.complete(
            request,
            task_name="report_generation",
        )

        raw_content = response.content or "{}"
        parsed_json = extract_json(raw_content)
        result = ReportGenerationResult.model_validate(parsed_json)

        logger.info(
            "Report generation successful",
            event_count=len(result.key_events),
            conflict_count=len(result.conflicts)
        )
        return result

    except Exception as exc:
        logger.error(
            "Report generation failed, falling back to minimal report",
            error=str(exc)
        )
        return ReportGenerationResult.fallback()
