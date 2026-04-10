"""Model registry with task-based ranking."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .tasks import TaskType, TaskProfile

logger = logging.getLogger(__name__)


@dataclass
class ModelCapability:
    """What a model can do well."""

    task_type: TaskType
    score: float  # 0-1 suitability for this task
    reasoning: str  # Why this score


@dataclass
class ModelInfo:
    """Complete model specification."""

    id: str  # Provider-specific ID
    provider: str  # "gemini", "openrouter", "anthropic", "openai"
    display_name: str
    context_window: int
    cost_per_1k_input: Decimal
    cost_per_1k_output: Decimal
    capabilities: list[ModelCapability] = field(default_factory=list)

    # Performance metrics (updated dynamically)
    avg_latency_ms: Optional[int] = None
    success_rate_24h: Optional[float] = None
    rate_limit_tier: str = "standard"  # "free", "standard", "high"

    # Feature flags
    supports_vision: bool = False
    supports_tools: bool = False
    supports_json_mode: bool = False

    def get_task_score(self, task_type: TaskType) -> float:
        """Get suitability score for a task type."""
        for cap in self.capabilities:
            if cap.task_type == task_type:
                return cap.score
        return 0.5  # Default mediocre score

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Estimate cost for a request."""
        input_cost = Decimal(input_tokens) / 1000 * self.cost_per_1k_input
        output_cost = Decimal(output_tokens) / 1000 * self.cost_per_1k_output
        return input_cost + output_cost

    def __repr__(self) -> str:
        return f"ModelInfo({self.id} @ {self.provider})"


# Global model registry
_MODEL_REGISTRY: dict[str, ModelInfo] = {}


def register_model(info: ModelInfo) -> None:
    """Register a model in the global registry."""
    _MODEL_REGISTRY[info.id] = info
    logger.debug("Registered model: %s", info.id)


def get_model(model_id: str) -> Optional[ModelInfo]:
    """Get a model by ID."""
    return _MODEL_REGISTRY.get(model_id)


def get_models_for_task(
    task_type: TaskType,
    provider: Optional[str] = None,
    min_context: Optional[int] = None,
    require_vision: bool = False,
    require_tools: bool = False,
    max_cost_per_1k: Optional[Decimal] = None,
    prefer_free: bool = False,
) -> list[ModelInfo]:
    """Get models ranked by suitability for a task."""

    candidates = []
    for model in _MODEL_REGISTRY.values():
        # Filter by provider
        if provider and model.provider != provider:
            continue

        # Filter by requirements
        if min_context and model.context_window < min_context:
            continue
        if require_vision and not model.supports_vision:
            continue
        if require_tools and not model.supports_tools:
            continue
        if max_cost_per_1k is not None and model.cost_per_1k_input > max_cost_per_1k:
            continue

        # Calculate composite score
        task_score = model.get_task_score(task_type)
        reliability = model.success_rate_24h or 0.9
        speed_score = (
            1.0
            if not model.avg_latency_ms
            else max(0, 1 - model.avg_latency_ms / 10000)
        )

        # Cost bonus (cheaper = better, normalize to 0-1)
        max_cost = Decimal("0.01")  # $0.01 per 1K as reference
        cost_score = float(max(0, 1 - model.cost_per_1k_input / max_cost))

        # Weighted composite
        if prefer_free or max_cost_per_1k == Decimal("0"):
            # For free tier, prioritize success rate
            composite = task_score * 0.4 + reliability * 0.4 + speed_score * 0.2
        else:
            # For paid, balance quality and cost
            composite = (
                task_score * 0.4 + reliability * 0.3 + speed_score * 0.2 + cost_score * 0.1
            )

        candidates.append((composite, model))

    # Sort by composite score descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in candidates]


def get_best_model(
    task_profile: TaskProfile,
    budget_tier: str = "auto",  # "free", "cheap", "standard", "premium", "auto"
    preferred_provider: Optional[str] = None,
) -> Optional[ModelInfo]:
    """Get best model for a task based on constraints."""

    # Determine filters from budget tier
    max_cost: Optional[Decimal] = None
    prefer_free = False

    if budget_tier == "free":
        max_cost = Decimal("0")
        prefer_free = True
    elif budget_tier == "cheap":
        max_cost = Decimal("0.001")  # $0.001 per 1K tokens
    elif budget_tier == "standard":
        max_cost = Decimal("0.01")  # $0.01 per 1K tokens
    elif budget_tier == "premium":
        max_cost = None  # No limit

    # Get candidates
    candidates = get_models_for_task(
        task_type=task_profile.primary_type,
        provider=preferred_provider,
        min_context=task_profile.context_size_estimate,
        require_vision=task_profile.requires_vision,
        require_tools=task_profile.requires_tools,
        max_cost_per_1k=max_cost,
        prefer_free=prefer_free,
    )

    if not candidates:
        # Fallback: any model that supports the task
        logger.warning(
            "No models match criteria for %s, trying fallback", task_profile.primary_type
        )
        candidates = get_models_for_task(
            task_type=task_profile.primary_type,
            require_vision=task_profile.requires_vision,
            require_tools=task_profile.requires_tools,
        )

    if candidates:
        best = candidates[0]
        logger.info(
            "Selected model %s for task %s (score: %.2f)",
            best.id,
            task_profile.primary_type.value,
            best.get_task_score(task_profile.primary_type),
        )
        return best

    logger.error("No suitable model found for task: %s", task_profile)
    return None


def get_model_registry_summary() -> list[dict]:
    """Get summary of all registered models for logging/debugging."""
    return [
        {
            "id": m.id,
            "provider": m.provider,
            "display_name": m.display_name,
            "context_window": m.context_window,
            "cost_input": str(m.cost_per_1k_input),
            "supports_tools": m.supports_tools,
            "supports_vision": m.supports_vision,
        }
        for m in _MODEL_REGISTRY.values()
    ]


def update_model_metrics(model_id: str, latency_ms: int, success: bool) -> None:
    """Update dynamic metrics for a model."""
    model = _MODEL_REGISTRY.get(model_id)
    if not model:
        return

    # Simple exponential moving average for latency
    if model.avg_latency_ms is None:
        model.avg_latency_ms = latency_ms
    else:
        model.avg_latency_ms = int(model.avg_latency_ms * 0.9 + latency_ms * 0.1)

    # Simple success rate tracking
    if model.success_rate_24h is None:
        model.success_rate_24h = 1.0 if success else 0.0
    else:
        model.success_rate_24h = model.success_rate_24h * 0.95 + (1.0 if success else 0.0) * 0.05


def clear_registry() -> None:
    """Clear all registered models. Useful for testing."""
    _MODEL_REGISTRY.clear()
