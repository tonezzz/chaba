#!/usr/bin/env python3
"""Bench ultralytics yolov8n / yolo11n ONNX on CPU and CUDA (GTX1650).

Measures per-image end-to-end predict latency (decode -> letterbox -> ORT
session.run -> NMS decode) and raw session.run latency, then scores the
top predicted class against manual labels (labels.yml).

Usage:
  .venv/bin/python bench.py            # full run, writes results.json
"""
import ctypes
import glob
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import yaml

# onnxruntime-gpu resolves CUDA/cuDNN at session-creation time; preload the
# pip-installed nvidia libs so CUDAExecutionProvider works without
# LD_LIBRARY_PATH being exported before process start.
_NV_ROOT = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "nvidia"
for _so in sorted(glob.glob(str(_NV_ROOT / "*" / "lib" / "*.so*"))):
    try:
        ctypes.CDLL(_so, mode=ctypes.RTLD_GLOBAL)
    except OSError:
        pass

HERE = Path(__file__).resolve().parent
SNAPS = HERE / "snaps"
MODELS = HERE / "models"
LABELS = HERE / "labels.yml"
OUT = HERE / "results.json"

IMGSZ = 640
CONF = 0.25
IOU = 0.45
REPS = 2  # timed passes over the dataset per config (first pass is warmup)

# COCO id -> bench class
COCO2LABEL = {
    0: "person",
    1: "vehicle", 2: "vehicle", 3: "vehicle", 5: "vehicle", 7: "vehicle",
    24: "package", 26: "package", 28: "package",
}


def letterbox(img, size=IMGSZ):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    out = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    out[top:top + nh, left:left + nw] = resized
    return out, r, left, top


def decode(pred, orig_shape, r, pad_x, pad_y):
    """pred: (1, 84, 8400) -> list of (label_class, conf, xyxy_orig)."""
    pred = pred[0].T  # (8400, 84)
    boxes, scores, cids = [], [], []
    for row in pred:
        cls_scores = row[4:]
        cid = int(np.argmax(cls_scores))
        conf = float(cls_scores[cid])
        if conf < CONF:
            continue
        cx, cy, w, h = row[:4]
        x1 = (cx - w / 2 - pad_x) / r
        y1 = (cy - h / 2 - pad_y) / r
        x2 = (cx + w / 2 - pad_x) / r
        y2 = (cy + h / 2 - pad_y) / r
        boxes.append([x1, y1, x2 - x1, y2 - y1])
        scores.append(conf)
        cids.append(cid)
    if not boxes:
        return []
    idxs = cv2.dnn.NMSBoxes(boxes, scores, CONF, IOU)
    H, W = orig_shape
    dets = []
    for i in np.atleast_1d(idxs).ravel():
        x, y, w, h = boxes[i]
        x2, y2 = min(x + w, W), min(y + h, H)
        dets.append({
            "coco_id": cids[i],
            "coco_name": COCO_NAMES[cids[i]],
            "cls": COCO2LABEL.get(cids[i], "other"),
            "conf": round(scores[i], 3),
            "xyxy": [round(max(x, 0)), round(max(y, 0)), round(x2), round(y2)],
        })
    return dets


COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


def run_config(model_path, provider, images, labels):
    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3
    sess = ort.InferenceSession(str(model_path), sess_options=sess_opts,
                                providers=[provider, "CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name

    per_image = {}
    lat_e2e, lat_ort = [], []

    for rep in range(REPS):
        timed = rep == REPS - 1
        for img_path in images:
            img = cv2.imread(str(img_path))
            lb, r, px, py = letterbox(img)
            blob = lb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
            t0 = time.perf_counter()
            pred = sess.run(None, {inp_name: blob})
            t_ort = time.perf_counter()
            dets = decode(pred[0], img.shape[:2], r, px, py)
            t1 = time.perf_counter()
            if timed:
                lat_ort.append((t_ort - t0) * 1000)
                lat_e2e.append((t1 - t0) * 1000)
                # predicted class = bench-class of the most confident
                # mapped detection; 'other' dets don't promote a class
                mapped = [d for d in dets if d["cls"] != "other"]
                pred_cls = "none"
                if mapped:
                    pred_cls = max(mapped, key=lambda d: d["conf"])["cls"]
                # alt rule: person presence wins (security-cam semantics)
                classes = {d["cls"] for d in mapped}
                pred_alt = ("person" if "person" in classes
                            else "package" if "package" in classes
                            else "vehicle" if "vehicle" in classes else "none")
                per_image[img_path.name] = {
                    "true": labels[img_path.name],
                    "pred": pred_cls,
                    "correct": pred_cls == labels[img_path.name],
                    "pred_alt": pred_alt,
                    "correct_alt": pred_alt == labels[img_path.name],
                    "lat_ms": round((t1 - t0) * 1000, 1),
                    "n_dets": len(dets),
                    "dets": dets,
                }

    def pct(a, p):
        a = sorted(a)
        k = max(0, min(len(a) - 1, int(round((p / 100) * (len(a) - 1)))))
        return round(a[k], 1)

    n = len(per_image)
    correct = sum(1 for v in per_image.values() if v["correct"])
    correct_alt = sum(1 for v in per_image.values() if v["correct_alt"])
    return {
        "provider": provider,
        "n_images": n,
        "p50_e2e_ms": pct(lat_e2e, 50),
        "p95_e2e_ms": pct(lat_e2e, 95),
        "p50_ort_ms": pct(lat_ort, 50),
        "p95_ort_ms": pct(lat_ort, 95),
        "correct": correct,
        "correct_rate": round(correct / n, 3),
        "correct_alt": correct_alt,
        "correct_rate_alt": round(correct_alt / n, 3),
        "per_image": per_image,
    }


def main():
    labels = yaml.safe_load(LABELS.read_text())["labels"]
    images = sorted(p for p in SNAPS.iterdir()
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png")
                    and p.name in labels)
    missing = [p.name for p in images if p.name not in labels]
    assert not missing, missing
    print(f"{len(images)} labeled images")

    results = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "imgsz": IMGSZ, "conf": CONF, "iou": IOU,
               "reps": REPS, "configs": {}}
    for model in ["yolov8n.onnx", "yolo11n.onnx"]:
        for provider in ["CPUExecutionProvider", "CUDAExecutionProvider"]:
            key = f"{model.replace('.onnx','')}@{'cuda' if 'CUDA' in provider else 'cpu'}"
            print(f"== {key}", flush=True)
            results["configs"][key] = run_config(
                MODELS / model, provider, images, labels)
            c = results["configs"][key]
            print(f"   p50={c['p50_e2e_ms']}ms p95={c['p95_e2e_ms']}ms "
                  f"correct={c['correct']}/{c['n_images']} "
                  f"({c['correct_rate']:.0%})", flush=True)

    OUT.write_text(json.dumps(results, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
