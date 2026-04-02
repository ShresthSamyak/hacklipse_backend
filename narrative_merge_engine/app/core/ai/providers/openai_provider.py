"""
OpenAI Provider — concrete implementation of BaseLLMProvider.
Swap this file out (or add siblings) to support other providers.

SDK: openai>=1.0  (async client)
Install: pip install openai
"""

from __future__ import annotations

from typing import AsyncIterator

import httpx

from app.core.ai.base_provider import BaseLLMProvider, LLMRequest, LLMResponse
from app.core.config import settings
from app.core.exceptions import LLMProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """
    Async OpenAI provider.
    Requires: OPENAI_API_KEY in env (read via LLM_API_KEY setting).
    """

    def __init__(self) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

        self._client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL or None,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,  # retries handled by orchestrator
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=request.model or settings.LLM_MODEL,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=False,
                **request.extra,
            )
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage=dict(response.usage) if response.usage else {},
                raw=response.model_dump(),
            )
        except Exception as exc:
            raise LLMProviderError(f"OpenAI call failed: {exc}") from exc

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        try:
            async with self._client.chat.completions.stream(
                model=request.model or settings.LLM_MODEL,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                **request.extra,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
        except Exception as exc:
            raise LLMProviderError(f"OpenAI streaming failed: {exc}") from exc

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
