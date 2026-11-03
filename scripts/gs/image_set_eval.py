#!/usr/bin/env python3
"""Deterministic Gaussian-capture image-set evaluation.

The evaluator is intentionally independent of an LLM. It produces evidence
Ada can explain through the optional Kornia MCP adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def sharpness(gray: np.ndarray) -> float:
    # Variance of a four-neighbour gradient: useful without OpenCV/Kornia.
    x = gray.astype(np.float32)
    dx = x[:, 1:] - x[:, :-1]
    dy = x[1:, :] - x[:-1, :]
    return float((dx.var() + dy.var()) / 2.0)


def evaluate(root: Path) -> dict:
    images = sorted(p for p in root.iterdir()
                    if p.is_file() and p.suffix.lower() in EXTS)
    rows = []
    hashes = {}
    for path in images:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            arr = np.asarray(rgb)
        gray = np.asarray(rgb.convert("L"))
        row = {
            "file": path.name,
            "width": int(arr.shape[1]),
            "height": int(arr.shape[0]),
            "bytes": len(data),
            "sha256": digest,
            "mean_luma": round(float(gray.mean()), 3),
            "luma_std": round(float(gray.std()), 3),
            "sharpness": round(sharpness(gray), 3),
        }
        rows.append(row)
        hashes.setdefault(digest, []).append(path.name)

    dims = sorted({(r["width"], r["height"]) for r in rows})
    duplicates = [names for names in hashes.values() if len(names) > 1]
    values = [r["sharpness"] for r in rows]
    result = {
        "dataset": str(root),
        "images": len(rows),
        "rows": rows,
        "gates": {
            "non_empty": bool(rows) and all(r["bytes"] > 0 for r in rows),
            "same_dimensions": len(dims) <= 1,
            "duplicate_groups": len(duplicates),
            "min_sharpness": min(values) if values else 0.0,
            "sharpness_median": (float(np.median(values)) if values else 0.0),
        },
        "recommendation": "train_baseline_then_review_masks",
    }
    if not result["gates"]["non_empty"]:
        result["recommendation"] = "reject_empty_or_tiny_inputs"
    elif not result["gates"]["same_dimensions"]:
        result["recommendation"] = "normalize_dimensions_then_retry"
    elif result["gates"]["min_sharpness"] < 5:
        result["recommendation"] = "review_blurry_frames"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image_dir", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    result = evaluate(args.image_dir)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
