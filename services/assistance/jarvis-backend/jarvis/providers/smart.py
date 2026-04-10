"""Smart provider with task-aware model selection."""
from __future__ import annotations

import logging
import os
from typing import Optional

from jarvis.models import (
    TaskClassifier,
    TaskProfile,
    get_best_model,
    seed_all_models,
)
from jarvis.models.registry import update_model_metrics

logger = logging.getLogger(__name__)


class SmartProvider:
    """Provider that intelligently selects models based on task."""

    def __init__(self) -> None:
        self.classifier = TaskClassifier()
        self.budget_tier = os.getenv("JARVIS_BUDGET_TIER", "auto")
        self.preferred_provider = os.getenv("JARVIS_PREFERRED_PROVIDER")

        # Seed model registry on init
        seed_all_models()
        logger.info("SmartProvider initialized with budget_tier=%s", self.budget_tier)

    def select_model(
        self,
        user_text: str,
        has_attachment: bool = False,
        preferred_provider: Optional[str] = None,
        force_budget_tier: Optional[str] = None,
    ) -> tuple[str, str, TaskProfile]:
        """Select best model for a user message.

        Returns:
            Tuple of (model_id, provider, task_profile)
        """
        # Classify the task
        task = self.classifier.classify(user_text, has_attachment=has_attachment)
        logger.debug("Classified as %s (confidence=%.2f)", task.primary_type.value, task.confidence)

        # Determine budget tier
        budget = force_budget_tier or self._determine_budget_tier(task)

        # Select best model
        provider = preferred_provider or self.preferred_provider
        model_info = get_best_model(
            task_profile=task,
            budget_tier=budget,
            preferred_provider=provider,
        )

        if not model_info:
            # Ultimate fallback to Gemini Flash
            logger.warning("No suitable model found, falling back to Gemini Flash")
            return "gemini-2.5-flash", "gemini", task

        return model_info.id, model_info.provider, task

    def _determine_budget_tier(self, task: TaskProfile) -> str:
        """Determine budget tier based on task and settings."""

        if self.budget_tier != "auto":
            return self.budget_tier

        # Auto logic: simple tasks = free/cheap, complex = standard
        if task.complexity == "low" and task.confidence > 0.8:
            return "free"  # Try free models first
        elif task.complexity == "high":
            return "standard"
        return "cheap"

    def build_system_prompt(self, task: TaskProfile) -> str:
        """Build task-optimized system prompt."""

        base = "You are Jarvis, a helpful AI assistant."

        task_hints = {
            "code": " When writing code, include comments and explain key logic.",
            "reasoning": " Think step by step and explain your reasoning clearly.",
            "creative": " Be creative and engaging in your response.",
            "summarization": " Be concise. Focus on the most important points.",
            "extraction": " Provide structured, parseable output.",
            "tool_use": " Use available tools when helpful.",
        }

        hint = task_hints.get(task.primary_type.value, "")
        return base + hint

    def get_temperature(self, task: TaskProfile) -> float:
        """Get optimal temperature for task."""
        if task.primary_type.value == "creative":
            return 0.9
        elif task.primary_type.value in ("code", "extraction"):
            return 0.3
        return 0.7

    def record_result(
        self,
        model_id: str,
        latency_ms: int,
        success: bool,
    ) -> None:
        """Record metrics for feedback loop."""
        update_model_metrics(model_id, latency_ms, success)


# Global singleton
_smart_provider: Optional[SmartProvider] = None


def get_smart_provider() -> SmartProvider:
    """Get or create the global SmartProvider instance."""
    global _smart_provider
    if _smart_provider is None:
        _smart_provider = SmartProvider()
    return _smart_provider
