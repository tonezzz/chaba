#!/usr/bin/env python3
"""Resident MLX batch renderer for KK-Mac PDF-conditioned shots.

The model is loaded once per batch. Each shot remains serial because MLX,
the VAE, and unified memory share the same M4 GPU/host memory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import imageio.v3 as iio
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "ltx-mlx"))
from ltx_mlx.pipeline import LTXPipeline


def render(manifest: Path, model_dir: Path, output_dir: Path) -> dict:
    spec = json.loads(manifest.read_text())
    shots = spec.get("shots", [])
    if not 1 <= len(shots) <= 20:
        raise ValueError("manifest must contain 1..20 shots")
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    pipe = LTXPipeline(str(model_dir))
    rows = []
    for shot in shots:
        shot_id = str(shot["id"])
        output = output_dir / f"{shot_id}.mp4"
        if output.exists() and output.stat().st_size > 10_000:
            rows.append({"id": shot_id, "status": "existing"})
            continue
        image = iio.imread(shot["image"]) if shot.get("image") else None
        t0 = time.time()
        frames = pipe.generate(
            prompt=shot["prompt"],
            num_frames=int(shot.get("frames", 17)),
            height=int(shot.get("height", 480)),
            width=int(shot.get("width", 768)),
            seed=int(shot.get("seed", 42)),
            image=image,
        )
        iio.imwrite(
            output,
            frames,
            fps=int(shot.get("fps", 24)),
            codec="libx264",
            macro_block_size=None,
        )
        array = np.asarray(frames)
        rows.append({
            "id": shot_id,
            "status": "done",
            "seconds": round(time.time() - t0, 2),
            "frames": int(array.shape[0]),
            "min": int(array.min()),
            "max": int(array.max()),
            "mean": round(float(array.mean()), 2),
            "bytes": output.stat().st_size,
        })
    result = {
        "manifest": str(manifest),
        "model_dir": str(model_dir),
        "shots": rows,
        "elapsed_seconds": round(time.time() - started, 2),
        "verified_nonblack": all(
            r["status"] == "existing"
            or (r["min"] < r["max"] and r["bytes"] > 10_000)
            for r in rows
        ),
    }
    (output_dir / "batch-result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--model-dir", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args()
    print(json.dumps(render(args.manifest, args.model_dir, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
