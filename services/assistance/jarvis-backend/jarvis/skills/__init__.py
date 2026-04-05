"""
Skills module for Jarvis AI assistant.
"""

from .news import NewsSkill

# Create an alias for backward compatibility
current_news_skill = NewsSkill()

__all__ = ["NewsSkill", "current_news_skill"]