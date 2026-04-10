"""Seed the model registry with known models."""
from __future__ import annotations

from decimal import Decimal

from .registry import ModelCapability, ModelInfo, register_model
from .tasks import TaskType


def seed_gemini_models() -> None:
    """Register Gemini models with task suitability."""

    register_model(
        ModelInfo(
            id="gemini-2.5-flash",
            provider="gemini",
            display_name="Gemini 2.5 Flash",
            context_window=1_000_000,
            cost_per_1k_input=Decimal("0.00015"),  # $0.15 per 1M
            cost_per_1k_output=Decimal("0.0006"),
            capabilities=[
                ModelCapability(TaskType.CHAT, 0.9, "Fast, good for conversation"),
                ModelCapability(TaskType.SUMMARIZATION, 0.85, "Long context useful"),
                ModelCapability(TaskType.CODE, 0.7, "Decent coding but not best"),
                ModelCapability(TaskType.VOICE, 0.9, "Low latency, streaming"),
                ModelCapability(TaskType.TOOL_USE, 0.8, "Good function calling"),
                ModelCapability(TaskType.VISION, 0.85, "Strong multimodal"),
            ],
            supports_vision=True,
            supports_tools=True,
            supports_json_mode=True,
            rate_limit_tier="high",
        )
    )

    register_model(
        ModelInfo(
            id="gemini-2.5-pro",
            provider="gemini",
            display_name="Gemini 2.5 Pro",
            context_window=2_000_000,
            cost_per_1k_input=Decimal("0.00125"),
            cost_per_1k_output=Decimal("0.005"),
            capabilities=[
                ModelCapability(TaskType.REASONING, 0.95, "Best reasoning in Gemini family"),
                ModelCapability(TaskType.CODE, 0.9, "Strong coding performance"),
                ModelCapability(TaskType.CREATIVE, 0.85, "Good writing quality"),
                ModelCapability(TaskType.EXTRACTION, 0.9, "Reliable structured output"),
                ModelCapability(TaskType.SUMMARIZATION, 0.95, "Huge context window"),
            ],
            supports_vision=True,
            supports_tools=True,
            supports_json_mode=True,
            rate_limit_tier="standard",
        )
    )

    register_model(
        ModelInfo(
            id="gemini-2.5-flash-lite-preview",
            provider="gemini",
            display_name="Gemini 2.5 Flash Lite Preview",
            context_window=1_000_000,
            cost_per_1k_input=Decimal("0.0001"),
            cost_per_1k_output=Decimal("0.0004"),
            capabilities=[
                ModelCapability(TaskType.CHAT, 0.85, "Fast and cheap"),
                ModelCapability(TaskType.VOICE, 0.9, "Low latency"),
                ModelCapability(TaskType.SUMMARIZATION, 0.8, "Good for simple tasks"),
            ],
            supports_vision=False,  # Lite may not have vision
            supports_tools=True,
            supports_json_mode=True,
            rate_limit_tier="high",
        )
    )


def seed_openrouter_free_models() -> None:
    """Register OpenRouter free models."""

    register_model(
        ModelInfo(
            id="anthropic/claude-3.5-sonnet:free",
            provider="openrouter",
            display_name="Claude 3.5 Sonnet (Free)",
            context_window=200_000,
            cost_per_1k_input=Decimal("0"),
            cost_per_1k_output=Decimal("0"),
            capabilities=[
                ModelCapability(TaskType.REASONING, 0.95, "Excellent reasoning"),
                ModelCapability(TaskType.CODE, 0.95, "Strong coding"),
                ModelCapability(TaskType.CREATIVE, 0.9, "Great writing"),
                ModelCapability(TaskType.TOOL_USE, 0.9, "Reliable tool use"),
                ModelCapability(TaskType.CHAT, 0.9, "Conversational"),
            ],
            supports_vision=True,
            supports_tools=True,
            rate_limit_tier="free",
        )
    )

    register_model(
        ModelInfo(
            id="google/gemini-2.0-flash-exp:free",
            provider="openrouter",
            display_name="Gemini 2.0 Flash (Free)",
            context_window=1_000_000,
            cost_per_1k_input=Decimal("0"),
            cost_per_1k_output=Decimal("0"),
            capabilities=[
                ModelCapability(TaskType.CHAT, 0.9, "Fast responses"),
                ModelCapability(TaskType.VISION, 0.9, "Strong multimodal"),
                ModelCapability(TaskType.SUMMARIZATION, 0.85, "Huge context"),
                ModelCapability(TaskType.TOOL_USE, 0.8, "Function calling"),
            ],
            supports_vision=True,
            supports_tools=True,
            rate_limit_tier="free",
        )
    )

    register_model(
        ModelInfo(
            id="meta-llama/llama-3.3-70b-instruct:free",
            provider="openrouter",
            display_name="Llama 3.3 70B (Free)",
            context_window=128_000,
            cost_per_1k_input=Decimal("0"),
            cost_per_1k_output=Decimal("0"),
            capabilities=[
                ModelCapability(TaskType.CHAT, 0.85, "Solid open model"),
                ModelCapability(TaskType.CODE, 0.75, "Decent coding"),
                ModelCapability(TaskType.REASONING, 0.75, "Reasonable reasoning"),
            ],
            supports_vision=False,
            supports_tools=True,
            rate_limit_tier="free",
        )
    )

    register_model(
        ModelInfo(
            id="deepseek/deepseek-chat:free",
            provider="openrouter",
            display_name="DeepSeek Chat (Free)",
            context_window=64_000,
            cost_per_1k_input=Decimal("0"),
            cost_per_1k_output=Decimal("0"),
            capabilities=[
                ModelCapability(TaskType.REASONING, 0.85, "Good reasoning"),
                ModelCapability(TaskType.CODE, 0.8, "Coding capable"),
            ],
            supports_vision=False,
            supports_tools=False,
            rate_limit_tier="free",
        )
    )

    register_model(
        ModelInfo(
            id="openrouter/free",
            provider="openrouter",
            display_name="OpenRouter Free Router",
            context_window=100_000,
            cost_per_1k_input=Decimal("0"),
            cost_per_1k_output=Decimal("0"),
            capabilities=[
                ModelCapability(TaskType.CHAT, 0.85, "Smart routing"),
                ModelCapability(TaskType.CODE, 0.8, "Routes to best free code model"),
            ],
            supports_vision=True,
            supports_tools=True,
            rate_limit_tier="free",
        )
    )


def seed_premium_models() -> None:
    """Register paid API models."""

    register_model(
        ModelInfo(
            id="claude-3-5-sonnet-20241022",
            provider="anthropic",
            display_name="Claude 3.5 Sonnet",
            context_window=200_000,
            cost_per_1k_input=Decimal("0.003"),
            cost_per_1k_output=Decimal("0.015"),
            capabilities=[
                ModelCapability(TaskType.REASONING, 0.95, "Top tier reasoning"),
                ModelCapability(TaskType.CODE, 0.95, "Excellent for programming"),
                ModelCapability(TaskType.CREATIVE, 0.9, "High quality writing"),
                ModelCapability(TaskType.TOOL_USE, 0.95, "Best tool use"),
                ModelCapability(TaskType.VISION, 0.9, "Strong vision"),
            ],
            supports_vision=True,
            supports_tools=True,
            rate_limit_tier="high",
        )
    )

    register_model(
        ModelInfo(
            id="gpt-4o",
            provider="openai",
            display_name="GPT-4o",
            context_window=128_000,
            cost_per_1k_input=Decimal("0.005"),
            cost_per_1k_output=Decimal("0.015"),
            capabilities=[
                ModelCapability(TaskType.VISION, 0.95, "Best multimodal"),
                ModelCapability(TaskType.REASONING, 0.9, "Strong reasoning"),
                ModelCapability(TaskType.CODE, 0.9, "Good coding"),
                ModelCapability(TaskType.TOOL_USE, 0.9, "Reliable tools"),
            ],
            supports_vision=True,
            supports_tools=True,
            supports_json_mode=True,
            rate_limit_tier="high",
        )
    )

    register_model(
        ModelInfo(
            id="gpt-4o-mini",
            provider="openai",
            display_name="GPT-4o Mini",
            context_window=128_000,
            cost_per_1k_input=Decimal("0.00015"),
            cost_per_1k_output=Decimal("0.0006"),
            capabilities=[
                ModelCapability(TaskType.CHAT, 0.85, "Good conversation"),
                ModelCapability(TaskType.CODE, 0.75, "Decent coding"),
                ModelCapability(TaskType.TOOL_USE, 0.85, "Reliable tools"),
                ModelCapability(TaskType.VISION, 0.8, "Vision capable"),
            ],
            supports_vision=True,
            supports_tools=True,
            supports_json_mode=True,
            rate_limit_tier="high",
        )
    )


def seed_all_models() -> None:
    """Seed all known models into the registry."""
    seed_gemini_models()
    seed_openrouter_free_models()
    seed_premium_models()
