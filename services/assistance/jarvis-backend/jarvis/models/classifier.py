"""Task classification from user intent."""
from __future__ import annotations

import re

from .tasks import TaskProfile, TaskType


class TaskClassifier:
    """Classify user intent to select appropriate task type."""

    # Keyword patterns for each task type
    PATTERNS: dict[TaskType, list[str]] = {
        TaskType.CODE: [
            r"\b(code|program|function|debug|error|bug|compile|syntax|python|javascript|typescript|java|go|rust|c\+\+|php)\b",
            r"\b(write|create)\b.*\b(script|app|program|function|class|method)\b",
            r"\bfix\b.*\b(error|bug|issue|problem|exception)\b",
            r"\brefactor|optimize|review\b.*\bcode\b",
        ],
        TaskType.REASONING: [
            r"\b(why|how|explain|analyze|compare|evaluate|solve|calculate|math|logic|reason|deduce|infer)\b",
            r"\b(step by step|reasoning|think through|work out|prove|demonstrate)\b",
            r"\bwhat if|hypothetically|consider the following\b",
        ],
        TaskType.CREATIVE: [
            r"\b(write|create|generate|craft|compose|author)\b.*\b(story|poem|essay|article|blog|draft|script|dialogue)\b",
            r"\b(imagine|creative|fiction|scenario|idea|brainstorm|concept)\b",
            r"\bhelp me write|can you write|write a\b",
        ],
        TaskType.SUMMARIZATION: [
            r"\b(summarize|summary|tl;dr|tldr|condense|brief overview|executive summary)\b",
            r"\b(key points|main ideas|in short|in brief|give me the gist|bottom line)\b",
            r"\bwhat are the main|highlights of|takeaways from\b",
        ],
        TaskType.EXTRACTION: [
            r"\b(extract|parse|get|pull|find|scrape|harvest|gather)\b.*\b(data|information|values|fields|entities)\b",
            r"\b(json|csv|structured|table|format|schema)\b.*\b(output|result|data)\b",
            r"\bconvert to|transform into|output as\b.*\b(json|csv|xml|yaml)\b",
        ],
        TaskType.VISION: [
            r"\b(image|picture|photo|screenshot|diagram|chart|graph|figure|plot)\b",
            r"\b(describe.*image|what.*see|what.*in.*this|analyze.*image|look at this)\b",
            r"\bwhat is in|what does this show|interpret this\b",
        ],
        TaskType.TOOL_USE: [
            r"\b(list tools|what can you do|available tools|tool list|your capabilities)\b",
            r"\b(use tool|call function|execute|run command|perform action)\b",
            r"\btime now|current time|what time|what day|what date|today's date\b",
            r"\b(add memo|save memo|remember this|write that down|take a note)\b",
            r"\b(search|look up|find information|get data|fetch|retrieve)\b",
            r"\b(check status|get status|is it working|health check)\b",
        ],
        TaskType.MEMORY: [
            r"\b(remember|recall|what did|what was|you said earlier|previous conversation)\b",
            r"\b(my preference|my setting|as I mentioned|like I told you)\b",
        ],
    }

    def classify(self, text: str, has_attachment: bool = False) -> TaskProfile:
        """Classify user text into task profile."""

        text_lower = text.lower()
        scores: dict[TaskType, float] = {}

        # Pattern matching
        for task_type, patterns in self.PATTERNS.items():
            score = 0.0
            for pattern in patterns:
                matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
                score += matches * 0.5  # Each match adds to score
            scores[task_type] = min(score, 1.0)  # Cap at 1.0

        # Vision boost if attachment present
        if has_attachment:
            scores[TaskType.VISION] = scores.get(TaskType.VISION, 0) + 0.8

        # Default chat score if nothing else matches
        if not scores or max(scores.values()) < 0.3:
            scores[TaskType.CHAT] = 0.7

        # Determine primary type
        primary = max(scores, key=scores.get)
        confidence = min(scores.get(primary, 0.5), 1.0)

        # Estimate complexity
        complexity = self._estimate_complexity(text)

        # Estimate context needs
        context_size = self._estimate_context(text)

        # Determine latency preference
        if primary == TaskType.CHAT:
            preferred_latency = "fast"
        elif primary in (TaskType.REASONING, TaskType.CODE):
            preferred_latency = "slow_ok"
        else:
            preferred_latency = "normal"

        return TaskProfile(
            primary_type=primary,
            confidence=confidence,
            complexity=complexity,
            requires_vision=has_attachment or primary == TaskType.VISION,
            requires_tools=primary == TaskType.TOOL_USE
            or scores.get(TaskType.TOOL_USE, 0) > 0.3,
            context_size_estimate=context_size,
            preferred_latency=preferred_latency,
        )

    def _estimate_complexity(self, text: str) -> str:
        """Estimate task complexity."""
        word_count = len(text.split())
        code_indicators = len(re.findall(r"[{}();=+\-*/]", text))
        reasoning_indicators = len(
            re.findall(r"\b(why|how|explain|analyze|compare|evaluate)\b", text, re.I)
        )

        if word_count > 500 or code_indicators > 50 or reasoning_indicators > 5:
            return "high"
        elif word_count > 100 or code_indicators > 20 or reasoning_indicators > 2:
            return "medium"
        return "low"

    def _estimate_context(self, text: str) -> int:
        """Estimate tokens needed."""
        # Rough estimate: 1 token ≈ 4 characters for English
        # Thai/Unicode: 1 token ≈ 2-3 characters
        chars = len(text)
        # Conservative estimate
        estimated_tokens = min(chars // 2, 100_000)  # Cap at 100K
        # Add buffer for response
        return min(estimated_tokens * 2, 200_000)

    def classify_quick(self, text: str) -> TaskType:
        """Quick classification returning just the task type."""
        return self.classify(text).primary_type
