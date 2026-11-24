#!/usr/bin/env python3
"""Run one offline, audited storyboard-image LTX probe on KK-Mac MPS."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

MODEL_ID = "Lightricks/LTX-Video"
REVISION = "8984fa25007f376c1a299016d0957a37a2f797bb"
SOURCE_SHA256 = "5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34"
EMBED_SHA256 = "ad7558cdbfbc4a79b2e0812d1d90397b55d3279e40db66419847dded54cbc133"
IMAGE_SHA256 = "a7ac937fdffe3b1d3bcad55ce3ba4bee9366311c2eefeada88ac21b1f32cc244"
HEIGHT, WIDTH, FRAMES, STEPS, FPS, SEED = 384, 640, 25, 12, 24, 42


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_inputs(embed: Path, image: Path, audit_path: Path) -> dict:
    if sha256(embed) != EMBED_SHA256:
        raise ValueError("shot01 embedding hash differs from the approved input")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    source = next(
        (entry for entry in audit.get("sources", [])
         if entry.get("label") == "v1_01"),
        None)
    if not source or source.get("sha256") != SOURCE_SHA256:
        raise ValueError("image audit is not bound to the approved v1_01 PDF")
    records = sorted(
        (record for record in source.get("extracted_files", [])
         if re.fullmatch(r"v1_01/images/image-\d{3}\.[A-Za-z0-9]+",
                         record.get("path", ""))),
        key=lambda record: record["path"])
    rows = source.get("image_rows") or []
    if len(records) != len(rows):
        raise ValueError("image audit rows and extracted files do not align")
    record_index = next(
        (index for index, record in enumerate(records)
         if Path(record["path"]).stem == "image-006"),
        None)
    if record_index is None or int(rows[record_index]["page"]) != 9:
        raise ValueError("image-006 is not the approved page-9 storyboard")
    record = records[record_index]
    if (record.get("sha256") != IMAGE_SHA256
            or not image.is_file()
            or image.stat().st_size != int(record["bytes"])
            or sha256(image) != record["sha256"]):
        raise ValueError("page-9 storyboard image failed audit hash/size check")
    return {
        "source_pdf": "OST_-_v1_01.pdf",
        "source_sha256": SOURCE_SHA256,
        "page": 9,
        "image": "image-006.jpg",
        "image_sha256": record["sha256"],
        "embedding_sha256": EMBED_SHA256,
    }


def inspect_video(path: Path, ffmpeg: str) -> dict:
    metadata = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=60)
    text = metadata.stderr
    stream = re.search(
        r"Video:\s*h264[^\n]*,\s*(\d{2,5})x(\d{2,5})[^\n]*",
        text, re.IGNORECASE)
    duration_match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}\.\d+)", text)
    if not stream or not duration_match:
        raise RuntimeError(f"ffmpeg could not identify H.264 media: {text[-500:]}")
    width, height = map(int, stream.groups())
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if (width, height) != (WIDTH, HEIGHT) or not 0.8 <= duration <= 1.5:
        raise RuntimeError(f"unexpected output media: {width}x{height} {duration:.2f}s")
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=180)
    if decoded.returncode:
        raise RuntimeError(f"full MP4 decode failed: {decoded.stderr[-500:]}")
    frames, counted_duration = __import__(
        "imageio_ffmpeg").count_frames_and_secs(str(path))
    if frames < FRAMES - 3 or not 0.8 <= counted_duration <= 1.5:
        raise RuntimeError(
            f"unexpected decoded frame count/duration: {frames} / {counted_duration:.2f}s")
    black = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path),
         "-vf", "blackdetect=d=0.2:pix_th=0.05", "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    if black.returncode:
        raise RuntimeError(f"black-frame check failed: {black.stderr[-300:]}")
    black_seconds = sum(
        float(value) for value in
        re.findall(r"black_duration:([0-9.]+)", black.stderr))
    if black_seconds >= counted_duration * 0.8:
        raise RuntimeError(
            f"near-total-black clip: {black_seconds:.2f}/{counted_duration:.2f}s")
    return {
        "codec": "h264",
        "width": width,
        "height": height,
        "frames": int(frames),
        "duration_s": round(float(counted_duration), 3),
        "black_duration_s": round(black_seconds, 3),
        "decode_ok": True,
    }


def mps_memory(torch) -> dict:
    stats = {}
    for label, method in (
        ("current_allocated_bytes", "current_allocated_memory"),
        ("driver_allocated_bytes", "driver_allocated_memory"),
    ):
        fn = getattr(torch.mps, method, None)
        if fn:
            try:
                stats[label] = int(fn())
            except Exception:
                stats[label] = None
    return stats


def run(model_dir: Path, embed: Path, image: Path,
        audit_path: Path, out_dir: Path) -> dict:
    import torch
    from diffusers import LTXImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image
    import imageio_ffmpeg

    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable on this Mac")
    input_info = verify_inputs(embed, image, audit_path)
    for relative in (
        "model_index.json",
        "scheduler/scheduler_config.json",
        "transformer/config.json",
        "transformer/diffusion_pytorch_model.safetensors.index.json",
        "transformer/diffusion_pytorch_model-00001-of-00002.safetensors",
        "transformer/diffusion_pytorch_model-00002-of-00002.safetensors",
        "vae/config.json",
        "vae/diffusion_pytorch_model.safetensors",
    ):
        if not (model_dir / relative).is_file():
            raise FileNotFoundError(f"cached LTX component missing: {relative}")

    embeds = torch.load(embed, map_location="cpu", weights_only=True)
    required = {
        "prompt_embeds", "prompt_attention_mask",
        "negative_prompt_embeds", "negative_prompt_attention_mask",
    }
    if not required.issubset(embeds):
        raise ValueError("shot01 embedding is missing required prompt tensors")

    out_dir.mkdir(parents=True, exist_ok=True)
    dtype = torch.bfloat16
    started = time.monotonic()
    pipeline = LTXImageToVideoPipeline.from_pretrained(
        str(model_dir),
        text_encoder=None,
        tokenizer=None,
        torch_dtype=dtype,
        local_files_only=True).to("mps")
    pipeline.set_progress_bar_config(disable=True)
    if hasattr(torch.mps, "synchronize"):
        torch.mps.synchronize()
    load_seconds = round(time.monotonic() - started, 2)

    tensors = {
        key: value.to("mps", dtype=dtype) if torch.is_tensor(value) else value
        for key, value in embeds.items()
    }
    torch.mps.empty_cache()
    generate_started = time.monotonic()
    with torch.inference_mode():
        frames = pipeline(
            image=load_image(str(image)),
            prompt=None,
            prompt_embeds=tensors["prompt_embeds"],
            prompt_attention_mask=tensors["prompt_attention_mask"],
            negative_prompt_embeds=tensors["negative_prompt_embeds"],
            negative_prompt_attention_mask=tensors[
                "negative_prompt_attention_mask"],
            height=HEIGHT,
            width=WIDTH,
            num_frames=FRAMES,
            num_inference_steps=STEPS,
            frame_rate=FPS,
            generator=torch.Generator(device="cpu").manual_seed(SEED),
            output_type="pil").frames[0]
    if hasattr(torch.mps, "synchronize"):
        torch.mps.synchronize()
    generation_seconds = round(time.monotonic() - generate_started, 2)

    output = out_dir / "shot01-i2v-mps.mp4"
    temp_output = out_dir / "shot01-i2v-mps.tmp.mp4"
    export_to_video(frames, str(temp_output), fps=FPS)
    if not temp_output.is_file() or temp_output.stat().st_size == 0:
        raise RuntimeError("I2V output is empty")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    media = inspect_video(temp_output, ffmpeg)
    temp_output.replace(output)
    peak_memory_note = (
        "MPS API exposes current/driver allocation only; these are after-run values, "
        "not peak memory.")
    report = {
        "schema": 1,
        "kind": "kk-mac-storyboard-image-conditioned-ltx-i2v-probe",
        "scope": "one private shot01 I2V technical probe",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "machine": platform.machine(),
        "model_id": MODEL_ID,
        "revision": REVISION,
        "device": "mps",
        "dtype": str(dtype),
        "inputs": input_info,
        "width": WIDTH,
        "height": HEIGHT,
        "frames_requested": FRAMES,
        "steps": STEPS,
        "fps": FPS,
        "model_load_s": load_seconds,
        "generation_s": generation_seconds,
        "total_s": round(time.monotonic() - started, 2),
        "mps_memory_after_run": mps_memory(torch),
        "memory_measurement_note": peak_memory_note,
        "output": {
            "name": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha256(output),
            **media,
        },
        "verdict": "technical_probe_pass",
        "visibility": "private",
        "public_release": False,
        "quality_review": "pending human review",
    }
    (out_dir / "probe.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(
        "\n".join([
            "# KK-Mac storyboard I2V probe",
            "",
            "- Scope: one private image-conditioned technical probe.",
            "- Input: v1_01 page 9 storyboard image, mapped to shot 1.",
            f"- Model: `{MODEL_ID}@{REVISION}` on MPS / {dtype}.",
            f"- Settings: {WIDTH}x{HEIGHT}, {FRAMES} requested frames, {STEPS} steps.",
            f"- Load/generation/total: {load_seconds}s / {generation_seconds}s / {report['total_s']}s.",
            f"- Output: {output.stat().st_size} bytes; {media['frames']} frames; decode passed.",
            f"- Memory note: {peak_memory_note}",
            "- Visibility: private; no narration or public release.",
            "- Technical validity is not visual-quality sign-off.",
            "",
        ]),
        encoding="utf-8")
    print(json.dumps({
        "status": report["verdict"],
        "generation_s": generation_seconds,
        "output_sha256": report["output"]["sha256"],
        "visibility": "private",
    }), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--embed", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.model_dir, args.embed, args.image, args.audit, args.out)
    except Exception as exc:
        print(f"I2V probe failed: {type(exc).__name__}: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
