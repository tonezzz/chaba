#!/usr/bin/env python3
"""Run one private LTX image-conditioned smoke; no audio or publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_image_approval(audit_path: Path, image_path: Path) -> tuple[int, str]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    source = next(
        item for item in audit["sources"]
        if item["label"] == "v1_01")
    image_record = next(
        item for item in source["extracted_files"]
        if item["path"].endswith("/images/image-000.jpg"))
    image_hash = sha256(image_path)
    if image_hash != image_record["sha256"]:
        raise ValueError("probe image does not match audited v1_01 asset")
    image_row = source["image_rows"][0]
    return int(image_row["page"]), image_hash


def probe(args: argparse.Namespace) -> dict:
    import torch
    from diffusers import LTXImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image

    image = Path(args.image)
    embeds = Path(args.embeds)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_page, image_hash = verify_image_approval(Path(args.audit), image)
    embed_hash = sha256(embeds)

    values = torch.load(embeds, map_location="cpu")
    tensors = {
        key: value.cuda() if torch.is_tensor(value) else value
        for key, value in values.items()
    }
    torch.cuda.reset_peak_memory_stats()
    pipeline = LTXImageToVideoPipeline.from_pretrained(
        "Lightricks/LTX-Video",
        torch_dtype=torch.bfloat16,
        text_encoder=None,
        tokenizer=None,
    ).to("cuda")
    started = time.monotonic()
    with torch.inference_mode():
        frames = pipeline(
            image=load_image(str(image)),
            prompt_embeds=tensors["prompt_embeds"],
            prompt_attention_mask=tensors["prompt_attention_mask"],
            negative_prompt_embeds=tensors["negative_prompt_embeds"],
            negative_prompt_attention_mask=tensors[
                "negative_prompt_attention_mask"],
            width=640,
            height=384,
            num_frames=25,
            num_inference_steps=12,
            frame_rate=24,
    ).frames[0]
    export_to_video(frames, str(output), fps=24)
    elapsed = round(time.monotonic() - started, 1)
    peak_gpu_gb = round(torch.cuda.max_memory_allocated() / 1e9, 2)
    del pipeline, tensors, values
    torch.cuda.empty_cache()

    probe_result = subprocess.run([
        "ffprobe", "-v", "error", "-count_frames",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,nb_read_frames:format=duration",
        "-of", "json", str(output),
    ], capture_output=True, text=True)
    if probe_result.returncode:
        raise RuntimeError(f"ffprobe failed: {probe_result.stderr[-300:]}")
    metadata = json.loads(probe_result.stdout)
    stream = metadata["streams"][0]
    duration = float(metadata["format"]["duration"])
    frames_read = int(stream.get("nb_read_frames") or 0)
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
        capture_output=True, text=True)
    valid = (
        stream.get("codec_name") == "h264"
        and int(stream.get("width", 0)) == 640
        and int(stream.get("height", 0)) == 384
        and frames_read >= 22
        and 0.8 <= duration <= 1.5
        and decode.returncode == 0
    )
    verdict = {
        "schema": 1,
        "status": "pass" if valid else "fail",
        "scope": "private one-shot image-conditioning smoke only",
        "approval_ref": "OPS-0952/source-image-private-use-approval",
        "source_pdf": "OST_-_v1_01.pdf",
        "source_page": source_page,
        "source_image_sha256": image_hash,
        "prompt_embedding": "shot01.pt",
        "prompt_embedding_sha256": embed_hash,
        "voice_or_audio": "none",
        "visibility": "private",
        "render_seconds": elapsed,
        "gpu_peak_gb": peak_gpu_gb,
        "video": {
            "codec": stream.get("codec_name"),
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "frames": frames_read,
            "duration_s": round(duration, 3),
            "decode_ok": decode.returncode == 0,
            "bytes": output.stat().st_size,
        },
    }
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--embeds", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--verdict", required=True)
    args = parser.parse_args()

    result = probe(args)
    verdict_dir = Path(args.verdict)
    verdict_dir.mkdir(parents=True, exist_ok=True)
    (verdict_dir / "verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (verdict_dir / "verdict.md").write_text(
        "\n".join([
            "# Private image-conditioning smoke",
            "",
            f"- Result: **{result['status']}**",
            f"- Source: {result['source_pdf']}, page {result['source_page']}",
            "- Scope: one ~1-second technical probe; not a scene/final render.",
            "- Audio/voice: none.",
            "- Visibility: private; no publish step is declared.",
            f"- Render time: {result['render_seconds']} s; "
            f"peak GPU: {result['gpu_peak_gb']} GB.",
            "",
        ]),
        encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "pass":
        raise SystemExit("image-conditioned probe QC failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
