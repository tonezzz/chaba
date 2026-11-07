#!/usr/bin/env python3
"""FastMCP adapter for deterministic Gaussian capture evaluation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

SCRIPT = Path(__file__).parents[2] / "scripts" / "gs" / "image_set_eval.py"
sys.path.insert(0, str(SCRIPT.parent))
from image_set_eval import evaluate  # noqa: E402

mcp = FastMCP("mcp-kornia")


@mcp.tool()
def inspect_image_set(image_dir: str) -> str:
    """Evaluate a local image set for Gaussian Splat capture readiness.

    Read-only. Returns dimensions, duplicate hashes, luma statistics,
    deterministic sharpness, gates, and a recommendation.
    """
    root = Path(image_dir).expanduser().resolve()
    if not root.is_dir():
        return json.dumps({"error": f"not a directory: {root}"})
    return json.dumps(evaluate(root), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
