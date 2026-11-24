#!/usr/bin/env python3
"""Run shot01 I2V at the proven full LTX frame/step settings."""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
from pathlib import Path

HEIGHT, WIDTH = 384, 640
FRAMES, STEPS = 73, 40
FPS = 24


def inspect_fullshot(path: Path, ffmpeg: str) -> dict:
    metadata = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=60)
    details = metadata.stderr
    stream = re.search(
        r"Video:\s*h264[^\n]*,\s*(\d{2,5})x(\d{2,5})[^\n]*",
        details, re.IGNORECASE)
    duration_match = re.search(
        r"Duration:\s*(\d+):(\d{2}):(\d{2}\.\d+)", details)
    if not stream or not duration_match:
        raise RuntimeError(f"ffmpeg could not identify H.264 media: {details[-500:]}")
    width, height = map(int, stream.groups())
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if (width, height) != (WIDTH, HEIGHT) or not 2.8 <= duration <= 3.3:
        raise RuntimeError(f"unexpected output media: {width}x{height} {duration:.2f}s")

    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=180)
    if decoded.returncode:
        raise RuntimeError(f"full MP4 decode failed: {decoded.stderr[-500:]}")
    black = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path),
         "-vf", "blackdetect=d=2:pix_th=0.05", "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    if black.returncode:
        raise RuntimeError(f"black-frame check failed: {black.stderr[-300:]}")
    black_seconds = sum(
        float(value) for value in
        re.findall(r"black_duration:([0-9.]+)", black.stderr))
    if black_seconds >= duration * 0.8:
        raise RuntimeError(
            f"near-total-black clip: {black_seconds:.2f}/{duration:.2f}s")

    imageio_ffmpeg = __import__("imageio_ffmpeg")
    frames, counted_duration = imageio_ffmpeg.count_frames_and_secs(str(path))
    if frames < FRAMES - 3 or not 2.8 <= counted_duration <= 3.3:
        raise RuntimeError(
            f"unexpected decoded frame count/duration: {frames}/{counted_duration:.2f}s")
    return {
        "codec": "h264",
        "width": width,
        "height": height,
        "frames": int(frames),
        "duration_s": round(float(counted_duration), 3),
        "black_duration_s": round(black_seconds, 3),
        "decode_ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-script", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--embed", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location(
        "kk_mac_i2v_probe_base", args.base_script)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the verified private I2V probe helpers")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.FRAMES = FRAMES
    base.STEPS = STEPS
    base.inspect_video = inspect_fullshot
    try:
        base.run(args.model_dir, args.embed, args.image, args.audit, args.out)
    except Exception as exc:
        print(f"full-settings I2V failed: {type(exc).__name__}: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
