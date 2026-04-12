"""Multi-provider router with failover support."""
from __future__ import annotations

import logging
import os
from typing import Optional

from .base import AIProvider, Message, ProviderResponse, ProviderStreamChunk

# Import optional providers - may be None if dependencies not available
from . import GeminiProvider, OpenRouterProvider

logger = logging.getLogger(__name__)


class ProviderRouter:
    """Routes requests across multiple providers with failover."""

    def __init__(self):
        self.providers: dict[str, AIProvider] = {}
        self._initialize_providers()

    def _initialize_providers(self) -> None:
        """Initialize providers from environment."""

        # Gemini
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key and GeminiProvider is not None:
            try:
                self.providers["gemini"] = GeminiProvider(api_key=gemini_key)
                logger.info("Gemini provider initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini: {e}")

        # OpenRouter
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if openrouter_key and OpenRouterProvider is not None:
            try:
                ghostroute_path = os.getenv(
                    "GHOSTROUTE_CONFIG_PATH",
                    "/discovery/ghostroute/latest/recommended_config.json"
                )
                self.providers["openrouter"] = OpenRouterProvider(
                    api_key=openrouter_key,
                    ghostroute_config_path=ghostroute_path,
                )
                logger.info("OpenRouter provider initialized (GhostRoute: %s)",
                           "loaded" if self.providers["openrouter"]._ghostroute_loaded else "default")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenRouter: {e}")

        if not self.providers:
            logger.warning("No AI providers initialized! Set GEMINI_API_KEY or OPENROUTER_API_KEY")

    def get_provider(self, name: str) -> Optional[AIProvider]:
        """Get a provider by name."""
        return self.providers.get(name)

    def get_provider_for_model(self, model_id: str) -> Optional[AIProvider]:
        """Get the best provider for a model."""

        # Direct provider mapping from model ID
        if model_id.startswith("gemini") or model_id.startswith("models/gemini"):
            return self.providers.get("gemini")

        if "/" in model_id or model_id.startswith("openrouter/"):
            return self.providers.get("openrouter")

        # Check which provider supports this model
        for name, provider in self.providers.items():
            if provider.supports_model(model_id):
                return provider

        return None

    async def generate(
        self,
        messages: list[Message],
        model_id: str,
        preferred_provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        enable_fallback: bool = True,
    ) -> ProviderResponse:
        """Generate with automatic provider selection and failover."""

        providers_to_try = []

        # Preferred provider first
        if preferred_provider and preferred_provider in self.providers:
            providers_to_try.append(self.providers[preferred_provider])

        # Provider for this specific model
        model_provider = self.get_provider_for_model(model_id)
        if model_provider and model_provider not in providers_to_try:
            providers_to_try.append(model_provider)

        # All other healthy providers as fallbacks
        if enable_fallback:
            for name, provider in self.providers.items():
                if provider not in providers_to_try and provider.is_healthy():
                    providers_to_try.append(provider)

        if not providers_to_try:
            raise RuntimeError("No providers available")

        last_error: Optional[Exception] = None

        for provider in providers_to_try:
            try:
                logger.debug(f"Trying provider {provider.provider_name} for model {model_id}")
                response = await provider.generate(
                    messages=messages,
                    model_id=model_id,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                )
                logger.info(
                    "Generated via %s using %s (input=%d, output=%d tokens)",
                    provider.provider_name,
                    response.model_id,
                    response.input_tokens,
                    response.output_tokens,
                )
                return response

            except Exception as e:
                logger.warning(f"Provider {provider.provider_name} failed: {e}")
                provider.record_error(e)
                last_error = e
                continue

        if last_error:
            raise last_error
        raise RuntimeError("All providers failed")

    async def generate_stream(
        self,
        messages: list[Message],
        model_id: str,
        preferred_provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
    ):
        """Generate streaming with provider selection."""

        provider = self.get_provider_for_model(model_id)
        if not provider:
            raise RuntimeError(f"No provider supports model: {model_id}")

        async for chunk in provider.generate_stream(
            messages=messages,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        ):
            yield chunk

    def get_healthy_providers(self) -> list[str]:
        """Get list of healthy provider names."""
        return [name for name, p in self.providers.items() if p.is_healthy()]

    def get_provider_status(self) -> dict[str, dict]:
        """Get status of all providers."""
        return {
            name: {
                "healthy": p.is_healthy(),
                "degraded": p.is_degraded,
                "consecutive_errors": p._consecutive_errors,
                "last_error": str(p._last_error) if p._last_error else None,
            }
            for name, p in self.providers.items()
        }


# Global singleton
_router: Optional[ProviderRouter] = None


def get_provider_router() -> ProviderRouter:
    """Get or create the global ProviderRouter."""
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
