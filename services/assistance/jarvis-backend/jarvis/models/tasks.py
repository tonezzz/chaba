"""Task classification for model selection."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskType(Enum):
    """Classification of user intent for model selection."""

    CHAT = "chat"  # Casual conversation, simple Q&A
    CODE = "code"  # Programming, debugging, generation
    REASONING = "reasoning"  # Complex problem solving, math, logic
    CREATIVE = "creative"  # Writing, storytelling, ideation
    SUMMARIZATION = "summarization"  # Condense long text
    EXTRACTION = "extraction"  # Structured data extraction
    VISION = "vision"  # Image understanding/analysis
    VOICE = "voice"  # Voice conversation (low latency)
    TOOL_USE = "tool_use"  # Heavy function calling
    MEMORY = "memory"  # Long context, recall


@dataclass
class TaskProfile:
    """Detected task characteristics."""

    primary_type: TaskType
    confidence: float  # 0-1 classification confidence
    complexity: str  # "low", "medium", "high"
    requires_vision: bool
    requires_tools: bool
    context_size_estimate: int  # estimated tokens needed
    preferred_latency: str  # "fast", "normal", "slow_ok"

    def __repr__(self) -> str:
        return (
            f"TaskProfile({self.primary_type.value}, "
            f"confidence={self.confidence:.2f}, "
            f"complexity={self.complexity})"
        )
