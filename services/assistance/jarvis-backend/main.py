"""jarvis-backend FastAPI application.

Endpoints
---------
GET  /health                  – liveness probe
POST /api/news_search         – direct news search (bypasses routing gate)
POST /api/dispatch            – route a text utterance to the matching skill
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from news_search import get_feed_list, search_news
from skills_router import SKILL_PATTERNS, is_routing_enabled, route

app = FastAPI(title="jarvis-backend", version="0.1.0")
logger = logging.getLogger("jarvis-backend")

PORT = int(os.getenv("PORT", "8018"))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "jarvis-backend",
        "skills_routing_enabled": is_routing_enabled(),
        "skill_count": len(SKILL_PATTERNS),
        "feed_count": len(get_feed_list()),
    }


# ---------------------------------------------------------------------------
# News search
# ---------------------------------------------------------------------------


class NewsSearchRequest(BaseModel):
    query: str
    max_articles: int = Field(default=10, ge=1, le=50)


@app.post("/api/news_search")
async def api_news_search(req: NewsSearchRequest) -> Dict[str, Any]:
    """Search RSS feeds for articles matching *query*.

    Feed URLs are configured via the ``NEWS_RSS_FEEDS`` environment variable
    (operator-controlled); callers cannot override them to prevent SSRF.

    Returns ``type: news_search_result`` with ``brief``, ``sources``,
    ``articles``, ``query``, and ``keywords``.
    """
    result = await search_news(req.query, max_articles=req.max_articles)
    return {"type": "news_search_result", **result}


# ---------------------------------------------------------------------------
# Dispatch (skills router)
# ---------------------------------------------------------------------------


class DispatchRequest(BaseModel):
    text: str


@app.post("/api/dispatch")
async def api_dispatch(req: DispatchRequest) -> Dict[str, Any]:
    """Route *text* to a skill handler and return the result.

    When ``SKILLS_ROUTING_ENABLED`` is off or no pattern matches, returns
    ``type: dispatch_fallthrough`` so callers can apply their own logic.
    """
    skill = route(req.text)
    if skill == "news_search":
        result = await search_news(req.text)
        return {"type": "news_search_result", "skill": skill, **result}
    return {"type": "dispatch_fallthrough", "text": req.text, "skill": None}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
