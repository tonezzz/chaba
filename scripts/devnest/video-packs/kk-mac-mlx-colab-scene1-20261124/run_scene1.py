#!/usr/bin/env python3
"""kk-mac-mlx-colab-scene1 — MLX rerender of old Colab scene1
(golden-hour-catch) shots 0-2 on the proven KK-Mac MLX lane.

Same conditioning as the 2026-10-22 CUDA renders: the T5 prompt embeds
(.pt, 4-key format) are injected directly — text_encoder weights are
never loaded, so conditioning is bit-identical to the CUDA lane. The
old renders were t2v (verified on scene0: Drive keyframes are
pixel-identical to rendered first/last frames, PSNR=inf), so no image
conditioning here.

STAGED-ON-APPROVAL: this pack is defined repo-side only. Stage to
gdrive:ada-nest/kk-mac-video-pilot/packs/ only after the scene0 control
passes and KK reviews quality. Old outputs are never touched.
"""
import json
import os
import pickle
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

PACK_DIR = Path(os.environ.get("PACK_DIR", os.getcwd()))
HOME = Path(os.path.expanduser("~"))
sys.path.insert(0, str(HOME / "kk-video" / "ltx-mlx"))

MODEL_DIR = HOME / "kk-video" / "ltx-mlx" / "models" / "LTX"
CHECKPOINT = "ltxv-2b-0.9.8-distilled.safetensors"
EMB_DIR = PACK_DIR / "inputs"
OUT = PACK_DIR / "out"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT, FRAMES, FPS = 640, 384, 49, 24
STEPS = 8
SEED = 42

SCENES = [
    {"id": "s1shot0", "embed": "shot0.pt",
     "old": "renders/ltx_s1_shot0_20261022-1236.mp4"},
    {"id": "s1shot1", "embed": "shot1.pt",
     "old": "renders/ltx_s1_shot1_20261022-1236.mp4"},
    {"id": "s1shot2", "embed": "shot2.pt",
     "old": "renders/ltx_s1_shot2_20261022-1236.mp4"},
]


def load_pt(path):
    """Torch-free .pt reader (same contract as the proven preview-mac
    pack): zip archive, pickle dict, raw storage buffers."""
    zf = zipfile.ZipFile(path)
    pkl_name = next(n for n in zf.namelist() if n.endswith("data.pkl"))
    root = pkl_name.rsplit("/", 1)[0]

    def rebuild(storage, offset, size, stride, *a):
        _, st_name, key, _loc, numel = storage
        dt = {"FloatStorage": np.float32, "BFloat16Storage": np.uint16,
              "DoubleStorage": np.float64, "HalfStorage": np.float16,
              "LongStorage": np.int64, "IntStorage": np.int32,
              "ShortStorage": np.int16, "ByteStorage": np.uint8,
              "BoolStorage": np.uint8}[st_name]
        arr = np.frombuffer(zf.read(f"{root}/data/{key}"), dtype=dt)
        if st_name == "BFloat16Storage":
            arr = (arr.astype(np.uint32) << 16).view(np.float32)
        return arr[offset:offset + int(np.prod(size))].reshape(size)

    class U(pickle.Unpickler):
        def find_class(self, mod, name):
            if "rebuild_tensor" in name or "rebuild_parameter" in name:
                return rebuild
            if name == "OrderedDict":
                from collections import OrderedDict
                return OrderedDict
            if name.endswith("Storage"):
                return name
            return lambda *a: None

        def persistent_load(self, pid):
            return pid

    return U(zf.open(pkl_name)).load()


def main():
    import mlx.core as mx
    import imageio.v3 as iio
    import ltx_mlx.pipeline as lp

    lp.load_t5_encoder = lambda *a, **k: None
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
        d = load_pt(EMB_DIR / shot["embed"])
        emb = mx.array(d["prompt_embeds"].astype(np.float32)).astype(mx.bfloat16)
        mask = mx.array(d["prompt_attention_mask"].astype(np.float32))

        def fake_t5(ids, mask=None, _e=emb):
            return _e

        class FakeTok:
            def encode(self, prompt, _m=mask):
                return None, _m

        pipe.t5 = fake_t5
        pipe.tokenizer = FakeTok()

        t = time.time()
        try:
            frames = pipe.generate(
                "x", num_frames=FRAMES, height=HEIGHT, width=WIDTH,
                num_steps=STEPS, seed=SEED, image=None)
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
        "conditioning": "T5 prompt_embeds injected from inputs/*.pt "
                        "(bit-identical to 2026-10-22 CUDA renders); "
                        "t2v, no image condition",
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

    verdict = ["# kk-mac-mlx-colab-scene1 verdict", "",
               "| shot | status | s | min | max | mean | bytes |",
               "|---|---|---|---|---|---|---|"]
    for r in rows:
        verdict.append(
            f"| {r['id']} | {r['status']} | {r.get('seconds', '-')} | "
            f"{r.get('min', '-')} | {r.get('max', '-')} | "
            f"{r.get('mean', '-')} | {r.get('bytes', '-')} |")
    verdict += ["",
                f"model_load: {load_s:.1f}s",
                f"nonblack: {result['verified_nonblack']}",
                "old artifacts (untouched): " +
                ", ".join(s["old"] for s in SCENES)]
    (OUT / "verdict.md").write_text("\n".join(verdict) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
