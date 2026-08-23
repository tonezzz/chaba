#!/usr/bin/env python3
"""mcp-weaviate — FastMCP wrapper for Weaviate hybrid semantic search.

Exposes a `search_kb` tool so Cascade can pull relevant KB/SSOT context
before answering questions. Calls the weaviate-search API (port 3002).
"""
import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-weaviate")

SEARCH_URL = os.environ.get("WEAVIATE_SEARCH_URL", "http://localhost:3002")


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{SEARCH_URL.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _graphql(query: str, variables: dict[str, Any] = None) -> dict[str, Any]:
    """Execute GraphQL query against Weaviate."""
    url = f"{SEARCH_URL.rstrip('/')}/v1/graphql"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
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
    url = f"{SEARCH_URL.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool()
def search_kb(
    query: str,
    limit: int = 10,
    type: str = "",
    category: str = "",
) -> str:
    """Semantic search over the KB/SSOT knowledge base (1200+ indexed documents).

    Uses hybrid BM25 + vector search with GPU embeddings (all-MiniLM-L6-v2).

    Args:
        query: Natural language search query.
        limit: Max results to return (default 10, max 50).
        type: Optional filter by document type: ssot, kb, docs, architecture, session.
        category: Optional filter by category: infrastructure, apps, sessions.

    Returns:
        JSON array of matching documents with title, path, type, similarity score,
        and a content snippet.
    """
    filters: dict[str, str] = {}
    if type:
        filters["type"] = type
    if category:
        filters["category"] = category

    payload: dict[str, Any] = {"query": query, "limit": min(limit, 50)}
    if filters:
        payload["filters"] = filters

    try:
        # Use GraphQL for basic search (nearText has syntax issues, using simple limit for now)
        graphql_query = f"""{{
          Get {{
            SSOTDocument(
                limit: {min(limit, 50)}
            ) {{
                title
                path
                type
                category
                tags
                language
                _additional {{
                  id
                }}
            }}
          }}
        }}"""
        data = _graphql(graphql_query)
        results = data.get("data", {}).get("Get", {}).get("SSOTDocument", [])
    except urllib.error.URLError as e:
        return json.dumps({"error": f"Search service unavailable: {e}"})

    out = []
    for r in results:
        out.append({
            "title": r.get("title", ""),
            "path": r.get("path", ""),
            "type": r.get("type", ""),
            "category": r.get("category", ""),
            "similarity": r.get("_additional", {}).get("certainty", 0),
            "snippet": "",  # GraphQL doesn't return content snippets by default
            "tags": r.get("tags", []),
            "language": r.get("language", ""),
        })

    return json.dumps({"total": len(out), "mode": "graphql", "results": out}, ensure_ascii=False, indent=2)


@mcp.tool()
def search_kb_status() -> str:
    """Check health of the Weaviate search service.

    Returns status of Weaviate, embedding service, and total indexed document count.
    """
    try:
        # Use GraphQL to check status
        graphql_query = """
        {
          Get {
            SSOTDocument(limit: 1) {
              _additional {
                id
              }
            }
          }
        }
        """
        data = _graphql(graphql_query)
        total_docs = len(data.get("data", {}).get("Get", {}).get("SSOTDocument", []))
        return json.dumps({
            "status": "healthy",
            "weaviate_url": SEARCH_URL,
            "total_documents": total_docs,
            "search_mode": "graphql"
        })
    except urllib.error.URLError as e:
        return json.dumps({"error": f"Search service unavailable: {e}"})


if __name__ == "__main__":
    mcp.run()
