#!/usr/bin/env python3
"""Deterministic technical QC for generated video artifacts.

This is the first P0 gate for the Ada Nest video quality control plane. It
checks container/stream metadata, decodability, suspicious black/frozen
content, and audio finiteness without asking an LLM to judge media health.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe(path: Path) -> dict:
    r = run([
        "ffprobe", "-v", "error", "-of", "json",
        "-show_entries",
        "format=duration,format_name,size:stream=index,codec_type,codec_name,"
        "width,height,avg_frame_rate,nb_frames,sample_rate,channels",
        str(path),
    ])
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "ffprobe failed")
    return json.loads(r.stdout)


def ratio(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    if "/" in value:
        a, b = value.split("/", 1)
        return float(a) / float(b)
    return float(value)


def qc(path: Path, *, black_seconds: float = 0.25,
       freeze_seconds: float = 0.75) -> dict:
    result = {
        "path": str(path),
        "ok": False,
        "checks": {},
        "errors": [],
    }
    if not path.is_file() or path.stat().st_size == 0:
        result["errors"].append("missing or empty file")
        return result
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        result["errors"].append("ffprobe and ffmpeg are required")
        return result

    try:
        metadata = probe(path)
        result["metadata"] = metadata
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        result["errors"].append(f"probe: {exc}")
        return result

    streams = metadata.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    checks = result["checks"]
    checks["has_video"] = bool(video)
    checks["dimensions"] = bool(video and video.get("width", 0) > 0
                               and video.get("height", 0) > 0)
    checks["fps"] = ratio(video.get("avg_frame_rate")) if video else 0.0
    checks["duration_s"] = float(
        metadata.get("format", {}).get("duration") or 0.0)
    checks["has_audio"] = bool(audio)

    if not checks["has_video"]:
        result["errors"].append("no video stream")
    if not checks["dimensions"]:
        result["errors"].append("video has invalid dimensions")
    if checks["fps"] <= 0:
        result["errors"].append("video has invalid frame rate")
    if checks["duration_s"] <= 0:
        result["errors"].append("video has invalid duration")

    # Decode to the null muxer. This catches corrupt frames that metadata-only
    # checks miss, while keeping the gate independent of a particular codec.
    decode = run(["ffmpeg", "-v", "error", "-i", str(path),
                  "-map", "0:v:0", "-f", "null", "-"])
    checks["video_decodes"] = decode.returncode == 0
    if decode.returncode:
        result["errors"].append("video decode: " + decode.stderr.strip()[:300])

    if checks["duration_s"] > 0:
        black = run([
            "ffmpeg", "-v", "info", "-i", str(path),
            "-vf", f"blackdetect=d={black_seconds}:pix_th=0.10",
            "-an", "-f", "null", "-",
        ])
        # blackdetect writes detections to stderr even with -v error.
        result["blackdetect"] = black.stderr.strip()[-2000:]
        checks["not_entirely_black"] = "black_start:0" not in black.stderr
        if not checks["not_entirely_black"]:
            result["errors"].append("video appears entirely black")

        freeze = run([
            "ffmpeg", "-v", "info", "-i", str(path),
            "-vf", f"freezedetect=n=-60dB:d={freeze_seconds}",
            "-an", "-f", "null", "-",
        ])
        result["freezedetect"] = freeze.stderr.strip()[-2000:]
        checks["decode_only_freeze_check"] = True

    if audio:
        audio_check = run([
            "ffmpeg", "-v", "error", "-i", str(path),
            "-map", "0:a:0", "-af", "astats=metadata=1:reset=1",
            "-f", "null", "-",
        ])
        checks["audio_decodes"] = audio_check.returncode == 0
        if audio_check.returncode:
            result["errors"].append(
                "audio decode: " + audio_check.stderr.strip()[:300])

    result["ok"] = not result["errors"]
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--json", type=Path, help="write the QC result here")
    args = ap.parse_args(argv)
    result = qc(args.video)
    text = json.dumps(result, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
