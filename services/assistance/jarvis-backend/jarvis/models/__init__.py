"""Jarvis model abstraction - task classification and intelligent model selection."""
from .tasks import TaskType, TaskProfile
from .registry import (
    ModelInfo,
    ModelCapability,
    register_model,
    get_models_for_task,
    get_best_model,
    get_model_registry_summary,
)
from .classifier import TaskClassifier
from .seed import seed_all_models

__all__ = [
    "TaskType",
    "TaskProfile",
    "ModelInfo",
    "ModelCapability",
    "register_model",
    "get_models_for_task",
    "get_best_model",
    "get_model_registry_summary",
    "TaskClassifier",
    "seed_all_models",
]
