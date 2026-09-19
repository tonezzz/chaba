#!/usr/bin/env python3
"""Query a specific NotebookLM source by title pattern."""
import argparse
import os
import subprocess
from pathlib import Path

import yaml

REPO = Path.home() / "CascadeProjects" / "chaba"
SSOT_VALUES = REPO / "docs" / "ssot" / "infrastructure" / "ssot.values.yml"
MANIFEST = REPO / "data" / "notebooklm-kb-sync-manifest.yml"


def _ssot_values():
    if SSOT_VALUES.exists():
        with open(SSOT_VALUES, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


NOTEBOOK_ID = os.environ.get("NOTEBOOKLM_KB_NOTEBOOK") or _ssot_values().get(
    "notebooklm", {}
).get("sync", {}).get("notebook_id", "fdfd3483-6b7e-4cb0-85f3-7f060698769c")


def _load_manifest():
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"sources": []}


def _match(pattern, title):
    if pattern == title:
        return True
    # allow prefix matching without requiring the trailing slash for exact-category ask
    if pattern.endswith("/"):
        return title.startswith(pattern)
    return title.startswith(pattern + "/")


def main():
    parser = argparse.ArgumentParser(
        description="Query a specific NotebookLM source by title pattern."
    )
    parser.add_argument(
        "source",
        help="Source title pattern (e.g. 'kb/mddb' or 'ssot/values'). Use '-' for all.",
    )
    parser.add_argument("question", nargs=argparse.REMAINDER, help="Question to ask.")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        parser.error("question is required")

    manifest = _load_manifest()
    all_sources = manifest.get("sources", [])

    if args.source == "-":
        ids = [s["source_id"] for s in all_sources if s.get("source_id")]
    else:
        ids = [
            s["source_id"]
            for s in all_sources
            if s.get("source_id") and _match(args.source.rstrip("/"), s.get("title", ""))
        ]

    if not ids:
        print(f"No sources matched '{args.source}'.")
        print("Available sources:")
        for s in sorted(all_sources, key=lambda x: x.get("title", "")):
            print(f"  {s.get('title')}")
        return 1

    short = ", ".join(ids[:5])
    if len(ids) > 5:
        short = f"{short}..."
    print(f"Querying {len(ids)} source(s): {short}")

    cmd = [
        "nlm", "query", "notebook", NOTEBOOK_ID,
        question,
        "--source-ids", ",".join(ids),
        "--timeout", str(args.timeout),
    ]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
