#!/usr/bin/env python3
"""kk-mac-mlx-vimax-goldenhour-s0 — MLX rerender of the ViMax
idea2video-local scene_0 shots (Golden Hour Catch) on the proven
KK-Mac MLX lane.

Old lane (adanest@kk-mac vimax_gen_video.py): diffusers LTXPipeline
t2v, torch.float32 + cpu_offload, 768x512/49f/30 steps/24fps, ~11min/shot.
ViMax prompt = shot_description.motion_desc + "\n" + audio_desc —
reproduced verbatim below from scene_0/shots/{0,1}/shot_description.json.

This is t2v like the old render (first_frame.png was storyboard ref
only — the old pipeline never conditioned on it). Prompt text goes
through the real T5 encoder on kk-mac (proven path; text_encoder
weights are present in the model dir).

STAGED-ON-APPROVAL: repo definition only — do NOT copy into
gdrive:ada-nest/kk-mac-video-pilot/packs/ until the scene0 control
passes and KK reviews quality.
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

PACK_DIR = Path(os.environ.get("PACK_DIR", os.getcwd()))
HOME = Path(os.path.expanduser("~"))
sys.path.insert(0, str(HOME / "kk-video" / "ltx-mlx"))

MODEL_DIR = HOME / "kk-video" / "ltx-mlx" / "models" / "LTX"
CHECKPOINT = "ltxv-2b-0.9.8-distilled.safetensors"
OUT = PACK_DIR / "out"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT, FRAMES, FPS = 768, 512, 49, 24
STEPS = 8
SEED = 42

SCENES = [
    {
        "id": "vimax-s0shot0",
        "prompt": ("Static camera. No movement observed within the frame.\n"
                   "[Ambient Sound] Gentle wind rustling the sails, water "
                   "lapping against the boat's hull, and distant birdsong."),
        "old": "adanest@kk-mac:~/ViMax/.working_dir/idea2video-local/"
               "scene_0/shots/0/video.mp4",
    },
    {
        "id": "vimax-s0shot1",
        "prompt": ("The camera slowly pans horizontally from the child's "
                   "face to reveal Kaow's hands gripping the tiller. The "
                   "fish arcs through the air in a slow-motion trajectory "
                   "before splashing into the water, with the camera "
                   "maintaining a static position during the splash.\n"
                   "[Sound Effect] A child's cheerful laughter, followed by "
                   "the splash of the fish hitting the water. [Ambient "
                   "Sound] Soft creaking of the boat's wood and the "
                   "rhythmic swaying of the longtail."),
        "old": "adanest@kk-mac:~/ViMax/.working_dir/idea2video-local/"
               "scene_0/shots/1/video.mp4",
    },
]


def main():
    import imageio.v3 as iio
    import ltx_mlx.pipeline as lp

    t0 = time.time()
    pipe = lp.LTXPipeline(str(MODEL_DIR), checkpoint=CHECKPOINT)
    load_s = time.time() - t0

    rows = []
    for shot in SCENES:
        sid = shot["id"]
        out = OUT / f"{sid}-mlx.mp4"
        if out.exists() and out.stat().st_size > 10_000:
            rows.append({"id": sid, "status": "existing"})
            continue
        t = time.time()
        try:
            frames = pipe.generate(
                shot["prompt"], num_frames=FRAMES, height=HEIGHT,
                width=WIDTH, num_steps=STEPS, seed=SEED, image=None)
            iio.imwrite(str(out), frames, fps=FPS, codec="libx264",
                        macro_block_size=None)
            arr = np.asarray(frames)
            rows.append({
                "id": sid, "status": "done",
                "seconds": round(time.time() - t, 2),
                "frames": int(arr.shape[0]),
                "min": int(arr.min()), "max": int(arr.max()),
                "mean": round(float(arr.mean()), 2),
                "bytes": out.stat().st_size,
                "prompt_sha256": __import__("hashlib").sha256(
                    shot["prompt"].encode()).hexdigest()[:16],
                "old_artifact": shot["old"],
            })
        except Exception as ex:
            rows.append({"id": sid, "status": "error",
                         "error": f"{type(ex).__name__}: {ex}"[:300]})
            print(f"{sid}: ERROR {ex}", flush=True)

    result = {
        "pack": PACK_DIR.name,
        "lane": "kk-mac-mlx",
        "model": "LTX-Video 0.9.8-distilled 2B (baisampayans/ltx-mlx)",
        "checkpoint": CHECKPOINT,
        "conditioning": "prompt text via real T5 encoder (same as old "
                        "diffusers lane); t2v like the old render",
        "params": {"width": WIDTH, "height": HEIGHT, "frames": FRAMES,
                   "fps": FPS, "steps": STEPS, "seed": SEED},
        "model_load_seconds": round(load_s, 2),
        "shots": rows,
        "verified_nonblack": all(
            r["status"] == "existing"
            or (r.get("min", 1) < r.get("max", 0) and r.get("bytes", 0) > 10_000)
            for r in rows),
    }
    (OUT / "batch-result.json").write_text(json.dumps(result, indent=2) + "\n")

    verdict = ["# kk-mac-mlx-vimax-goldenhour-s0 verdict", "",
               "| shot | status | s | min | max | mean | bytes | prompt_sha |",
               "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        verdict.append(
            f"| {r['id']} | {r['status']} | {r.get('seconds', '-')} | "
            f"{r.get('min', '-')} | {r.get('max', '-')} | "
            f"{r.get('mean', '-')} | {r.get('bytes', '-')} | "
            f"{r.get('prompt_sha256', '-')} |")
    verdict += ["",
                f"model_load: {load_s:.1f}s",
                f"nonblack: {result['verified_nonblack']}",
                "old artifacts (untouched): adanest ViMax working_dir + "
                "tony-dell archive copy"]
    (OUT / "verdict.md").write_text("\n".join(verdict) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
