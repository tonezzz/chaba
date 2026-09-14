"""MCP Debug SSOT read/search helpers."""
import difflib
import json
import os
import time
from pathlib import Path

import yaml

from .config import REPO_DIR


_SSOT_PARSED_CACHE = {}


def _safe_path(path):
    p = Path(path) if os.path.isabs(path) else REPO_DIR / path
    try:
        p.relative_to(REPO_DIR)
    except ValueError:
        return None
    return p


def _load_yaml_cached(path):
    """Load and cache parsed SSOT YAML, keyed by mtime."""
    p = _safe_path(path)
    if p is None:
        raise ValueError("path is outside the repository")
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    cache_key = str(p)
    mtime = p.stat().st_mtime
    cached = _SSOT_PARSED_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(p) as f:
        data = yaml.safe_load(f) or {}
    _SSOT_PARSED_CACHE[cache_key] = (mtime, data)
    return data


_USAGE_LOG = REPO_DIR / "data" / "mcp-usage.ndjson"
_USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)


def _log_usage(tool, kwargs, ok, result):
    try:
        val = result.get("value") if isinstance(result, dict) else result
        row = {
            "ts": time.time(),
            "tool": tool,
            "query": kwargs.get("query"),
            "path": kwargs.get("path"),
            "key": kwargs.get("key"),
            "fuzzy": kwargs.get("fuzzy"),
            "context": kwargs.get("context"),
            "ok": ok,
            "result_type": result.get("type") if isinstance(result, dict) else type(result).__name__,
            "result_len": len(str(val)),
            "error": result.get("error") if isinstance(result, dict) else None,
        }
        with open(_USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


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


def _navigate_wildcard(current, rest, fuzzy=False):
    if not isinstance(current, (dict, list)):
        return {
            "value": None,
            "error": "cannot apply wildcard to a non-container",
            "info": {},
        }
    rest_key = ".".join(rest)
    if isinstance(current, dict):
        if not rest:
            return {"value": current, "error": None, "info": {"wildcard": True}}
        collected = {}
        for k, v in current.items():
            res = _navigate(v, rest_key, fuzzy=fuzzy)
            if not res["error"]:
                collected[k] = res["value"]
        if not collected:
            return {
                "value": None,
                "error": f"wildcard path produced no matches for '{rest_key}'",
                "info": {"wildcard": True},
            }
        return {"value": collected, "error": None, "info": {"wildcard": True}}
    else:
        if not rest:
            return {"value": current, "error": None, "info": {"wildcard": True}}
        collected = []
        for v in current:
            res = _navigate(v, rest_key, fuzzy=fuzzy)
            collected.append(res["value"] if not res["error"] else None)
        return {"value": collected, "error": None, "info": {"wildcard": True}}


def _navigate(data, key, fuzzy=False, context=0):
    if not key:
        return {"value": data, "error": None, "info": {}}
    parts = [p for p in key.split(".") if p]
    current = data
    parent_stack = []
    fuzzy_parts = []
    for i, part in enumerate(parts):
        if context > 0:
            parent_stack.append(current)
        if part == "*":
            rest = parts[i + 1:]
            return _navigate_wildcard(current, rest, fuzzy=fuzzy)
        if isinstance(current, list):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return {
                    "value": None,
                    "error": f"invalid list index '{part}' at key '{key}'",
                    "info": {},
                }
        elif isinstance(current, dict):
            if part not in current:
                suggestions = difflib.get_close_matches(part, current.keys(), n=3, cutoff=0.6)
                if fuzzy and suggestions:
                    resolved = suggestions[0]
                    fuzzy_parts.append({"original": part, "resolved": resolved})
                    part = resolved
                    current = current[part]
                else:
                    info = {"suggestions": suggestions}
                    if context > 0 and parent_stack:
                        ctx_idx = min(context, len(parent_stack))
                        info["context_path"] = ".".join(parts[:max(0, len(parts) - context)])
                        info["context_value"] = parent_stack[-ctx_idx]
                    return {
                        "value": None,
                        "error": f"key '{part}' not found at '{key}'",
                        "info": info,
                    }
            else:
                current = current[part]
        else:
            return {
                "value": None,
                "error": f"cannot traverse into non-container at '{part}'",
                "info": {},
            }
    info = {}
    if fuzzy_parts:
        info["fuzzy"] = True
        info["fuzzy_parts"] = fuzzy_parts
    if context > 0 and parent_stack:
        ctx_idx = min(context, len(parent_stack))
        info["context_path"] = ".".join(parts[:max(0, len(parts) - context)])
        info["context_value"] = parent_stack[-ctx_idx]
    return {"value": current, "error": None, "info": info}


def mcp_query_ssot(query=None, path=None, key=None, limit=50, fuzzy=False, context=0):
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

    try:
        data = _load_yaml_cached(resolved_path)
    except Exception as e:
        result = {"ok": False, "error": str(e), "path": resolved_path, "key": key}
        _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context}, False, result)
        return result

    res = _navigate(data, key, fuzzy=fuzzy, context=context)
    value = res["value"]
    error = res["error"]
    info = res["info"]

    if error:
        result = {"ok": False, "error": error, "path": resolved_path, "key": key}
        result.update(info)
        _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context}, False, result)
        return result

    result_type = type(value).__name__
    truncated = False
    if isinstance(value, list):
        n = len(value)
        if n > limit:
            value = value[:limit]
            truncated = True
        result = {
            "ok": True,
            "path": resolved_path,
            "key": key,
            "type": "list",
            "n": n,
            "returned": len(value),
            "truncated": truncated,
            "value": value,
        }
    else:
        result = {
            "ok": True,
            "path": resolved_path,
            "key": key,
            "type": result_type,
            "value": value,
        }
    result.update(info)
    _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context}, True, result)
    return result
