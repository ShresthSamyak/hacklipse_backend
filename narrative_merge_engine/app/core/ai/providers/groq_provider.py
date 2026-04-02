"""
Groq Provider — concrete implementation of BaseLLMProvider.

Groq's API is OpenAI-compatible, so we use the openai SDK pointed at
Groq's base URL.  This lets us reuse all the existing LLMRequest/LLMResponse
types while transparently switching inference to Groq's ultra-fast hardware.

Supported capabilities:
  - Async completions (chat)
  - Async streaming
  - JSON mode (response_format={"type": "json_object"})
  - Health check via models.list()

Models (as of 2025 — check https://console.groq.com/docs/models for updates):
  - llama3-70b-8192    (default — best quality)
  - llama3-8b-8192     (fast / lightweight)
  - gemma2-9b-it       (Google OSS, fast)
  - mixtral-8x7b-32768 (large context)
  - whisper-large-v3-turbo  (STT — handled by STT service, not this class)

SDK: openai>=1.0  (Groq uses an OpenAI-compatible REST API)
Install: pip install openai groq
"""

from __future__ import annotations

from typing import AsyncIterator

from app.core.ai.base_provider import BaseLLMProvider, LLMRequest, LLMResponse
from app.core.config import settings
from app.core.exceptions import LLMProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Groq's OpenAI-compatible base URL
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(BaseLLMProvider):
    """
    Async Groq provider using the OpenAI-compatible SDK.

    Requires:
        LLM_PROVIDER=groq
        LLM_API_KEY=<your Groq API key>
        LLM_MODEL=llama3-70b-8192  (or any Groq-hosted model)

    JSON mode:
        Set request.extra["response_format"] = {"type": "json_object"}
        — Groq supports this for llama3 and mixtral models.
        The orchestrator sets this automatically for structured-output tasks.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "openai package is required for GroqProvider. "
                "Install it with: pip install openai"
            ) from exc

        self._api_key = api_key or settings.LLM_API_KEY
        self._default_model = model or settings.LLM_MODEL

        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=_GROQ_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,  # retries handled by orchestrator's tenacity wrapper
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._default_model

        # Build extra kwargs — pass through anything in request.extra
        # (e.g. response_format={"type": "json_object"} for JSON mode)
        extra: dict = dict(request.extra)

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=False,
                **extra,
            )
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage=dict(response.usage) if response.usage else {},
                raw=response.model_dump(),
            )
        except Exception as exc:
            logger.error("Groq completion failed", error=str(exc), model=model)
            raise LLMProviderError(f"Groq call failed: {exc}") from exc

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        model = request.model or self._default_model
        extra: dict = dict(request.extra)

        try:
            async with self._client.chat.completions.stream(
                model=model,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                **extra,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
        except Exception as exc:
            logger.error("Groq streaming failed", error=str(exc), model=model)
            raise LLMProviderError(f"Groq streaming failed: {exc}") from exc

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
