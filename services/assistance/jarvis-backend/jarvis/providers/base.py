"""Base interface for AI providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class ProviderResponse:
    """Response from an AI provider."""

    text: str
    model_id: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderStreamChunk:
    """Streaming chunk from an AI provider."""

    text: str = ""
    is_finished: bool = False
    model_id: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class Message:
    """Chat message."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    def __init__(self, provider_name: str, api_key: str, base_url: Optional[str] = None):
        self.provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url
        self._last_error: Optional[Exception] = None
        self._consecutive_errors: int = 0

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> ProviderResponse:
        """Generate a complete response."""
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[Message],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> AsyncIterator[ProviderStreamChunk]:
        """Generate a streaming response."""
        pass

    @abstractmethod
    def supports_model(self, model_id: str) -> bool:
        """Check if this provider supports the given model."""
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if provider is currently healthy."""
        pass

    def record_error(self, error: Exception) -> None:
        """Record an error for health tracking."""
        self._last_error = error
        self._consecutive_errors += 1

    def record_success(self) -> None:
        """Record a success for health tracking."""
        self._consecutive_errors = 0
        self._last_error = None

    @property
    def is_degraded(self) -> bool:
        """Check if provider is degraded (too many errors)."""
        return self._consecutive_errors >= 3

    def format_tools(self, tools: list[dict]) -> list[dict]:
        """Format tools for this provider's API. Override if needed."""
        return tools
