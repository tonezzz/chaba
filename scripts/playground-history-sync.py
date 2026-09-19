#!/usr/bin/env python3
"""Fetch the live AI Playground history export and stage it for NotebookLM sync."""
import subprocess
import sys
from pathlib import Path

REPO = Path.home() / "CascadeProjects" / "chaba"
OUT = REPO / "data" / "kb" / "playground-history.md"
URL = "https://tony-dell.taila0626a.ts.net/apps/dev/v0/api/history/export"

OUT.parent.mkdir(parents=True, exist_ok=True)

try:
    result = subprocess.run(
        ["curl", "-sS", "-f", "-k", URL],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        print(f"fetch failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    OUT.write_text(result.stdout, encoding="utf-8")
    print(f"wrote {OUT} ({len(result.stdout)} bytes)")
except Exception as e:
    print(f"error: {e}", file=sys.stderr)
    sys.exit(1)
