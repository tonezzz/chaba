#!/usr/bin/env python3
"""Propose missing assets for ssot.registry.yml without modifying it."""
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "docs" / "ssot" / "ssot.registry.yml"
DRAFT = REPO / "reports" / "REGISTRY_DRAFTS.md"


def run(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw).stdout


def known_paths():
    if not REGISTRY.exists():
        return set()
    paths = set()
    for f in sorted(REGISTRY.parent.glob("ssot.registry.*.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        paths.update(a.get("path") for a in doc.get("assets", []) if a.get("path"))
    return paths


def scan_ssot():
    return [p.relative_to(REPO) for p in (REPO / "docs" / "ssot").rglob("*.yml") if "focus-inbox" not in p.parts]


def scan_scripts():
    return [p.relative_to(REPO) for p in (REPO / "scripts").rglob("*.py") if "__pycache__" not in p.parts]


def scan_systemd():
    home = Path.home() / ".config" / "systemd" / "user"
    paths = []
    if home.exists():
        for p in home.iterdir():
            if p.suffix in {".service", ".timer"}:
                paths.append(f"~/.config/systemd/user/{p.name}")
    return paths


def scan_h3():
    h3 = REPO.parent / "chaba-h3" / "public" / "apps"
    paths = []
    if h3.exists():
        for p in h3.rglob("index.html"):
            paths.append(f"chaba-h3/public/{p.relative_to(h3.parent).as_posix()}")
    return paths


def scan_stacks():
    return [p.relative_to(REPO) for p in (REPO / "stacks").rglob("docker-compose.yml")]


def path_key(p):
    return str(p).lstrip("/")


def main():
    known = {path_key(p) for p in known_paths()}
    candidates = []
    for p in scan_ssot():
        key = path_key(p)
        if key and key not in known:
            candidates.append({"type": "ssot", "path": str(p)})
    for p in scan_scripts():
        key = path_key(p)
        if key and key not in known:
            candidates.append({"type": "script", "path": str(p)})
    for p in scan_systemd():
        key = path_key(p)
        if key and key not in known:
            kind = "timer" if p.endswith(".timer") else "service"
            candidates.append({"type": kind, "path": p})
    for p in scan_h3():
        key = path_key(p)
        if key and key not in known:
            candidates.append({"type": "h3-app", "path": p})
    for p in scan_stacks():
        key = path_key(p)
        if key and key not in known:
            candidates.append({"type": "stack", "path": str(p)})

    if not candidates:
        print("No missing assets found.")
        DRAFT.parent.mkdir(parents=True, exist_ok=True)
        DRAFT.write_text("# Registry Drafts\n\nNo missing assets found.\n")
        return

    lines = ["# Registry Drafts", "", "The following assets are not yet in ssot.registry.yml:", ""]
    for c in sorted(candidates, key=lambda x: (x["type"], x["path"])):
        lines.append(f"- type: {c['type']}")
        lines.append(f"  path: {c['path']}")
        lines.append("  purpose: ")
        lines.append("  status: unknown")
        lines.append("")
    DRAFT.parent.mkdir(parents=True, exist_ok=True)
    DRAFT.write_text("\n".join(lines))
    print(f"Found {len(candidates)} missing asset(s); draft written to {DRAFT}")


if __name__ == "__main__":
    main()
