#!/usr/bin/env python3
"""Render and verify the private, storyboard-mapped Sacred Father V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml


PROJECT = "kk-video-c9f99fee6146"
PACK = f"{PROJECT}-preview-v2"
SOURCE_SHA256 = "5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34"
WIDTH, HEIGHT, FRAMES, STEPS, FPS = 640, 384, 73, 40, 24
RENDER_REVISION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, capture_output=True, text=True, timeout=timeout)


def resolve_images(root: Path, scene_map: dict, audit_path: Path) -> list[dict]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    source = next(
        (entry for entry in audit.get("sources", [])
         if entry.get("label") == "v1_01"),
        None)
    if not source or source.get("sha256") != SOURCE_SHA256:
        raise ValueError("v1_01 audit source hash does not match the approved source")
    rows = source.get("image_rows") or []
    records = source.get("extracted_files") or []
    images = sorted(
        (record for record in records
         if re.fullmatch(r"v1_01/images/image-\d{3}\.[A-Za-z0-9]+",
                         record.get("path", ""))),
        key=lambda record: record["path"])
    if len(images) != len(rows):
        raise ValueError("audited image rows and extracted image files do not align")

    by_id = {}
    for record, row in zip(images, rows):
        image_id = Path(record["path"]).stem
        by_id[image_id] = (record, row)

    resolved = []
    for item in scene_map["shots"]:
        image_id = item["storyboard_image"]
        if image_id not in by_id:
            raise ValueError(f"storyboard image is absent from audit: {image_id}")
        record, row = by_id[image_id]
        if int(row["page"]) != int(item["storyboard_page"]):
            raise ValueError(f"{image_id} is not on approved page {item['storyboard_page']}")
        image_path = root / record["path"]
        if (not image_path.is_file()
                or image_path.stat().st_size != int(record["bytes"])
                or sha256(image_path) != record["sha256"]):
            raise ValueError(f"audited image failed hash/size verification: {image_id}")
        resolved.append({
            "shot": int(item["shot"]),
            "page": int(item["storyboard_page"]),
            "image_id": image_id,
            "path": image_path,
            "sha256": record["sha256"],
        })
    if [item["shot"] for item in resolved] != list(range(1, 11)):
        raise ValueError("scene map must assign exactly shots 1-10 in order")
    return resolved


def inspect_shot(path: Path) -> tuple[bool, str]:
    if not path.is_file() or path.stat().st_size < 1024:
        return False, "missing or too small"
    probe = run([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,nb_read_frames:format=duration",
        "-of", "json", str(path)])
    if probe.returncode:
        return False, f"ffprobe failed: {probe.stderr[-160:]}"
    try:
        data = json.loads(probe.stdout)
        stream = data["streams"][0]
        duration = float(data["format"]["duration"])
        frames = int(stream.get("nb_read_frames") or 0)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return False, f"incomplete ffprobe metadata: {exc}"
    if (stream.get("codec_name") != "h264"
            or (int(stream["width"]), int(stream["height"])) != (WIDTH, HEIGHT)
            or frames < FRAMES - 3 or duration < 2.8):
        return False, f"{stream.get('codec_name')} {stream.get('width')}x{stream.get('height')} {frames}f {duration:.2f}s"
    decoded = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    if decoded.returncode:
        return False, f"full decode failed: {decoded.stderr[-160:]}"
    black = run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-vf", "blackdetect=d=2:pix_th=0.05", "-an", "-f", "null", "-"])
    if black.returncode:
        return False, "black-frame check failed"
    black_s = sum(float(value) for value in
                  re.findall(r"black_duration:([0-9.]+)", black.stderr))
    if black_s >= duration * 0.8:
        return False, f"near-total-black output {black_s:.2f}/{duration:.2f}s"
    return True, f"{frames} frames, {duration:.2f}s, full decode passed"


def reusable(path: Path, sidecar: Path, expected: dict) -> tuple[bool, str]:
    if not sidecar.is_file():
        return False, "no V2 input sidecar"
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "invalid V2 input sidecar"
    if metadata.get("inputs") != expected:
        return False, "V2 inputs changed"
    ok, detail = inspect_shot(path)
    return ok, detail


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def inspect_final(path: Path) -> tuple[bool, str]:
    probe = run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,sample_rate:format=duration",
        "-of", "json", str(path)])
    if probe.returncode:
        return False, f"ffprobe failed: {probe.stderr[-180:]}"
    try:
        data = json.loads(probe.stdout)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
        duration = float(data["format"]["duration"])
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        return False, f"incomplete final metadata: {exc}"
    if (video.get("codec_name") != "h264"
            or (int(video.get("width", 0)), int(video.get("height", 0))) != (WIDTH, HEIGHT)
            or audio.get("codec_name") != "aac"
            or not 59 <= duration <= 61):
        return False, f"invalid codecs/dimensions/duration: {video} {audio} {duration}"
    decoded = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"])
    if decoded.returncode:
        return False, f"full decode failed: {decoded.stderr[-180:]}"
    return True, f"H.264/AAC, {duration:.2f}s, full decode passed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--nest-root", type=Path, required=True)
    args = parser.parse_args()
    pack_dir = args.pack_dir
    nest_root = args.nest_root
    out = pack_dir / "out"
    shots_dir = out / "shots"
    audio_dir = out / "narration"
    shots_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    scene_map_path = pack_dir / "inputs" / "scene-map.yml"
    scene_map = yaml.safe_load(scene_map_path.read_text(encoding="utf-8"))
    if (scene_map.get("project_id") != PROJECT
            or scene_map.get("visibility") != "private"
            or scene_map.get("source", {}).get("sha256") != SOURCE_SHA256):
        raise ValueError("scene map is not bound to the approved private source")
    scene_map_hash = sha256(scene_map_path)
    image_root = (nest_root / "packs" /
                  f"{PROJECT}-pdf-image-audit" / "out")
    mapped = resolve_images(
        image_root, scene_map,
        nest_root / "packs" / f"{PROJECT}-pdf-image-audit" / "out" / "audit.json")
    embeds_root = nest_root / "packs" / f"{PROJECT}-embeds" / "embeds"

    reusable_shots, rendered_shots = [], []
    for item in mapped:
        shot = item["shot"]
        embed_path = embeds_root / f"shot{shot:02d}.pt"
        if not embed_path.is_file() or embed_path.stat().st_size == 0:
            raise FileNotFoundError(f"missing prompt embedding for shot {shot}")
        expected_inputs = {
            "renderer_revision": RENDER_REVISION,
            "scene_map_sha256": scene_map_hash,
            "source_image_sha256": item["sha256"],
            "prompt_embedding_sha256": sha256(embed_path),
            "width": WIDTH,
            "height": HEIGHT,
            "frames": FRAMES,
            "steps": STEPS,
            "fps": FPS,
        }
        video_path = shots_dir / f"kk-shot{shot:02d}.mp4"
        sidecar_path = shots_dir / f"kk-shot{shot:02d}.json"
        ok, detail = reusable(video_path, sidecar_path, expected_inputs)
        if ok:
            print(f"shot {shot:02d}: reuse verified V2 output ({detail})", flush=True)
            reusable_shots.append(shot)
            continue

        print(f"shot {shot:02d}: render page {item['page']} ({item['image_id']}); {detail}",
              flush=True)
        import torch
        from diffusers import LTXImageToVideoPipeline
        from diffusers.utils import export_to_video, load_image

        if not torch.cuda.is_available():
            raise RuntimeError("private V2 pack requires CUDA")
        torch.cuda.empty_cache()
        if "pipeline" not in locals():
            pipeline = LTXImageToVideoPipeline.from_pretrained(
                "Lightricks/LTX-Video",
                torch_dtype=torch.bfloat16,
                text_encoder=None,
                tokenizer=None).to("cuda")
            pipeline.eval()
        values = torch.load(embed_path, map_location="cpu")
        tensors = {
            key: value.cuda() if torch.is_tensor(value) else value
            for key, value in values.items()
        }
        torch.cuda.reset_peak_memory_stats()
        temp_video = video_path.with_suffix(".tmp.mp4")
        started = time.monotonic()
        with torch.inference_mode():
            frames = pipeline(
                image=load_image(str(item["path"])),
                prompt_embeds=tensors["prompt_embeds"],
                prompt_attention_mask=tensors["prompt_attention_mask"],
                negative_prompt_embeds=tensors["negative_prompt_embeds"],
                negative_prompt_attention_mask=tensors[
                    "negative_prompt_attention_mask"],
                width=WIDTH,
                height=HEIGHT,
                num_frames=FRAMES,
                num_inference_steps=STEPS,
                frame_rate=FPS).frames[0]
        export_to_video(frames, str(temp_video), fps=FPS)
        ok, detail = inspect_shot(temp_video)
        if not ok:
            temp_video.unlink(missing_ok=True)
            raise RuntimeError(f"shot {shot} failed media QC: {detail}")
        os.replace(temp_video, video_path)
        shot_result = {
            "schema": 1,
            "status": "pass",
            "shot": shot,
            "source_page": item["page"],
            "source_image": item["image_id"],
            "source_image_sha256": item["sha256"],
            "inputs": expected_inputs,
            "render_seconds": round(time.monotonic() - started, 1),
            "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
            "media_qc": detail,
            "visibility": "private",
            "public_release": False,
        }
        atomic_json(sidecar_path, shot_result)
        rendered_shots.append(shot)
        del frames, tensors, values
        print(f"shot {shot:02d}: rendered and verified ({detail})", flush=True)

    if "pipeline" in locals():
        del pipeline
    import gc
    import torch
    gc.collect()
    torch.cuda.empty_cache()

    old_preview = nest_root / "packs" / f"{PROJECT}-preview"
    th_srt = old_preview / "teaser-preview.th.srt"
    en_srt = old_preview / "teaser-preview.en.srt"
    if not th_srt.is_file() or not en_srt.is_file():
        raise FileNotFoundError("approved V1 subtitle scripts are missing")
    th_out = out / "teaser-preview.th.srt"
    en_out = out / "teaser-preview.en.srt"
    shutil.copyfile(th_srt, th_out)
    shutil.copyfile(en_srt, en_out)

    voice_root = nest_root / "projects" / PROJECT / "voice-reference"
    probe_verdict = (
        nest_root / "packs" / f"{PROJECT}-voice-clone-probe" / "out" /
        "verdict.json")
    voice_script = pack_dir / "run_narration_v2.py"
    narration_run = run([
        sys.executable, str(voice_script),
        "--voice-dir", str(voice_root),
        "--probe-verdict", str(probe_verdict),
        "--srt", str(th_out),
        "--out-dir", str(audio_dir)])
    if narration_run.returncode:
        raise RuntimeError(
            f"VYNCX narration failed: {narration_run.stderr[-600:]}")
    narration_path = audio_dir / "narration.wav"
    narration_probe = run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
        "-of", "json", str(narration_path)])
    if narration_probe.returncode:
        raise RuntimeError(f"narration ffprobe failed: {narration_probe.stderr[-300:]}")
    audio_info = json.loads(narration_probe.stdout)
    audio_stream = audio_info["streams"][0]
    audio_duration = float(audio_info["format"]["duration"])
    if (audio_stream.get("codec_name") != "pcm_s16le"
            or int(audio_stream.get("sample_rate", 0)) != 24000
            or int(audio_stream.get("channels", 0)) != 1
            or not 59.9 <= audio_duration <= 60.1
            or narration_path.stat().st_size < 100_000):
        raise RuntimeError("assembled narration failed 24kHz/60s media checks")
    decoded_audio = run([
        "ffmpeg", "-v", "error", "-i", str(narration_path), "-f", "null", "-"])
    if decoded_audio.returncode:
        raise RuntimeError(f"narration full decode failed: {decoded_audio.stderr[-240:]}")

    concat_path = out / "shots" / "concat.txt"
    concat_path.write_text(
        "".join(f"file '{shots_dir / f'kk-shot{item['shot']:02d}.mp4'}'\n"
                for item in mapped),
        encoding="utf-8")
    silent = out / "teaser-silent.tmp.mp4"
    assemble = run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-vf", "setpts=2.0*PTS", "-an", "-t", "60",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], timeout=1800)
    if assemble.returncode or not silent.is_file() or silent.stat().st_size < 1024:
        raise RuntimeError(f"silent assembly failed: {assemble.stderr[-400:]}")

    teaser = out / "teaser-preview.mp4"
    teaser_tmp = out / "teaser-preview.tmp.mp4"
    mux = run([
        "ffmpeg", "-y", "-i", str(silent), "-i", str(narration_path),
        "-map", "0:v:0", "-map", "1:a:0", "-t", "60",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        str(teaser_tmp)], timeout=1800)
    if mux.returncode:
        raise RuntimeError(f"private V2 mux failed: {mux.stderr[-400:]}")
    ok, final_qc = inspect_final(teaser_tmp)
    if not ok:
        raise RuntimeError(f"private V2 final media QC failed: {final_qc}")
    os.replace(teaser_tmp, teaser)
    silent.unlink(missing_ok=True)
    concat_path.unlink(missing_ok=True)

    shot_qc = {}
    for item in mapped:
        path = shots_dir / f"kk-shot{item['shot']:02d}.mp4"
        ok, detail = inspect_shot(path)
        if not ok:
            raise RuntimeError(f"post-assembly shot {item['shot']} invalid: {detail}")
        shot_qc[str(item["shot"])] = detail
    verdict = {
        "schema": 1,
        "status": "pass",
        "scope": "private Sacred Father V2 preview",
        "approval_ref": "OPS-0952/private-v2 approval",
        "source": {
            "filename": "OST_-_v1_01.pdf",
            "sha256": SOURCE_SHA256,
            "scene_map_sha256": scene_map_hash,
        },
        "shot_mapping": [
            {"shot": item["shot"], "page": item["page"],
             "image": item["image_id"], "sha256": item["sha256"]}
            for item in mapped
        ],
        "rendered_shots": rendered_shots,
        "reused_v2_shots": reusable_shots,
        "shot_qc": shot_qc,
        "narration": json.loads(
            (audio_dir / "narration-verdict.json").read_text(encoding="utf-8")),
        "final_video": {
            "file": teaser.name,
            "sha256": sha256(teaser),
            "bytes": teaser.stat().st_size,
            "qc": final_qc,
        },
        "subtitles": {
            "thai_sha256": sha256(th_out),
            "english_sha256": sha256(en_out),
        },
        "visibility": "private",
        "public_release": False,
    }
    atomic_json(out / "verdict.json", verdict)
    report = [
        "# Sacred Father private V2 preview",
        "",
        "- Status: **pass**",
        "- Scope: private V2 only; V1 preserved; no public release.",
        f"- Source: v1_01 PDF SHA-256 `{SOURCE_SHA256}`.",
        f"- Rendered mapped shots: {rendered_shots or 'none; verified V2 outputs reused'}.",
        f"- Reused verified V2 shots: {reusable_shots or 'none'}.",
        f"- Final media: {final_qc}.",
        "- Thai and English SRTs copied from the approved private preview script.",
        "- Cloned narration and per-cue metrics are in `narration/`.",
        "- Technical verification is not visual or voice-quality sign-off.",
        "",
    ]
    (out / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({
        "status": "pass",
        "rendered_shots": rendered_shots,
        "reused_v2_shots": reusable_shots,
        "final": str(teaser),
        "visibility": "private",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
