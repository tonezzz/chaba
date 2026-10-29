#!/usr/bin/env python3
"""Run one offline LTX-Video MPS probe using the existing Mac HF cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

MODEL_ID = "Lightricks/LTX-Video"
REVISION = "8984fa25007f376c1a299016d0957a37a2f797bb"
EXPECTED_EMBED_SHA256 = "ad7558cdbfbc4a79b2e0812d1d90397b55d3279e40db66419847dded54cbc133"
HEIGHT, WIDTH, FRAMES, STEPS, FPS, SEED = 384, 640, 73, 40, 24, 42


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def run(model_dir: Path, embed_path: Path, out_dir: Path) -> dict:
    import torch
    from diffusers import LTXPipeline
    from diffusers.utils import export_to_video
    import imageio_ffmpeg

    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable on this Mac")
    if sha256_file(embed_path) != EXPECTED_EMBED_SHA256:
        raise RuntimeError("shot01 embedding hash does not match the staged project input")
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
        path = model_dir / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"cached model component missing: {relative}")

    embeds = torch.load(embed_path, map_location="cpu", weights_only=True)
    required = {
        "prompt_embeds",
        "prompt_attention_mask",
        "negative_prompt_embeds",
        "negative_prompt_attention_mask",
    }
    if not required.issubset(embeds):
        raise RuntimeError(f"shot embedding keys missing: {sorted(required - set(embeds))}")

    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    dtype = torch.bfloat16
    print(f"load {MODEL_ID}@{REVISION} on MPS ({dtype})", flush=True)
    pipe = LTXPipeline.from_pretrained(
        str(model_dir),
        text_encoder=None,
        tokenizer=None,
        torch_dtype=dtype,
        local_files_only=True,
    ).to("mps")
    pipe.set_progress_bar_config(disable=True)
    load_s = round(time.monotonic() - started, 2)
    mps_sync = getattr(torch.mps, "synchronize", None)
    if mps_sync:
        mps_sync()

    tensors = {
        key: value.to("mps", dtype=dtype) if torch.is_tensor(value) else value
        for key, value in embeds.items()
    }
    gen_started = time.monotonic()
    print(f"generate shot01: {FRAMES} frames, {STEPS} steps, {WIDTH}x{HEIGHT}", flush=True)
    with torch.inference_mode():
        frames = pipe(
            prompt=None,
            prompt_embeds=tensors["prompt_embeds"],
            prompt_attention_mask=tensors["prompt_attention_mask"],
            negative_prompt_embeds=tensors["negative_prompt_embeds"],
            negative_prompt_attention_mask=tensors["negative_prompt_attention_mask"],
            height=HEIGHT,
            width=WIDTH,
            num_frames=FRAMES,
            num_inference_steps=STEPS,
            frame_rate=FPS,
            generator=torch.Generator(device="cpu").manual_seed(SEED),
            output_type="pil",
        ).frames[0]
    if mps_sync:
        mps_sync()
    gen_s = round(time.monotonic() - gen_started, 2)

    output = out_dir / "kk-shot01-mps.mp4"
    export_to_video(frames, str(output), fps=FPS)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("render output is empty")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    decode = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    if decode.returncode:
        raise RuntimeError(f"MP4 decode check failed: {decode.stderr[-600:]}")

    report = {
        "schema": 1,
        "kind": "kk-mac-ltx-video-mps-single-shot-probe",
        "scope": "one T2V technical probe only; not a full render or quality approval",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "machine": platform.machine(),
        "model_id": MODEL_ID,
        "revision": REVISION,
        "device": "mps",
        "torch": torch.__version__,
        "diffusers": __import__("diffusers").__version__,
        "dtype": str(dtype),
        "input_embed_sha256": sha256_file(embed_path),
        "width": WIDTH,
        "height": HEIGHT,
        "frames": len(frames),
        "fps": FPS,
        "steps": STEPS,
        "model_load_s": load_s,
        "generation_s": gen_s,
        "total_s": round(time.monotonic() - started, 2),
        "mps_memory": mps_memory(torch),
        "output": {
            "name": output.name,
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
            "decode_ok": True,
        },
        "verdict": "technical_probe_pass",
        "quality_review": "pending human review; no quality claim",
    }
    (out_dir / "probe.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(
        "\n".join([
            "# KK-Mac LTX MPS single-shot probe",
            "",
            f"- Scope: {report['scope']}",
            f"- Model: `{MODEL_ID}` at `{REVISION}`",
            f"- Device/dtype: MPS / {dtype}",
            f"- Settings: {WIDTH}x{HEIGHT}, {FRAMES} frames, {STEPS} steps, {FPS} fps",
            f"- Load/generation/total: {load_s}s / {gen_s}s / {report['total_s']}s",
            f"- MP4: {output.stat().st_size} bytes; decode check passed",
            "- Verdict: technical probe passed; quality review remains pending.",
            "",
        ]),
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--embed", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.model_dir, args.embed, args.out)
    except Exception as exc:
        print(f"MPS probe failed: {type(exc).__name__}: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
