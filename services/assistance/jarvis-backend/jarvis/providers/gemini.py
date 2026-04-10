"""Gemini provider implementation."""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from google import genai
from google.genai import types

from .base import AIProvider, Message, ProviderResponse, ProviderStreamChunk

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    """Provider for Google Gemini API."""

    # Models supported via REST API (non-Live)
    SUPPORTED_MODELS = {
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite-preview",
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-2.0-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    }

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        super().__init__("gemini", api_key, base_url)
        self.client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"}
        )

    def supports_model(self, model_id: str) -> bool:
        """Check if we support this model."""
        # Strip 'models/' prefix if present
        clean_id = model_id.replace("models/", "")
        return any(clean_id.startswith(m) or m in clean_id for m in self.SUPPORTED_MODELS)

    def is_healthy(self) -> bool:
        """Check provider health."""
        return not self.is_degraded

    def _to_gemini_messages(self, messages: list[Message]) -> list[types.Content]:
        """Convert our Message format to Gemini Content."""
        contents = []
        for msg in messages:
            role = "user" if msg.role in ("user", "system") else "model"
            parts = [types.Part(text=msg.content)]
            contents.append(types.Content(role=role, parts=parts))
        return contents

    def _to_gemini_tools(self, tools: list[dict]) -> list[types.Tool]:
        """Convert tool definitions to Gemini format."""
        gemini_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool.get("function", {})
                gemini_tools.append(types.Tool(
                    function_declarations=[types.FunctionDeclaration(
                        name=fn.get("name", ""),
                        description=fn.get("description", ""),
                        parameters=fn.get("parameters", {}),
                    )]
                ))
        return gemini_tools

    async def generate(
        self,
        messages: list[Message],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> ProviderResponse:
        """Generate response via Gemini REST API."""

        try:
            # Format model ID
            if not model_id.startswith("models/"):
                model_id = f"models/{model_id}"

            # Build request
            contents = self._to_gemini_messages(messages)
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )

            # Add system instruction if first message is system
            if messages and messages[0].role == "system":
                config.system_instruction = messages[0].content
                contents = contents[1:]  # Remove from messages

            # Add tools
            if tools:
                config.tools = self._to_gemini_tools(tools)
                config.automatic_function_calling = types.AutomaticFunctionCallingConfig(
                    disable=True  # We handle manually
                )

            # Call API
            response = await self.client.aio.models.generate_content(
                model=model_id,
                contents=contents,
                config=config,
            )

            # Extract text
            text = ""
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        text += part.text

            self.record_success()

            return ProviderResponse(
                text=text,
                model_id=model_id.replace("models/", ""),
                provider=self.provider_name,
                input_tokens=response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
                output_tokens=response.usage_metadata.candidates_token_count if response.usage_metadata else 0,
            )

        except Exception as e:
            self.record_error(e)
            logger.error(f"Gemini generate error: {e}")
            raise

    async def generate_stream(
        self,
        messages: list[Message],
        model_id: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict]] = None,
        **kwargs
    ) -> AsyncIterator[ProviderStreamChunk]:
        """Generate streaming response via Gemini."""

        try:
            if not model_id.startswith("models/"):
                model_id = f"models/{model_id}"

            contents = self._to_gemini_messages(messages)
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )

            if messages and messages[0].role == "system":
                config.system_instruction = messages[0].content
                contents = contents[1:]

            if tools:
                config.tools = self._to_gemini_tools(tools)
                config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)

            async for chunk in await self.client.aio.models.generate_content_stream(
                model=model_id,
                contents=contents,
                config=config,
            ):
                text = ""
                if chunk.candidates:
                    for part in chunk.candidates[0].content.parts:
                        if part.text:
                            text += part.text

                finish_reason = None
                if chunk.candidates and chunk.candidates[0].finish_reason:
                    finish_reason = chunk.candidates[0].finish_reason.name

                yield ProviderStreamChunk(
                    text=text,
                    is_finished=finish_reason is not None,
                    model_id=model_id.replace("models/", ""),
                    finish_reason=finish_reason,
                )

            self.record_success()

        except Exception as e:
            self.record_error(e)
            logger.error(f"Gemini stream error: {e}")
            raise
