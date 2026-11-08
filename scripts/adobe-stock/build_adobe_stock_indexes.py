#!/usr/bin/env python3
"""Build deterministic Adobe Stock reuse indexes from campaign manifests.

The generator reads local campaign exports and writes JSON indexes. It does
not access Google Drive or upload anything; a separate sync job may publish
the output to the read-only Ada mount.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

INDEX_FILES = (
    "campaigns.json",
    "assets.json",
    "prompt-patterns.json",
    "rejection-patterns.json",
)
COLLECTIONS = {
    "assets": "assets",
    "prompt-patterns": "prompt_patterns",
    "rejection-patterns": "rejection_patterns",
}


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _campaign_id(manifest: dict[str, Any], path: Path) -> str:
    value = manifest.get("campaign_id") or manifest.get("run_id")
    if value:
        return str(value)
    return path.parent.name


def _source_ref(campaign_id: str, path: Path) -> str:
    return f"{campaign_id}/{path.name}"


def _records(
    manifest: dict[str, Any],
    *,
    campaign_id: str,
    source_ref: str,
    key: str,
) -> list[dict[str, Any]]:
    values = manifest.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"{source_ref}: {key} must be a JSON list")
    output = []
    for position, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"{source_ref}: {key}[{position}] must be an object")
        record = dict(value)
        record.setdefault("id", f"{campaign_id}-{key}-{position + 1}")
        record["campaign_id"] = campaign_id
        record["source_ref"] = source_ref
        output.append(record)
    return output


def _campaign_record(
    manifest: dict[str, Any], *, campaign_id: str, source_ref: str
) -> dict[str, Any]:
    record = {
        key: manifest[key]
        for key in (
            "campaign_id",
            "run_id",
            "theme",
            "status",
            "generator",
            "gdrive_root",
            "tags",
        )
        if key in manifest
    }
    record["campaign_id"] = campaign_id
    record.setdefault("id", campaign_id)
    record["source_ref"] = source_ref
    return record


def build_indexes(campaigns_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Build all indexes from JSON RUN manifests below campaigns_root."""
    root = campaigns_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"campaigns root does not exist: {root}")

    indexes: dict[str, list[dict[str, Any]]] = {
        "campaigns": [],
        "assets": [],
        "prompt-patterns": [],
        "rejection-patterns": [],
    }
    manifests = sorted(root.rglob("RUN.json"))
    for path in manifests:
        manifest = _load_manifest(path)
        campaign_id = _campaign_id(manifest, path)
        source_ref = _source_ref(campaign_id, path.relative_to(root))
        indexes["campaigns"].append(
            _campaign_record(manifest, campaign_id=campaign_id, source_ref=source_ref)
        )
        for output_name, manifest_key in COLLECTIONS.items():
            indexes[output_name].extend(
                _records(
                    manifest,
                    campaign_id=campaign_id,
                    source_ref=source_ref,
                    key=manifest_key,
                )
            )

    for records in indexes.values():
        records.sort(key=lambda item: (str(item.get("campaign_id", "")), str(item["id"])))
    return indexes


def _write_json_atomic(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"items": payload}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_indexes(
    indexes: dict[str, list[dict[str, Any]]], output_root: Path
) -> list[Path]:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for filename in INDEX_FILES:
        key = filename.removesuffix(".json")
        path = root / filename
        _write_json_atomic(path, indexes[key])
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--campaigns-root",
        default=os.environ.get(
            "ADA_ADOBE_STOCK_CAMPAIGNS_ROOT",
            ".adobe-stock/campaigns",
        ),
    )
    parser.add_argument(
        "--output-root",
        default=os.environ.get(
            "ADA_ADOBE_STOCK_INDEX_OUTPUT_ROOT",
            ".adobe-stock/indexes",
        ),
    )
    args = parser.parse_args()
    indexes = build_indexes(Path(args.campaigns_root))
    written = write_indexes(indexes, Path(args.output_root))
    print(json.dumps({
        "ok": True,
        "campaigns": len(indexes["campaigns"]),
        "assets": len(indexes["assets"]),
        "prompt_patterns": len(indexes["prompt-patterns"]),
        "rejection_patterns": len(indexes["rejection-patterns"]),
        "written": [str(path) for path in written],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
