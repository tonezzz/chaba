"""Provider abstraction layer for multi-AI support."""
from __future__ import annotations

import logging

from .base import AIProvider, ProviderResponse, ProviderStreamChunk

logger = logging.getLogger(__name__)

# Import optional providers with graceful fallback
GeminiProvider = None
try:
    from .gemini import GeminiProvider
except ImportError as e:
    logger.warning(f"GeminiProvider not available: {e}")

OpenRouterProvider = None
try:
    from .openrouter import OpenRouterProvider
except ImportError as e:
    logger.warning(f"OpenRouterProvider not available: {e}")

from .router import ProviderRouter, get_provider_router
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
    "get_provider_router",
]
