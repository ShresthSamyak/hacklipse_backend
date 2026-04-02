"""
LLM Orchestration Layer.

Responsibilities:
  - Resolve the active LLM provider from config (never hard-coded).
  - Apply retry logic with exponential back-off (via tenacity).
  - Emit structured logs for every LLM call.
  - Expose a single, uniform interface to all services.

To add a new provider:
  1. Create app/core/ai/providers/<name>.py implementing BaseLLMProvider.
  2. Add it to PROVIDER_REGISTRY below.
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


# ---------------------------------------------------------------------------
# Provider registry  (lazy imports to avoid importing unused SDKs at boot)
# ---------------------------------------------------------------------------

def _load_provider(provider_name: str) -> BaseLLMProvider:
    """
    Factory: instantiate the correct provider implementation.
    Add entries here as new providers are implemented.
    """
    if provider_name == "openai":
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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class LLMOrchestrator:
    """
    Central orchestration layer for all LLM interactions.
    Services should depend on this class, not on concrete providers.
    """

    def __init__(self) -> None:
        self._provider: BaseLLMProvider = _load_provider(settings.LLM_PROVIDER)
        logger.info("LLM provider loaded", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    # ── Internal retry wrapper ───────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(LLMProviderError),
        stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _complete_with_retry(self, request: LLMRequest) -> LLMResponse:
        try:
            return await self._provider.complete(request)
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
        """Execute a completion request with logging and retry."""
        effective_model = request.model or settings.LLM_MODEL
        request.model = effective_model

        logger.info(
            "LLM request",
            task=task_name,
            model=effective_model,
            messages=len(request.messages),
        )

        response = await self._complete_with_retry(request)

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
        effective_model = request.model or settings.LLM_MODEL
        request.model = effective_model
        request.stream = True

        logger.info("LLM stream started", task=task_name, model=effective_model)

        try:
            async for chunk in self._provider.stream(request):
                yield chunk
        except Exception as exc:
            logger.exception("LLM stream error", task=task_name, exc_info=exc)
            raise LLMProviderError(f"LLM streaming failed: {exc}") from exc

        logger.info("LLM stream completed", task=task_name)


# ---------------------------------------------------------------------------
# Module-level singleton (can be overridden in tests with DI)
# ---------------------------------------------------------------------------

_orchestrator_instance: LLMOrchestrator | None = None


def get_orchestrator() -> LLMOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = LLMOrchestrator()
    return _orchestrator_instance
