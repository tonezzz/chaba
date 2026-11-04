#!/usr/bin/env python3
"""Create and verify portable Nest media-pack manifests.

The manifest is deliberately storage-provider neutral: Drive hydration and
local scratch cleanup stay in the worker, while this tool records immutable
inputs and outputs for every image/video/audio/GS candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _files(root: Path):
    return sorted(p for p in root.rglob("*") if p.is_file()
                  and p.name != "manifest.json")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_pack(args) -> int:
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "nest-media-pack-v1",
        "pack_id": args.pack_id,
        "asset_type": args.asset_type,
        "dataset_ref": args.dataset_ref,
        "path_id": args.path_id,
        "privacy": args.privacy,
        "created_at": _now(),
        "files": [],
        "outputs": {},
        "metrics": {},
        "verifier": {},
        "verdict": None,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    return 0


def hash_pack(args) -> int:
    root = args.root.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = [
        {"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
         "sha256": _hash(path)}
        for path in _files(root)
    ]
    manifest["hashed_at"] = _now()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"ok": True, "files": len(manifest["files"])},
                     indent=2))
    return 0


def verify_pack(args) -> int:
    root = args.root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    missing, changed = [], []
    for item in manifest.get("files", []):
        path = root / item["path"]
        if not path.is_file():
            missing.append(item["path"])
        elif _hash(path) != item["sha256"]:
            changed.append(item["path"])
    result = {"ok": not missing and not changed, "missing": missing,
              "changed": changed, "files": len(manifest.get("files", []))}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "hash", "verify"):
        p = sub.add_parser(command)
        p.add_argument("root", type=Path)
        if command == "init":
            p.add_argument("--pack-id", required=True)
            p.add_argument("--asset-type", required=True)
            p.add_argument("--dataset-ref", default="")
            p.add_argument("--path-id", default="original-v1")
            p.add_argument("--privacy", default="private")
    args = parser.parse_args()
    return {"init": init_pack, "hash": hash_pack,
            "verify": verify_pack}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
