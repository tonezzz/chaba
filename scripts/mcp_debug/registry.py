"""MCP Debug registry lookup helpers."""
import json
from pathlib import Path

import yaml

from .config import REPO_DIR
from .ssot import mcp_read_ssot


def _safe_path(path):
    p = Path(path) if Path(path).is_absolute() else REPO_DIR / path
    try:
        p.relative_to(REPO_DIR)
    except ValueError:
        return None
    return p


def _load_assets():
    """Load all assets from the partitioned registry."""
    reg = REPO_DIR / "docs" / "ssot" / "ssot.registry.yml"
    if not reg.exists():
        return []
    doc = yaml.safe_load(reg.read_text()) or {}
    assets = []
    # ssot.registry.yml assets list contains the partition files
    for partition_asset in doc.get("assets", []):
        partition_path = partition_asset.get("path")
        if not partition_path:
            continue
        p = _safe_path(partition_path)
        if not p or not p.exists():
            continue
        try:
            part = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        for asset in part.get("assets", []):
            if not isinstance(asset, dict):
                continue
            asset = dict(asset)
            asset["registry_file"] = partition_path
            asset["partition"] = Path(partition_path).stem
            assets.append(asset)
    return assets


def _fields_for(asset, by):
    by = (by or "any").lower()
    if by == "id":
        return [asset.get("id", "")]
    if by == "name":
        return [asset.get("name", "")]
    if by == "path":
        return [asset.get("path", "")]
    if by == "purpose":
        return [asset.get("purpose", "")]
    if by == "label":
        return [asset.get("label", "")]
    if by == "tags":
        return [str(t) for t in asset.get("tags", [])]
    return [
        asset.get("id", ""),
        asset.get("name", ""),
        asset.get("path", ""),
        asset.get("purpose", ""),
        asset.get("label", ""),
    ] + [str(t) for t in asset.get("tags", [])]


def _matches(asset, q, by):
    if not q:
        return True
    keyword = str(q).lower()
    for field in _fields_for(asset, by):
        if keyword in str(field).lower():
            return True
    return False


def mcp_registry_lookup(host=None, q=None, type=None, by="any", limit=5, offset=0):
    """Search registry assets across partitions."""
    try:
        assets = _load_assets()
    except Exception as e:
        return {"ok": False, "error": f"failed to load registry: {e}"}

    type_filter = (type or "all").lower()
    filtered = [
        a for a in assets
        if (type_filter == "all" or str(a.get("type", "")).lower() == type_filter)
        and _matches(a, q, by)
    ]

    total = len(filtered)
    start = max(0, int(offset or 0))
    end = start + int(limit or 5)
    page = filtered[start:end]

    return {
        "ok": True,
        "q": q,
        "by": by,
        "type": type_filter,
        "offset": start,
        "limit": int(limit or 5),
        "total": total,
        "results": page,
    }


def mcp_registry_get(host=None, id=None, path=None, ssot_limit=20000):
    """Resolve a single asset by id or path and return its source SSOT."""
    if not id and not path:
        return {"ok": False, "error": "id or path is required"}

    try:
        assets = _load_assets()
    except Exception as e:
        return {"ok": False, "error": f"failed to load registry: {e}"}

    matches = []
    for a in assets:
        if path and a.get("path") == path:
            matches.append(a)
        elif id and a.get("id") == id:
            matches.append(a)

    if path:
        # If path was given, prefer exact path match
        path_matches = [a for a in matches if a.get("path") == path]
        if path_matches:
            matches = path_matches

    if len(matches) > 1:
        return {
            "ok": False,
            "error": f"multiple assets match '{id or path}'",
            "candidates": matches[:10],
        }

    if not matches:
        return {"ok": False, "error": f"no asset found for '{id or path}'"}

    asset = matches[0]
    ssot_path = asset.get("path")
    read = mcp_read_ssot(path=ssot_path, limit=int(ssot_limit or 20000))
    if not read.get("ok"):
        return {
            "ok": False,
            "error": read.get("error", "failed to read source SSOT"),
            "asset": asset,
        }

    return {
        "ok": True,
        "asset": asset,
        "ssot": {
            "path": ssot_path,
            "content": read.get("content"),
            "truncated": read.get("truncated", False),
        },
    }
