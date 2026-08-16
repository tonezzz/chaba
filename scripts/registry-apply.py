#!/usr/bin/env python3
"""Apply missing assets from scripts/registry-drafts.py into ssot.registry.yml."""
import re
from pathlib import Path
from datetime import date

import yaml

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "docs" / "ssot" / "ssot.registry.yml"


def known_paths():
    if not REGISTRY.exists():
        return set()
    doc = yaml.safe_load(REGISTRY.read_text()) or {}
    return {a.get("path") for a in doc.get("assets", []) if a.get("path")}


def path_key(p):
    return str(p).lstrip("/")


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


def make_id(path):
    key = path.lower()
    key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    key = re.sub(r"(^-|-$)", "", key)
    return key or "unknown"


def make_name(path):
    p = Path(path)
    if str(path).startswith("chaba-h3/"):
        if p.name == "index.html":
            return f"{p.parent.name}/{p.name}"
        return p.name
    return p.name


def make_project(path):
    if str(path).startswith("chaba-h3/"):
        return "chaba-h3"
    return "chaba"


def gather_missing():
    known = {path_key(p) for p in known_paths()}
    missing = []
    scans = [
        (scan_ssot(), "ssot"),
        (scan_scripts(), "script"),
        (scan_h3(), "h3-app"),
        (scan_stacks(), "stack"),
    ]
    for paths, kind in scans:
        for p in paths:
            key = path_key(p)
            if key and key not in known:
                missing.append({"type": kind, "path": str(p)})
    for p in scan_systemd():
        key = path_key(p)
        if key and key not in known:
            kind = "timer" if p.endswith(".timer") else "service"
            missing.append({"type": kind, "path": p})
    return sorted(missing, key=lambda x: (x["type"], x["path"]))


def build_entry(c):
    entry_id = make_id(c["path"])
    name = make_name(c["path"])
    project = make_project(c["path"])
    lines = [
        f"  - id: {entry_id}",
        f"    name: {name}",
        f"    type: {c['type']}",
        f"    path: {c['path']}",
        f"    project: {project}",
    ]
    if c["path"].startswith("~"):
        lines.append(f"    location: user")
    lines.extend([
        "    purpose: TBD — purpose not yet written.",
        "    status: unknown",
        f"    tags: [{c['type']}]",
        f"    added: '{date.today().isoformat()}'",
        "",
    ])
    return "\n".join(lines)


def main():
    missing = gather_missing()
    if not missing:
        print("No missing assets found.")
        return

    text = REGISTRY.read_text()
    marker = "related_files:"
    if marker not in text:
        print(f"Could not find {marker} in {REGISTRY}; aborting.")
        return

    chunks = [build_entry(c) for c in missing]
    body = "\n".join(chunks)
    new_text = text.replace(marker, body + marker, 1)
    REGISTRY.write_text(new_text)
    print(f"Added {len(missing)} missing asset(s) to {REGISTRY}")


if __name__ == "__main__":
    main()
