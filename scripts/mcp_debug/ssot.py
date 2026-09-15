"""MCP Debug SSOT read/search helpers."""
import difflib
import json
import os
import re
import time
from pathlib import Path

import yaml

from .config import REPO_DIR


def _ssot_ref_constructor(loader, node):
    value = loader.construct_scalar(node)
    return {"__ref__": value}


yaml.SafeLoader.add_constructor("!ssot_ref", _ssot_ref_constructor)


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


def _value_to_string(value):
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _parse_ssot_args(inner):
    """Parse a string like '...path...', '...key...' and return (path, key)."""
    parts = re.findall(r'"([^"]*)"|\'([^\']*)\'', inner)
    args = [p[0] if p[0] else p[1] for p in parts]
    if len(args) != 2:
        return None
    return args[0], args[1]


def _parse_ref(ref):
    """Parse a __ref__ value, which may be a string 'path:key' or a dict."""
    if isinstance(ref, dict):
        path = ref.get("path") or ref.get("query")
        key = ref.get("key")
        if not path or not key:
            return None
        return path, key
    if isinstance(ref, str):
        if ":" not in ref:
            return None
        path, key = ref.rsplit(":", 1)
        return path, key
    return None


def _resolve_ref(path, key, stack, trace, fuzzy=False, context=0, limit=50):
    """Resolve one SSOT reference and recursively resolve its value."""
    try:
        p = _safe_path(path)
        if p is None:
            return {"value": None, "error": f"ref path is outside the repository: {path}", "trace": trace}
        if not p.exists():
            return {"value": None, "error": f"ref file not found: {path}", "trace": trace}
        resolved_path = str(p.relative_to(REPO_DIR))
        ref_key = (resolved_path, key)
        if ref_key in stack:
            return {"value": None, "error": f"circular SSOT reference: {ref_key}", "circular": True, "trace": trace}
        data = _load_yaml_cached(resolved_path)
        res = _navigate(data, key, fuzzy=fuzzy, context=context)
        if res["error"]:
            return {"value": None, "error": f"ref lookup failed for {resolved_path}:{key}: {res['error']}", "trace": trace}
        value = res["value"]
        trace.append({"path": resolved_path, "key": key, "type": type(value).__name__})
        new_stack = stack | {ref_key}
        return _resolve_value(value, stack=new_stack, trace=trace, fuzzy=fuzzy, context=context, limit=limit)
    except Exception as e:
        return {"value": None, "error": f"ref error for {path}:{key}: {e}", "trace": trace}


def _interpolate_ssot(value, stack, trace, fuzzy=False, context=0, limit=50):
    pattern = re.compile(r'\$\{ssot\(([^)]*)\)\}')
    parts = []
    pos = 0
    for m in pattern.finditer(value):
        parts.append(value[pos:m.start()])
        target = _parse_ssot_args(m.group(1))
        if not target:
            return None, f"invalid ssot expression: {m.group(0)}"
        res = _resolve_ref(target[0], target[1], stack, trace, fuzzy=fuzzy, context=context, limit=limit)
        if res.get("error"):
            return None, res["error"]
        parts.append(_value_to_string(res["value"]))
        pos = m.end()
    parts.append(value[pos:])
    return "".join(parts), None


def _resolve_value(value, stack=None, trace=None, fuzzy=False, context=0, limit=50):
    if trace is None:
        trace = []
    if stack is None:
        stack = set()

    if isinstance(value, dict) and "__ref__" in value:
        target = _parse_ref(value["__ref__"])
        if not target:
            return {"value": value, "error": "invalid __ref__ value", "trace": trace}
        return _resolve_ref(target[0], target[1], stack, trace, fuzzy=fuzzy, context=context, limit=limit)

    if isinstance(value, str):
        m = re.fullmatch(r'\$\{ssot\(([^)]*)\)\}', value)
        if m:
            target = _parse_ssot_args(m.group(1))
            if not target:
                return {"value": value, "error": f"invalid ssot expression: {value}", "trace": trace}
            return _resolve_ref(target[0], target[1], stack, trace, fuzzy=fuzzy, context=context, limit=limit)
        if "${ssot(" in value:
            resolved, error = _interpolate_ssot(value, stack, trace, fuzzy=fuzzy, context=context, limit=limit)
            if error:
                return {"value": value, "error": error, "trace": trace}
            return {"value": resolved, "error": None, "trace": trace}

    return {"value": value, "error": None, "trace": trace}


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


def mcp_query_ssot(query=None, path=None, key=None, limit=50, fuzzy=False, context=0, resolve=True, trace=False):
    """Find an SSOT document and return a specific value or list at a dotted/integer path.

    If resolve=True, values that are __ref__ objects, !ssot_ref tags, or ${ssot(...)}
    expressions are resolved by looking up the referenced SSOT value. Circular
    references are detected and reported. If trace=True, the resolution chain is
    included in the response and in the usage log.
    """
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
        _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context, "resolve": resolve, "trace": trace}, False, result)
        return result

    res = _navigate(data, key, fuzzy=fuzzy, context=context)
    value = res["value"]
    error = res["error"]
    info = res["info"]

    if error:
        result = {"ok": False, "error": error, "path": resolved_path, "key": key}
        result.update(info)
        _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context, "resolve": resolve, "trace": trace}, False, result)
        return result

    resolved_trace = []
    if resolve:
        r = _resolve_value(value, fuzzy=fuzzy, context=context, limit=limit)
        if r.get("error"):
            result = {
                "ok": False,
                "error": r["error"],
                "path": resolved_path,
                "key": key,
            }
            if trace:
                result["resolved_trace"] = r.get("trace", [])
            result.update(info)
            _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context, "resolve": resolve, "trace": trace}, False, result)
            return result
        value = r["value"]
        resolved_trace = r.get("trace", [])

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
    if resolve and resolved_trace:
        result["resolved"] = True
        if trace:
            result["resolved_trace"] = resolved_trace
    elif resolve:
        result["resolved"] = False
    result.update(info)
    _log_usage("mcp_query_ssot", {"query": query, "path": path, "key": key, "fuzzy": fuzzy, "context": context, "resolve": resolve, "trace": trace}, True, result)
    return result
