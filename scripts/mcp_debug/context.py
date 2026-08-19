"""MCP Debug context/session summary wrappers."""
import json
import subprocess
import sys
from pathlib import Path

from .config import REPO_DIR


def _run_script(name, *args):
    script = REPO_DIR / "scripts" / name
    if not script.exists():
        return {"ok": False, "error": f"script not found: {script}"}
    try:
        result = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            cwd=REPO_DIR,
            timeout=30,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr or f"{name} exited {result.returncode}"}
        return json.loads(result.stdout)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def mcp_context(query=None, top_k=10):
    """Return relevant KB/SSOT files for the active focus and optional query."""
    args = []
    if query:
        args.append(str(query))
    result = _run_script("mcp_context.py", *args)
    if not result.get("ok"):
        return result
    # Limit results to top_k
    for k in ("kb", "ssot"):
        if k in result:
            result[k] = result[k][:top_k]
    result["top_k"] = top_k
    return result


def mcp_session_summary():
    """Return a structured summary of the active focus and recent sessions."""
    return _run_script("mcp_session_summary.py")
