#!/usr/bin/env python3
"""upscale-eval.py — OPS-1077 upscaler evaluation harness for the Adobe Stock pipeline.

Runs an image through an upscale backend, then scores the result with
no-reference + roundtrip metrics and emits a JSON receipt (same convention
as land-render.py / campaign-status.py).

Metrics (no ground truth exists for generated images, so we measure
consistency + sharpness, and leave semantic QC to Tony):
  - laplacian_var: sharpness proxy (higher = sharper)
  - roundtrip_psnr / roundtrip_ssim: downscale(upscaled) vs source
  - dims, bytes, wall_s

Backends:
  realesrgan-ncnn  — xinntao realesrgan-ncnn-vulkan binary (CPU or Vulkan)

Usage:
  upscale-eval.py --input comp-d.png --backend realesrgan-ncnn \
      --ncnn-bin /tmp/realesrgan-ncnn/realesrgan-ncnn-vulkan \
      --ncnn-model-dir /tmp/realesrgan-ncnn/models \
      --model realesrgan-x4plus --scale 4 \
      --out-dir /tmp/sr-out --unsharp 60 \
      --report /tmp/upscale-eval-report.json
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np


def load_rgb(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"cannot read image: {path}")
    return img


def laplacian_var(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """SSIM on grayscale, 7x7 gaussian window (Wang et al. constants)."""
    g1 = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float64)
    g2 = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float64)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    win = cv2.getGaussianKernel(11, 1.5)
    win = np.outer(win, win.T)

    def filt(x):
        return cv2.filter2D(x, -1, win, borderType=cv2.BORDER_REFLECT)

    mu1, mu2 = filt(g1), filt(g2)
    mu1_sq, mu2_sq, mu12 = mu1 * mu1, mu2 * mu2, mu1 * mu2
    s1 = filt(g1 * g1) - mu1_sq
    s2 = filt(g2 * g2) - mu2_sq
    s12 = filt(g1 * g2) - mu12
    h = win.shape[0] // 2
    sl = (slice(h, -h), slice(h, -h))
    num = (2 * mu12[sl] + C1) * (2 * s12[sl] + C2)
    den = (mu1_sq[sl] + mu2_sq[sl] + C1) * (s1[sl] + s2[sl] + C2)
    return float(np.mean(num / den))


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    diff = a.astype(np.float64) - b.astype(np.float64)
    mse = float(np.mean(diff * diff))
    return float("inf") if mse == 0 else 10 * np.log10((255.0 ** 2) / mse)


def unsharp(img: np.ndarray, percent: int, radius: float = 2.0) -> np.ndarray:
    """PIL-equivalent unsharp mask via cv2 Gaussian blur."""
    blurred = cv2.GaussianBlur(img, (0, 0), radius)
    amount = percent / 100.0
    return cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)


def run_ncnn(src: Path, dst: Path, bin_path: Path, model_dir: Path,
             model: str, scale: int) -> float:
    t0 = time.time()
    cmd = [str(bin_path), "-i", str(src), "-o", str(dst),
           "-n", model, "-s", str(scale), "-f", "png",
           "-m", str(model_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"ncnn failed rc={proc.returncode}: {proc.stderr[-500:]}")
    return time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="source image path")
    ap.add_argument("--backend", default="realesrgan-ncnn",
                    choices=["realesrgan-ncnn"])
    ap.add_argument("--ncnn-bin", help="path to realesrgan-ncnn-vulkan binary")
    ap.add_argument("--ncnn-model-dir", help="path to ncnn model dir")
    ap.add_argument("--model", default="realesrgan-x4plus")
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--out-dir", required=True, help="output directory")
    ap.add_argument("--unsharp", type=int, default=0,
                    help="post-upscale unsharp percent (0=off, e.g. 60)")
    ap.add_argument("--report", help="write JSON receipt here")
    args = ap.parse_args()

    src = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    src_img = load_rgb(str(src))
    h, w = src_img.shape[:2]

    if args.backend == "realesrgan-ncnn":
        if not args.ncnn_bin or not args.ncnn_model_dir:
            raise SystemExit("--ncnn-bin and --ncnn-model-dir required")
        raw_out = out_dir / f"{stem}-{args.model}-x{args.scale}.png"
        wall = run_ncnn(src, raw_out, Path(args.ncnn_bin),
                        Path(args.ncnn_model_dir), args.model, args.scale)
    else:
        raise SystemExit(f"unknown backend {args.backend}")

    up_img = load_rgb(str(raw_out))
    if args.unsharp:
        up_img = unsharp(up_img, args.unsharp)
        out_path = out_dir / f"{stem}-{args.model}-x{args.scale}-sharp{args.unsharp}.png"
        cv2.imwrite(str(out_path), up_img)
    else:
        out_path = raw_out

    uh, uw = up_img.shape[:2]
    rt = cv2.resize(up_img, (w, h), interpolation=cv2.INTER_AREA)

    receipt = {
        "tool": "upscale-eval.py",
        "backend": args.backend,
        "model": args.model,
        "scale": args.scale,
        "unsharp": args.unsharp,
        "source": {"path": str(src), "width": w, "height": h},
        "output": {"path": str(out_path), "width": uw, "height": uh,
                   "megapixels": round(uw * uh / 1e6, 2)},
        "metrics": {
            "laplacian_var_source": round(laplacian_var(src_img), 2),
            "laplacian_var_output": round(laplacian_var(up_img), 2),
            "roundtrip_psnr_db": round(psnr(src_img, rt), 2),
            "roundtrip_ssim": round(ssim(src_img, rt), 4),
        },
        "wall_s": round(wall, 1),
        "note": "roundtrip metrics measure self-consistency, not ground truth; "
                "semantic QC remains human (Tony).",
    }
    text = json.dumps(receipt, indent=1)
    if args.report:
        Path(args.report).write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
