"""API endpoints for model management and task classification."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from jarvis.models import (
    TaskClassifier,
    get_model_registry_summary,
    get_models_for_task,
    get_best_model,
)
from jarvis.models.tasks import TaskType
from jarvis.providers.smart import get_smart_provider

router = APIRouter()


class ClassifyRequest(BaseModel):
    text: str
    has_attachment: bool = False


class ClassifyResponse(BaseModel):
    task_type: str
    confidence: float
    complexity: str
    requires_vision: bool
    requires_tools: bool


class SelectModelRequest(BaseModel):
    text: str
    has_attachment: bool = False
    budget_tier: str = "auto"  # free, cheap, standard, premium, auto
    preferred_provider: str | None = None


class SelectModelResponse(BaseModel):
    model_id: str
    provider: str
    display_name: str
    context_window: int
    cost_per_1k_input: str
    task_type: str
    task_confidence: float


@router.get("/models", response_model=list[dict[str, Any]])
async def list_models():
    """List all registered models with capabilities."""
    return get_model_registry_summary()


@router.get("/models/free")
async def list_free_models():
    """List free models only."""
    all_models = get_model_registry_summary()
    free_models = [m for m in all_models if m["cost_input"] == "0"]
    return {
        "count": len(free_models),
        "models": free_models,
    }


@router.post("/models/classify", response_model=ClassifyResponse)
async def classify_task(request: ClassifyRequest):
    """Classify user text into task type."""
    classifier = TaskClassifier()
    profile = classifier.classify(request.text, request.has_attachment)

    return ClassifyResponse(
        task_type=profile.primary_type.value,
        confidence=profile.confidence,
        complexity=profile.complexity,
        requires_vision=profile.requires_vision,
        requires_tools=profile.requires_tools,
    )


@router.post("/models/select", response_model=SelectModelResponse)
async def select_model_for_task(request: SelectModelRequest):
    """Select best model for a given task."""
    smart = get_smart_provider()

    model_id, provider, task = smart.select_model(
        request.text,
        has_attachment=request.has_attachment,
        preferred_provider=request.preferred_provider,
        force_budget_tier=request.budget_tier if request.budget_tier != "auto" else None,
    )

    # Get full model info
    from jarvis.models.registry import get_model
    model_info = get_model(model_id)

    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")

    return SelectModelResponse(
        model_id=model_id,
        provider=provider,
        display_name=model_info.display_name,
        context_window=model_info.context_window,
        cost_per_1k_input=str(model_info.cost_per_1k_input),
        task_type=task.primary_type.value,
        task_confidence=task.confidence,
    )


@router.get("/models/for-task/{task_type}")
async def get_models_for_task_type(
    task_type: str,
    provider: str | None = None,
    budget: str = "auto",
):
    """Get models ranked for a specific task type."""
    try:
        task_enum = TaskType(task_type)
    except ValueError:
        valid = [t.value for t in TaskType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type. Valid: {valid}"
        )

    # Determine cost limit from budget
    from decimal import Decimal
    max_cost = None
    if budget == "free":
        max_cost = Decimal("0")
    elif budget == "cheap":
        max_cost = Decimal("0.001")
    elif budget == "standard":
        max_cost = Decimal("0.01")

    models = get_models_for_task(
        task_type=task_enum,
        provider=provider,
        max_cost_per_1k=max_cost,
    )

    return {
        "task_type": task_type,
        "budget": budget,
        "count": len(models),
        "models": [
            {
                "id": m.id,
                "display_name": m.display_name,
                "provider": m.provider,
                "task_score": m.get_task_score(task_enum),
                "cost_input": str(m.cost_per_1k_input),
                "supports_tools": m.supports_tools,
                "supports_vision": m.supports_vision,
            }
            for m in models[:10]  # Top 10
        ],
    }
