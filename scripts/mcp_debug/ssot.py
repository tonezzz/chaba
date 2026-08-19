"""MCP Debug SSOT read/search helpers."""
import os
from pathlib import Path

import yaml

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


MDDB_BASE = os.environ.get("MDDB_BASE_URL", "http://tony-dell:11023")


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


def _meta_list(meta, key):
    if not meta:
        return None
    value = meta.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def mcp_search_ssot(query=None, collection="ssot-infrastructure", limit=5):
    if not query:
        return {"ok": False, "error": "query is required"}

    source = "mddb"
    mddb = _mddb_search(query, collection=collection, limit=limit)
    results = []
    if mddb and mddb.get("results"):
        for r in mddb.get("results")[:limit]:
            doc = r.get("document") or {}
            meta = doc.get("meta") or {}
            original = _meta_list(meta, "original_path") or doc.get("key", "")
            if original and not original.startswith("docs/"):
                original = f"docs/ssot/{original}"
            content = doc.get("contentMd") or doc.get("content", "")
            title = _meta_list(meta, "title") or ""
            excerpt = (content[:200] if content else title[:200])
            results.append({
                "path": original,
                "excerpt": excerpt,
                "source": "mddb",
            })

    if not results:
        results = _local_ssot_search(query, limit=limit)
        source = "local"

    return {"ok": True, "query": query, "source": source, "results": results}


def mcp_mddb_doc(query=None, collection="ssot-infrastructure", top_k=1, read_limit=20000):
    """Find the most relevant SSOT document with MDDB and return its full content."""
    if not query:
        return {"ok": False, "error": "query is required"}
    search = mcp_search_ssot(query=query, collection=collection, limit=top_k)
    if not search.get("ok") or not search.get("results"):
        return {"ok": False, "error": "no matching document found"}
    docs = []
    for r in search.get("results")[:top_k]:
        path = r.get("path")
        if not path:
            continue
        read = mcp_read_ssot(path=path, limit=read_limit)
        docs.append({
            "path": path,
            "excerpt": r.get("excerpt", ""),
            "source": r.get("source", "local"),
            "content": read.get("content") if read.get("ok") else None,
            "truncated": read.get("truncated", False) if read.get("ok") else None,
            "read_error": None if read.get("ok") else read.get("error"),
        })
    return {
        "ok": True,
        "query": query,
        "source": search.get("source", "local"),
        "n": len(docs),
        "docs": docs,
    }


def _navigate(data, key):
    if not key:
        return data, None
    parts = [p for p in key.split(".") if p]
    current = data
    for part in parts:
        if isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return None, f"invalid list index '{part}' at key '{key}'"
        elif isinstance(current, dict):
            if part not in current:
                return None, f"key '{part}' not found at '{key}'"
            current = current[part]
        else:
            return None, f"cannot traverse into non-container at '{part}'"
    return current, None


def mcp_query_ssot(query=None, path=None, key=None, limit=50):
    """Find an SSOT document and return a specific value or list at a dotted/integer path."""
    if not query and not path:
        return {"ok": False, "error": "query or path is required"}

    resolved_path = path
    if not resolved_path:
        search = mcp_search_ssot(query=query, collection="ssot-infrastructure", limit=1)
        if not search.get("ok") or not search.get("results"):
            return {"ok": False, "error": "no matching document found"}
        resolved_path = search["results"][0].get("path")

    if not resolved_path:
        return {"ok": False, "error": "could not resolve document path"}

    read = mcp_read_ssot(path=resolved_path, limit=100000)
    if not read.get("ok"):
        return {"ok": False, "error": read.get("error", "failed to read SSOT")}

    try:
        data = yaml.safe_load(read["content"])
    except Exception as e:
        return {"ok": False, "error": f"YAML parse error: {e}"}

    value, error = _navigate(data, key)
    if error:
        return {"ok": False, "error": error, "path": resolved_path, "key": key}

    result_type = type(value).__name__
    truncated = False
    if isinstance(value, list):
        n = len(value)
        if n > limit:
            value = value[:limit]
            truncated = True
        return {
            "ok": True,
            "path": resolved_path,
            "key": key,
            "type": "list",
            "n": n,
            "returned": len(value),
            "truncated": truncated,
            "value": value,
        }

    return {
        "ok": True,
        "path": resolved_path,
        "key": key,
        "type": result_type,
        "value": value,
    }
