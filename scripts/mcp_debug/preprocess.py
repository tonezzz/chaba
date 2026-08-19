"""MCP Debug prompt preprocessor wrapper."""
import json
import subprocess
import sys

from .config import REPO_DIR


def mcp_preprocess(request=None):
    """Run prompt_preprocessor.py on the request and return the structured result."""
    if not request:
        return {"ok": False, "error": "request is required"}
    try:
        result = subprocess.run(
            [sys.executable, str(REPO_DIR / "scripts" / "prompt_preprocessor.py"), request],
            capture_output=True,
            text=True,
            cwd=REPO_DIR,
            timeout=30,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr or f"preprocessor exited {result.returncode}"}
        return json.loads(result.stdout)
    except Exception as e:
        return {"ok": False, "error": str(e)}
