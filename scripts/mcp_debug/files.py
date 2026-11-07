"""Structured read-only filesystem tools (mcp_files_{list,stat,search,tree}).

Each call vets the path against the per-host allowlist from
ssot.mcp-debug.files.yml (the same allowed_path_prefixes used by
mcp_get_file/mcp_put_file), then ships files_agent.py to the target host
over the existing run_on_host transport and returns its stable JSON
envelope. The remote agent re-verifies the allowlist after realpath
resolution, never descends into symlinks, and caps entries/depth/output.
"""
import base64
import json
import shlex
from pathlib import Path
from .config import HOSTS, FILE_CONFIG
from .hosts import run_on_host
from .tools import _check_path_allowed, _allowed_prefixes, _normalize_path

_AGENT_B64 = base64.b64encode(
    Path(__file__).with_name("files_agent.py").read_bytes()).decode()

_LIMITS = (FILE_CONFIG.get("files") or {}).get("limits") or {}
_LIM_DEFAULTS = {
    "max_entries": (500, 5000),
    "max_depth": (3, 12),
    "max_output_bytes": (196608, 524288),
    "max_errors": (50, 200),
}


def _lim(name, requested):
    cfg = _LIMITS.get(name) or {}
    default, hard = _LIM_DEFAULTS[name]
    default = int(cfg.get("default", default))
    hard = int(cfg.get("hard", hard))
    if requested is None:
        return default
    try:
        n = int(requested)
    except (TypeError, ValueError):
        return default
    return max(0, min(n, hard))


def _run_agent(host, op, path, params):
    tool = f"mcp_files_{op}"
    if host not in HOSTS:
        return {"ok": False, "tool": tool, "host": host,
                "error": f"unknown host: {host}",
                "available_hosts": list(HOSTS.keys())}
    allowed, err = _check_path_allowed(host, path)
    if err:
        return {"ok": False, "tool": tool, "host": host, "error": err,
                "path": path}
    roots = [r for r in (_normalize_path(p) for p in _allowed_prefixes(host)) if r]
    if not roots:
        return {"ok": False, "tool": tool, "host": host,
                "error": f"no allowed_path_prefixes configured for {host}"}

    payload = dict(params)
    payload["path"] = allowed
    payload["allowed_roots"] = roots
    payload["max_output_bytes"] = _lim("max_output_bytes",
                                       params.get("max_output_bytes"))
    payload["max_errors"] = _lim("max_errors", params.get("max_errors"))
    params_b64 = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()).decode()

    py = '"$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"'
    cmd = (f"printf %s {shlex.quote(_AGENT_B64)} | base64 -d | "
           f"{py} - {shlex.quote(op)} {shlex.quote(params_b64)}")
    result = run_on_host(host, cmd, compact=False, shell=True)
    if not result.get("ok"):
        err_text = (result.get("err") or "files agent failed").strip()
        return {"ok": False, "tool": tool, "host": host,
                "error": err_text[:500], "rc": result.get("rc")}
    out = (result.get("out") or "").strip()
    line = out.splitlines()[-1] if out else ""
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "tool": tool, "host": host,
                "error": "files agent output was not JSON",
                "out": out[:500]}
    if not isinstance(data, dict):
        return {"ok": False, "tool": tool, "host": host,
                "error": "files agent returned non-object JSON"}
    data["host"] = host
    data["tool"] = tool
    return data


def _fmt(fmt):
    return "rows" if fmt == "rows" else "objects"


def mcp_files_list(host, path, pattern=None, max_entries=None, sort="name",
                   order="asc", format="objects"):
    """One directory level: direct children of path."""
    return _run_agent(host, "list", path, {
        "pattern": pattern,
        "max_entries": _lim("max_entries", max_entries),
        "sort": sort, "order": order, "depth": 1, "format": _fmt(format),
    })


def mcp_files_stat(host, path, format="objects"):
    """Stat a single path; entries has exactly one item."""
    return _run_agent(host, "stat", path, {"format": _fmt(format)})


def mcp_files_search(host, path, pattern, depth=None, max_entries=None,
                     sort="name", order="asc", kind="any", format="objects"):
    """Recursive match of pattern under path, capped by depth/max_entries."""
    return _run_agent(host, "search", path, {
        "pattern": pattern,
        "depth": _lim("max_depth", depth),
        "max_entries": _lim("max_entries", max_entries),
        "sort": sort, "order": order, "kind": kind, "format": _fmt(format),
    })


def mcp_files_tree(host, path, depth=None, max_entries=None, sort="name",
                   order="asc", kind="any", pattern=None, format="objects"):
    """Pre-order tree walk under path with per-entry depth markers."""
    return _run_agent(host, "tree", path, {
        "pattern": pattern,
        "depth": _lim("max_depth", depth),
        "max_entries": _lim("max_entries", max_entries),
        "sort": sort, "order": order, "kind": kind, "format": _fmt(format),
    })
