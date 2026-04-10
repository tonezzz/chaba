"""Provider abstraction layer for multi-AI support."""
from __future__ import annotations

from .base import AIProvider, ProviderResponse, ProviderStreamChunk
from .gemini import GeminiProvider
from .openrouter import OpenRouterProvider
from .router import ProviderRouter
from .smart import SmartProvider, get_smart_provider

__all__ = [
    "AIProvider",
    "ProviderResponse",
    "ProviderStreamChunk",
    "GeminiProvider",
    "OpenRouterProvider",
    "ProviderRouter",
    "SmartProvider",
    "get_smart_provider",
]
