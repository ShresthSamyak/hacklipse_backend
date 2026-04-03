"""
LLM Orchestration Layer.

Responsibilities:
  - Resolve the active LLM provider from config (never hard-coded).
  - Apply retry logic with exponential back-off (via tenacity).
  - Emit structured logs for every LLM call.
  - Route lightweight tasks to the optional FAST_LLM when configured.
  - Expose a single, uniform interface to all services.

Provider routing:
  ┌─────────────────────────────────────────────────────────┐
  │  task_name                     │  routed to             │
  ├────────────────────────────────┼────────────────────────┤
  │  event_extraction_*            │  primary LLM           │
  │  timeline_reconstruction_*     │  primary LLM           │
  │  conflict_detection_*          │  primary LLM           │
  │  question_generation_*         │  fast LLM (if avail.)  │
  │  testimony_summary_*           │  fast LLM (if avail.)  │
  │  speech_to_text                │  STT provider (Groq)   │
  │  everything else               │  primary LLM           │
  └─────────────────────────────────────────────────────────┘

To add a new provider:
  1. Create app/core/ai/providers/<name>.py implementing BaseLLMProvider.
  2. Add it to _load_provider() below.
"""

from __future__ import annotations

from typing import AsyncIterator

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.ai.base_provider import BaseLLMProvider, LLMRequest, LLMResponse
from app.core.config import settings
from app.core.exceptions import LLMProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Task routing ─────────────────────────────────────────────────────────────
# Tasks whose names START WITH any of these prefixes are candidates for the
# fast LLM when FAST_LLM_PROVIDER is configured.
_FAST_LLM_TASK_PREFIXES: tuple[str, ...] = (
    "question_generation",
    "testimony_summary",
    "narrative_merge",
)

# These task names are ALWAYS routed to the primary LLM (never downgraded).
_PRIMARY_ONLY_TASKS: frozenset[str] = frozenset({
    "event_extraction_v2",
    "timeline_reconstruction_v2",
    "conflict_detection_v2",
    "conflict_detection_strict",
})

# Tasks that MUST receive structured JSON output.
# The orchestrator will automatically inject response_format={"type":"json_object"}
# for these tasks — no service-level boilerplate needed.
# Only applies when the provider supports JSON mode (Groq/OpenAI-compatible).
_JSON_MODE_TASKS: frozenset[str] = frozenset({
    "event_extraction_v2",
    "timeline_reconstruction_v2",
    "conflict_detection_v2",
    "conflict_detection_strict",
    "question_generation_v1",
})


def _is_fast_task(task_name: str) -> bool:
    """True if this task should be routed to the fast LLM when available."""
    if task_name in _PRIMARY_ONLY_TASKS:
        return False
    return any(task_name.startswith(p) for p in _FAST_LLM_TASK_PREFIXES)


# ── Provider factory ──────────────────────────────────────────────────────────

def _load_provider(
    provider_name: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseLLMProvider:
    """
    Factory: instantiate the correct provider implementation.
    api_key / model override the settings defaults (used for fast LLM).
    """
    if provider_name == "groq":
        from app.core.ai.providers.groq_provider import GroqProvider
        return GroqProvider(api_key=api_key, model=model)
    elif provider_name == "openai":
        from app.core.ai.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif provider_name == "anthropic":
        from app.core.ai.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif provider_name == "gemini":
        from app.core.ai.providers.gemini_provider import GeminiProvider
        return GeminiProvider()
    elif provider_name == "azure_openai":
        from app.core.ai.providers.azure_openai_provider import AzureOpenAIProvider
        return AzureOpenAIProvider()
    elif provider_name == "custom":
        from app.core.ai.providers.custom_provider import CustomProvider
        return CustomProvider()
    else:
        raise ValueError(f"Unknown LLM provider: '{provider_name}'")


# ── Orchestrator ──────────────────────────────────────────────────────────────

class LLMOrchestrator:
    """
    Central orchestration layer for all LLM interactions.
    Services should depend on this class, not on concrete providers.
    """

    def __init__(self) -> None:
        # Primary provider (used for all heavy tasks)
        self._provider: BaseLLMProvider = _load_provider(settings.LLM_PROVIDER)
        logger.info(
            "LLM provider loaded",
            provider=settings.LLM_PROVIDER,
            model=settings.LLM_MODEL,
        )

        # Optional fast provider (used for lightweight tasks)
        self._fast_provider: BaseLLMProvider | None = None
        if settings.fast_llm_enabled:
            try:
                self._fast_provider = _load_provider(
                    settings.FAST_LLM_PROVIDER,
                    api_key=settings.fast_llm_api_key,
                    model=settings.FAST_LLM_MODEL,
                )
                logger.info(
                    "Fast LLM provider loaded",
                    provider=settings.FAST_LLM_PROVIDER,
                    model=settings.FAST_LLM_MODEL,
                )
            except Exception as exc:
                logger.warning(
                    "Fast LLM failed to load — falling back to primary for all tasks",
                    error=str(exc),
                )
                self._fast_provider = None

    def _resolve_provider(self, task_name: str) -> tuple[BaseLLMProvider, str]:
        """
        Return (provider, effective_model) for this task.
        Routes lightweight tasks to the fast LLM when available.
        """
        if self._fast_provider and _is_fast_task(task_name):
            return self._fast_provider, settings.FAST_LLM_MODEL
        return self._provider, settings.LLM_MODEL

    # ── Internal retry wrapper ───────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(LLMProviderError),
        stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _complete_with_retry(
        self,
        request: LLMRequest,
        provider: BaseLLMProvider,
    ) -> LLMResponse:
        try:
            return await provider.complete(request)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(
                f"LLM call failed: {exc}", detail=str(exc)
            ) from exc

    # ── Public API ───────────────────────────────────────────────────────────

    async def complete(
        self,
        request: LLMRequest,
        *,
        task_name: str = "unknown",
    ) -> LLMResponse:
        """Execute a completion request with routing, logging, and retry."""
        provider, default_model = self._resolve_provider(task_name)
        effective_model = request.model or default_model
        request.model = effective_model

        # ── Auto JSON mode ──────────────────────────────────────────────────
        # For tasks that require deterministic structured output, instruct the
        # provider to enforce JSON formatting at the API level.
        # We skip if the caller has already set a response_format (explicit wins).
        if task_name in _JSON_MODE_TASKS and "response_format" not in request.extra:
            request.extra["response_format"] = {"type": "json_object"}
            logger.debug(
                "JSON mode auto-injected",
                task=task_name,
                model=effective_model,
            )

        logger.info(
            "LLM request",
            task=task_name,
            model=effective_model,
            messages=len(request.messages),
            fast_route=provider is self._fast_provider,
            json_mode="response_format" in request.extra,
        )

        response = await self._complete_with_retry(request, provider)

        logger.info(
            "LLM response received",
            task=task_name,
            model=response.model,
            usage=response.usage,
        )
        return response


    async def stream(
        self,
        request: LLMRequest,
        *,
        task_name: str = "unknown",
    ) -> AsyncIterator[str]:
        """Stream token chunks from the LLM provider."""
        provider, default_model = self._resolve_provider(task_name)
        effective_model = request.model or default_model
        request.model = effective_model
        request.stream = True

        logger.info(
            "LLM stream started",
            task=task_name,
            model=effective_model,
            fast_route=provider is self._fast_provider,
        )

        try:
            async for chunk in provider.stream(request):
                yield chunk
        except Exception as exc:
            logger.exception("LLM stream error", task=task_name, exc_info=exc)
            raise LLMProviderError(f"LLM streaming failed: {exc}") from exc

        logger.info("LLM stream completed", task=task_name)


# ── Module-level singleton ────────────────────────────────────────────────────

_orchestrator_instance: LLMOrchestrator | None = None


def get_orchestrator() -> LLMOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = LLMOrchestrator()
    return _orchestrator_instance
