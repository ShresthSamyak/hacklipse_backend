"""
Abstract LLM provider interface.
All concrete providers (OpenAI, Anthropic, Gemini, Azure, custom) must implement this.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class LLMMessage:
    """A single message in a chat-style prompt."""
    role: str          # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    """Provider-agnostic LLM request payload."""
    messages: list[LLMMessage]
    model: str = ""                       # overrides settings.LLM_MODEL when set
    temperature: float = 0.2
    max_tokens: int = 4096
    stream: bool = False
    extra: dict = field(default_factory=dict)  # provider-specific kwargs


@dataclass
class LLMResponse:
    """Provider-agnostic LLM response."""
    content: str
    model: str
    usage: dict = field(default_factory=dict)  # prompt_tokens, completion_tokens, total_tokens
    raw: dict = field(default_factory=dict)    # full raw response for debugging


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.
    To add a new provider, subclass this and implement `complete` and `stream`.
    Register it in `app/core/ai/orchestrator.py`.
    """

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a completion request and return the full response."""
        ...

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """
        Stream token chunks as they are generated.
        Yield each chunk (delta text) as a string.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable."""
        ...
