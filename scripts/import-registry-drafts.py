#!/usr/bin/env python3
"""Import missing assets from REGISTRY_DRAFTS.md into ssot.registry.yml."""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "docs" / "ssot" / "ssot.registry.yml"
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


def main():
    doc = yaml.safe_load(REGISTRY.read_text()) or {}
    assets = doc.get("assets", [])
    known = {a.get("path") for a in assets if a.get("path")}

    text = DRAFT.read_text()
    blocks = re.findall(r"- type: (\S+)\n  path: (\S+)", text)
    added = 0

    for asset_type, path in blocks:
        if path in known:
            continue
        assets.append({
            "id": _kebab_id(path),
            "name": _name(path),
            "type": asset_type,
            "path": path,
            "project": "chaba",
            "purpose": _purpose(path, asset_type),
            "status": "draft",
        })
        known.add(path)
        added += 1

    doc["assets"] = assets
    REGISTRY.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    print(f"Imported {added} new assets into {REGISTRY}")
    print(f"Total assets: {len(assets)}")


if __name__ == "__main__":
    main()
