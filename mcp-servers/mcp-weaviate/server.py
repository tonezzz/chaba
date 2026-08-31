#!/usr/bin/env python3
"""mcp-weaviate — FastMCP wrapper for the Weaviate hybrid search API.

Calls the local Weaviate search API (port 3002) which embeds queries and
performs hybrid BM25 + vector search over the SSOTDocument collection.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-weaviate")

SEARCH_URL = os.environ.get("WEAVIATE_SEARCH_URL", "http://localhost:3002").rstrip("/")


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{SEARCH_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict[str, Any]:
    url = f"{SEARCH_URL}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool()
def search_kb(
    query: str,
    limit: int = 10,
    type: str = "",
    category: str = "",
) -> str:
    """Semantic search over the KB/SSOT knowledge base.

    Uses hybrid BM25 + vector search with all-MiniLM-L6-v2 embeddings.

    Args:
        query: Natural language search query.
        limit: Max results to return (default 10, max 50).
        type: Optional filter by document type: ssot, kb, docs, architecture, session.
        category: Optional filter by category: infrastructure, apps, sessions, etc.

    Returns:
        JSON array of matching documents with title, path, type, similarity score,
        content snippet, and tags.
    """
    if not query or not query.strip():
        return json.dumps({"error": "query is required"})

    filters: dict[str, str] = {}
    if type:
        filters["type"] = type
    if category:
        filters["category"] = category

    try:
        payload: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 50),
            "filters": filters,
        }
        return json.dumps(_post("/search", payload), ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as exc:
        return json.dumps({
            "error": f"Search API HTTP {exc.code}",
            "body": exc.read().decode("utf-8", errors="replace")[:500],
            "search_url": SEARCH_URL,
        })
    except Exception as exc:
        return json.dumps({"error": str(exc), "search_url": SEARCH_URL})


@mcp.tool()
def search_kb_status() -> str:
    """Check health of the Weaviate search service."""
    try:
        return json.dumps(_get("/health"))
    except urllib.error.URLError as e:
        return json.dumps({"error": str(e), "search_url": SEARCH_URL})


if __name__ == "__main__":
    mcp.run(transport="stdio")
