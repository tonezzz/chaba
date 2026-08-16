"""MCP Debug SSOT read/search helpers."""
import os
from pathlib import Path

from .config import REPO_DIR


def _safe_path(path):
    p = Path(path) if os.path.isabs(path) else REPO_DIR / path
    try:
        p.relative_to(REPO_DIR)
    except ValueError:
        return None
    return p


def mcp_read_ssot(path=None, limit=20000):
    if not path:
        return {"ok": False, "error": "path is required"}
    p = _safe_path(path)
    if p is None:
        return {"ok": False, "error": "path is outside the repository"}
    if not p.exists():
        return {"ok": False, "error": f"file not found: {p.relative_to(REPO_DIR)}"}
    try:
        with open(p) as f:
            content = f.read()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    truncated = len(content) > limit
    if truncated:
        content = content[:limit]
    return {
        "ok": True,
        "path": str(p.relative_to(REPO_DIR)),
        "content": content,
        "truncated": truncated,
    }


MDDB_BASE = os.environ.get("MDDB_BASE_URL", "http://tony-omen.local:11023")


def _mddb_search(query, collection="ssot-infrastructure", limit=5):
    try:
        import json as _json
        from urllib import request, error
        payload = _json.dumps({
            "query": query,
            "limit": limit,
            "collection": collection,
        }).encode()
        req = request.Request(
            f"{MDDB_BASE}/v1/vector-search",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        return data
    except Exception:
        return None


def _excerpt(text, keyword, window=80):
    low = text.lower()
    pos = low.find(keyword.lower())
    if pos == -1:
        return text[:window * 2]
    start = max(0, pos - window)
    end = min(len(text), pos + len(keyword) + window)
    return text[start:end]


def _local_ssot_search(query, limit=10):
    keywords = [k for k in query.lower().split() if k]
    if not keywords:
        return []
    results = []
    for p in sorted((REPO_DIR / "docs" / "ssot").rglob("*.yml")):
        try:
            with open(p) as f:
                text = f.read()
        except Exception:
            continue
        low = text.lower()
        if all(k in low for k in keywords):
            excerpt = _excerpt(text, keywords[0])
            results.append({
                "path": str(p.relative_to(REPO_DIR)),
                "excerpt": excerpt,
                "source": "local",
            })
            if len(results) >= limit:
                break
    return results


def mcp_search_ssot(query=None, collection="ssot-infrastructure", limit=5):
    if not query:
        return {"ok": False, "error": "query is required"}

    source = "mddb"
    mddb = _mddb_search(query, collection=collection, limit=limit)
    results = []
    if mddb and mddb.get("results"):
        for r in mddb.get("results")[:limit]:
            results.append({
                "path": r.get("key") or r.get("path") or r.get("source"),
                "excerpt": r.get("excerpt") or r.get("content_md", "")[:200],
                "source": "mddb",
            })

    if not results:
        results = _local_ssot_search(query, limit=limit)
        source = "local"

    return {"ok": True, "query": query, "source": source, "results": results}
