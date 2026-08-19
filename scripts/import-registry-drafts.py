#!/usr/bin/env python3
"""Import missing assets from REGISTRY_DRAFTS.md into the appropriate ssot.registry.*.yml file."""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO / "docs" / "ssot"
DRAFT = REPO / "reports" / "REGISTRY_DRAFTS.md"


def _kebab_id(path):
    # e.g. chaba-h3/public/apps/docs/mcp_debug/index.html -> chaba-h3-apps-docs-mcp-debug-index-html
    name = Path(path).name
    stem = Path(path).stem if name != "index.html" else Path(path).parent.name
    if not stem:
        stem = Path(path).name
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:60]


def _name(path):
    p = Path(path)
    return p.name if p.name != "index.html" else p.parent.name


def _purpose(path, asset_type):
    return f"{asset_type} asset at {path}; purpose to be documented."


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


def _known_paths():
    known = set()
    for f in sorted(REGISTRY_DIR.glob("ssot.registry.*.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        for a in doc.get("assets", []):
            if a.get("path"):
                known.add(a.get("path"))
    return known


def main():
    known = _known_paths()

    text = DRAFT.read_text()
    blocks = re.findall(r"- type: (\S+)\n  path: (\S+)", text)
    added = 0

    part_assets = {}
    for asset_type, path in blocks:
        if path in known:
            continue
        part = _part_file(asset_type, path)
        entry = {
            "id": _kebab_id(path),
            "name": _name(path),
            "type": asset_type,
            "path": path,
            "project": "chaba",
            "purpose": _purpose(path, asset_type),
            "status": "draft",
        }
        part_assets.setdefault(part, []).append(entry)
        known.add(path)
        added += 1

    for part, entries in part_assets.items():
        f = REGISTRY_DIR / part
        doc = yaml.safe_load(f.read_text()) or {}
        assets = doc.get("assets", [])
        assets.extend(entries)
        assets.sort(key=lambda a: (a.get("type", ""), a.get("path", "")))
        doc["assets"] = assets
        f.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        print(f"Imported {len(entries)} new asset(s) into {f}")

    print(f"Total imported: {added}")


if __name__ == "__main__":
    main()
