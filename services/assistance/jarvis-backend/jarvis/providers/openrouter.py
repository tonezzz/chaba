"""OpenRouter provider with GhostRoute fallback support."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Optional

import httpx

from .base import AIProvider, Message, ProviderResponse, ProviderStreamChunk

logger = logging.getLogger(__name__)


class OpenRouterProvider(AIProvider):
    """Provider for OpenRouter API with GhostRoute fallback."""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    # Default fallback chain (will be overridden by GhostRoute)
    DEFAULT_FALLBACK_CHAIN = [
        "anthropic/claude-3.5-sonnet",
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/free",  # Smart routing
    ]

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        ghostroute_config_path: Optional[str] = None,
    ):
        super().__init__("openrouter", api_key, base_url or self.DEFAULT_BASE_URL)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://jarvis.ai",
                "X-Title": "Jarvis AI",
            },
            timeout=60.0,
        )
        self._fallback_chain: list[str] = []
        self._ghostroute_loaded = False
        self._load_ghostroute_config(ghostroute_config_path)

    def _load_ghostroute_config(self, config_path: Optional[str] = None) -> None:
        """Load GhostRoute recommended config if available."""

        paths_to_try = [
            config_path,
            os.getenv("GHOSTROUTE_CONFIG_PATH"),
            "/discovery/ghostroute/latest/recommended_config.json",
            "./discovery/ghostroute/latest/recommended_config.json",
        ]

        for path in paths_to_try:
            if not path:
                continue
            try:
                with open(path) as f:
                    config = json.load(f)
                    ranked = config.get("ranked_models", [])
                    self._fallback_chain = [m["id"] for m in ranked if m.get("id")]
                    self._ghostroute_loaded = True
                    logger.info(
                        "Loaded GhostRoute config from %s: %s models",
                        path,
                        len(self._fallback_chain)
                    )
                    return
            except FileNotFoundError:
                continue
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid GhostRoute config at {path}: {e}")
                continue

        # Fallback to defaults
        self._fallback_chain = self.DEFAULT_FALLBACK_CHAIN.copy()
        logger.info("Using default OpenRouter fallback chain")

    def supports_model(self, model_id: str) -> bool:
        """OpenRouter supports any model ID that follows their format."""
        # Accept provider/model format
        return "/" in model_id or model_id == "openrouter/free"

    def is_healthy(self) -> bool:
        """Check provider health."""
        return not self.is_degraded

    @property
    def fallback_chain(self) -> list[str]:
        """Get current fallback chain (GhostRoute-ranked or default)."""
        return self._fallback_chain.copy()

    def _to_openai_messages(self, messages: list[Message]) -> list[dict]:
        """Convert messages to OpenAI format."""
        result = []
        for msg in messages:
            openai_msg: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_calls:
                openai_msg["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id
            result.append(openai_msg)
        return result

    async def _try_generate(
        self,
        messages: list[dict],
        model_id: str,
        temperature: float,
        max_tokens: Optional[int],
        tools: Optional[list[dict]],
        stream: bool = False,
    ) -> tuple[bool, Any]:
        """Try generation with a model. Returns (success, response_or_error)."""

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            if stream:
                response = await self.client.post(
                    "/chat/completions",
                    json=payload,
                    timeout=60.0,
                )
            else:
                response = await self.client.post(
                    "/chat/completions",
                    json=payload,
                    timeout=30.0,
                )
            response.raise_for_status()
            return True, response

        except httpx.HTTPStatusError as e:
            # Check for rate limit or model unavailable
            if e.response.status_code in (429, 503, 502):
                logger.warning(f"Model {model_id} unavailable: {e.response.status_code}")
                return False, e
            raise
        except httpx.TimeoutException as e:
            logger.warning(f"Model {model_id} timeout")
            return False, e
        except Exception as e:
            logger.warning(f"Model {model_id} error: {e}")
            return False, e

    async def generate(
        self,
        messages: list[Message],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> ProviderResponse:
        """Generate with fallback chain."""

        openai_messages = self._to_openai_messages(messages)

        # If specific model requested, try it first
        models_to_try = [model_id]

        # Add GhostRoute fallback chain
        for fallback_id in self._fallback_chain:
            if fallback_id != model_id:
                models_to_try.append(fallback_id)

        last_error: Optional[Exception] = None

        for try_model in models_to_try:
            success, result = await self._try_generate(
                openai_messages,
                try_model,
                temperature,
                max_tokens,
                tools,
                stream=False,
            )

            if success:
                data = result.json()
                choice = data["choices"][0]
                message = choice["message"]

                self.record_success()

                return ProviderResponse(
                    text=message.get("content", ""),
                    model_id=try_model,
                    provider=self.provider_name,
                    input_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                    output_tokens=data.get("usage", {}).get("completion_tokens", 0),
                    finish_reason=choice.get("finish_reason"),
                    tool_calls=message.get("tool_calls", []),
                    metadata={
                        "native_finish_reason": choice.get("native_finish_reason"),
                        "provider_name": data.get("provider"),
                    }
                )

            last_error = result if isinstance(result, Exception) else None
            logger.warning(f"Model {try_model} failed, trying fallback...")

        # All models failed
        if last_error:
            self.record_error(last_error)
            raise last_error

        raise RuntimeError("All fallback models failed")

    async def generate_stream(
        self,
        messages: list[Message],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> AsyncIterator[ProviderStreamChunk]:
        """Generate streaming with fallback."""

        openai_messages = self._to_openai_messages(messages)
        models_to_try = [model_id] + [m for m in self._fallback_chain if m != model_id]

        for try_model in models_to_try:
            success, result = await self._try_generate(
                openai_messages,
                try_model,
                temperature,
                max_tokens,
                tools,
                stream=True,
            )

            if not success:
                logger.warning(f"Model {try_model} failed for streaming, trying fallback...")
                continue

            # Stream successful model
            buffer = ""
            async for line in result.aiter_lines():
                if not line.startswith("data: "):
                    continue

                data = line[6:]  # Remove "data: " prefix
                if data == "[DONE]":
                    yield ProviderStreamChunk(text="", is_finished=True)
                    break

                try:
                    chunk_data = json.loads(data)
                    delta = chunk_data["choices"][0].get("delta", {})
                    text = delta.get("content", "")

                    finish_reason = chunk_data["choices"][0].get("finish_reason")
                    tool_calls = delta.get("tool_calls", [])

                    if text or finish_reason or tool_calls:
                        yield ProviderStreamChunk(
                            text=text,
                            is_finished=finish_reason is not None,
                            model_id=try_model,
                            finish_reason=finish_reason,
                            tool_calls=tool_calls,
                        )

                except json.JSONDecodeError:
                    continue
                except (KeyError, IndexError):
                    continue

            self.record_success()
            return

        raise RuntimeError("All fallback models failed for streaming")

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
