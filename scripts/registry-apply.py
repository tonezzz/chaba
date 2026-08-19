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
    paths = set()
    for f in sorted(REGISTRY.parent.glob("ssot.registry.*.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        paths.update(a.get("path") for a in doc.get("assets", []) if a.get("path"))
    return paths


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


def _part_file(asset_type, path):
    if asset_type == "ssot":
        if path.startswith("docs/ssot/templates/"):
            return "ssot.registry.ssot-template.yml"
        if path.startswith("docs/ssot/ssot.") or path.startswith("docs/ssot/decisions/"):
            return "ssot.registry.ssot-core.yml"
        m = re.match(r"docs/ssot/([^/]+)", path)
        if m:
            return f"ssot.registry.ssot-{Path(m.group(1)).stem}.yml"
    if asset_type in ("service", "timer", "stack"):
        return "ssot.registry.infrastructure.yml"
    return f"ssot.registry.{asset_type}.yml"


def build_entry(c):
    entry_id = make_id(c["path"])
    name = make_name(c["path"])
    project = make_project(c["path"])
    return {
        "id": entry_id,
        "name": name,
        "type": c["type"],
        "path": c["path"],
        "project": project,
        "purpose": "TBD — purpose not yet written.",
        "status": "unknown",
        "tags": [c["type"]],
        "added": str(date.today().isoformat()),
    }


def main():
    missing = gather_missing()
    if not missing:
        print("No missing assets found.")
        return

    part_assets = {}
    for c in missing:
        part = _part_file(c["type"], c["path"])
        part_assets.setdefault(part, []).append(build_entry(c))

    for part, entries in part_assets.items():
        f = REGISTRY.parent / part
        doc = yaml.safe_load(f.read_text()) or {}
        assets = doc.get("assets", [])
        assets.extend(entries)
        assets.sort(key=lambda a: (a.get("type", ""), a.get("path", "")))
        doc["assets"] = assets
        f.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        print(f"Added {len(entries)} missing asset(s) to {f}")


if __name__ == "__main__":
    main()
