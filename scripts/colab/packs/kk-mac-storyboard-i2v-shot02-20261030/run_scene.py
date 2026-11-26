#!/usr/bin/env python3
"""Render one audited storyboard-mapped shot with the cached Mac MPS model."""

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

import yaml

MODEL_ID = "Lightricks/LTX-Video"
REVISION = "8984fa25007f376c1a299016d0957a37a2f797bb"
SOURCE_SHA256 = "5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34"
HEIGHT, WIDTH, FRAMES, STEPS, FPS, SEED = 384, 640, 73, 40, 24, 42


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_inputs(pack_dir: Path) -> tuple[dict, Path, Path]:
    scene_map = yaml.safe_load(
        (pack_dir / "inputs/scene-map.yml").read_text(encoding="utf-8"))
    if (scene_map.get("project_id") != "kk-video-c9f99fee6146"
            or scene_map.get("visibility") != "private"
            or scene_map.get("source", {}).get("sha256") != SOURCE_SHA256):
        raise ValueError("scene map is not bound to the approved private source")
    shot = scene_map["shot"]
    number = int(shot["number"])
    image_id = str(shot["storyboard_image"])
    if number != 2 or image_id != "image-007" or int(shot["storyboard_page"]) != 12:
        raise ValueError("this pack is pinned to shot02/page12/image-007")

    audit = json.loads(
        (pack_dir / "inputs/audit.json").read_text(encoding="utf-8"))
    source = next(
        (entry for entry in audit.get("sources", [])
         if entry.get("label") == "v1_01"),
        None)
    if not source or source.get("sha256") != SOURCE_SHA256:
        raise ValueError("v1_01 audit source hash differs from the approved PDF")
    records = sorted(
        (record for record in source.get("extracted_files", [])
         if re.fullmatch(r"v1_01/images/image-\d{3}\.[A-Za-z0-9]+",
                         record.get("path", ""))),
        key=lambda record: record["path"])
    rows = source.get("image_rows") or []
    if len(records) != len(rows):
        raise ValueError("audited image rows and extracted files do not align")
    image_index = next(
        (index for index, record in enumerate(records)
         if Path(record["path"]).stem == image_id),
        None)
    if image_index is None or int(rows[image_index]["page"]) != 12:
        raise ValueError("image-007 is not on approved storyboard page 12")

    image_record = records[image_index]
    image_path = pack_dir / "inputs/image-007.jpg"
    embed_path = pack_dir / "inputs/shot02.pt"
    if (image_record.get("sha256") != shot["image_sha256"]
            or not image_path.is_file()
            or image_path.stat().st_size != int(image_record["bytes"])
            or sha256(image_path) != image_record["sha256"]):
        raise ValueError("page-12 storyboard image failed audit hash/size check")
    if (not embed_path.is_file()
            or sha256(embed_path) != shot["embedding_sha256"]):
        raise ValueError("shot02 embedding hash differs from the staged scene map")
    return {
        "source_pdf": "OST_-_v1_01.pdf",
        "source_sha256": SOURCE_SHA256,
        "shot": number,
        "page": 12,
        "image": image_id,
        "image_sha256": image_record["sha256"],
        "embedding_sha256": shot["embedding_sha256"],
    }, image_path, embed_path


def inspect_output(path: Path, ffmpeg: str) -> dict:
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
        raise RuntimeError(f"unexpected media metadata: {width}x{height} {duration:.2f}s")
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=180)
    if decoded.returncode:
        raise RuntimeError(f"full decode failed: {decoded.stderr[-400:]}")
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
        raise RuntimeError(f"near-total-black output: {black_seconds:.2f}s")
    import imageio_ffmpeg
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


def mps_memory(torch) -> dict:
    memory = {}
    for label, method in (
        ("current_allocated_bytes", "current_allocated_memory"),
        ("driver_allocated_bytes", "driver_allocated_memory"),
    ):
        fn = getattr(torch.mps, method, None)
        if fn:
            try:
                memory[label] = int(fn())
            except Exception:
                memory[label] = None
    return memory


def run(pack_dir: Path, model_dir: Path) -> dict:
    import torch
    from diffusers import LTXImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image
    import imageio_ffmpeg

    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable")
    input_info, image_path, embed_path = verify_inputs(pack_dir)
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

    embeddings = torch.load(embed_path, map_location="cpu", weights_only=True)
    required = {
        "prompt_embeds", "prompt_attention_mask",
        "negative_prompt_embeds", "negative_prompt_attention_mask",
    }
    if not required.issubset(embeddings):
        raise ValueError("shot02 embedding is missing prompt tensors")

    dtype = torch.bfloat16
    started = time.monotonic()
    pipeline = LTXImageToVideoPipeline.from_pretrained(
        str(model_dir), text_encoder=None, tokenizer=None,
        torch_dtype=dtype, local_files_only=True).to("mps")
    pipeline.set_progress_bar_config(disable=True)
    if hasattr(torch.mps, "synchronize"):
        torch.mps.synchronize()
    load_s = round(time.monotonic() - started, 2)
    tensors = {
        key: value.to("mps", dtype=dtype) if torch.is_tensor(value) else value
        for key, value in embeddings.items()
    }
    if hasattr(torch.mps, "empty_cache"):
        torch.mps.empty_cache()
    render_started = time.monotonic()
    with torch.inference_mode():
        frames = pipeline(
            image=load_image(str(image_path)),
            prompt=None,
            prompt_embeds=tensors["prompt_embeds"],
            prompt_attention_mask=tensors["prompt_attention_mask"],
            negative_prompt_embeds=tensors["negative_prompt_embeds"],
            negative_prompt_attention_mask=tensors["negative_prompt_attention_mask"],
            height=HEIGHT, width=WIDTH, num_frames=FRAMES,
            num_inference_steps=STEPS, frame_rate=FPS,
            generator=torch.Generator(device="cpu").manual_seed(SEED + 2),
            output_type="pil").frames[0]
    if hasattr(torch.mps, "synchronize"):
        torch.mps.synchronize()
    generation_s = round(time.monotonic() - render_started, 2)

    out_dir = pack_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "shot02-i2v-mps.mp4"
    temp = out_dir / "shot02-i2v-mps.tmp.mp4"
    export_to_video(frames, str(temp), fps=FPS)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    media = inspect_output(temp, ffmpeg)
    temp.replace(output)
    report = {
        "schema": 1,
        "kind": "kk-mac-storyboard-image-conditioned-ltx-i2v-shot02",
        "scope": "one private shot02 I2V render",
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
        "model_load_s": load_s,
        "generation_s": generation_s,
        "total_s": round(time.monotonic() - started, 2),
        "mps_memory_after_run": mps_memory(torch),
        "memory_measurement_note": "MPS current/driver allocation after run; not peak memory.",
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
            "# KK-Mac storyboard I2V shot02",
            "",
            "- Scope: one private mapped shot; no narration or public release.",
            "- Input: v1_01 page 12, image-007, shot02 prompt embedding.",
            f"- Model: `{MODEL_ID}@{REVISION}` on MPS / {dtype}.",
            f"- Settings: {WIDTH}x{HEIGHT}, {FRAMES} frames, {STEPS} steps, {FPS} fps.",
            f"- Load/generation/total: {load_s}s / {generation_s}s / {report['total_s']}s.",
            f"- Output: H.264, {media['frames']} frames, {media['duration_s']:.2f}s; full decode passed.",
            "- Technical pass is not visual-quality sign-off.",
            "",
        ]),
        encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.pack_dir, args.model_dir)
    print(json.dumps({
        "status": report["verdict"],
        "generation_s": report["generation_s"],
        "output_sha256": report["output"]["sha256"],
        "visibility": "private",
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
