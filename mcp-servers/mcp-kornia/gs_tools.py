#!/usr/bin/env python3
"""Pure evaluation helpers for the read-only Kornia MCP server.

Every function is deterministic where possible and degrades cleanly when
optional heavy dependencies (torch/kornia/opencv/lpips) are absent. Results
are written under GS_EVAL_ARTIFACT_ROOT so callers get a durable
artifact_ref instead of chat-only output.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
ARTIFACT_ROOT = Path(
    os.environ.get(
        "GS_EVAL_ARTIFACT_ROOT",
        str(Path.home() / ".local" / "share" / "gs-eval-artifacts"),
    )
)


def _images(root: Path) -> list[Path]:
    return sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in EXTS
    )


def _artifact_dir(tool: str, dataset: str) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    slug = "".join(ch if ch.isalnum() or ch in "-_." else "-"
                   for ch in Path(dataset).name)[:60]
    out = ARTIFACT_ROOT / tool / f"{slug}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_result(out: Path, payload: dict) -> dict:
    path = out / "result.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    payload["artifact_ref"] = str(path)
    return payload


def _load_rgb(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        if size is not None and rgb.size != size:
            rgb = rgb.resize(size)
        return np.asarray(rgb, dtype=np.float32)


# ---------------------------------------------------------------- match_views

def _match_cv2(kp1, des1, kp2, des2):
    """SIFT/ORB + BFMatcher + RANSAC fundamental matrix via OpenCV."""
    import cv2  # type: ignore

    if des1 is None or des2 is None or len(des1) < 8 or len(des2) < 8:
        return None
    bf = cv2.BFMatcher(cv2.NORM_L2 if des1.dtype == np.float32 else cv2.NORM_HAMMING)
    raw = bf.knnMatch(des1, des2, k=2)
    good = [m for pair in raw if len(pair) == 2
            for m, n in [pair] if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return {"matches": len(good), "inliers": 0, "inlier_ratio": 0.0}
    p1 = np.float32([kp1[m.queryIdx].pt for m in good])
    p2 = np.float32([kp2[m.trainIdx].pt for m in good])
    fm, mask = cv2.findFundamentalMat(p1, p2, cv2.FM_RANSAC, 3.0, 0.99)
    inl = int(mask.sum()) if mask is not None else 0
    return {"matches": len(good), "inliers": inl,
            "inlier_ratio": round(inl / len(good), 4)}


def _detect_match_cv2(path_a: Path, path_b: Path):
    import cv2  # type: ignore

    a = _load_rgb(path_a)
    b = _load_rgb(path_b)
    def downscale(g):
        h, w = g.shape
        if max(h, w) > 1024:
            s = 1024.0 / max(h, w)
            return cv2.resize(g, (int(w * s), int(h * s)),
                              interpolation=cv2.INTER_AREA)
        return g
    g1 = downscale(cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_RGB2GRAY))
    g2 = downscale(cv2.cvtColor(b.astype(np.uint8), cv2.COLOR_RGB2GRAY))
    detector = cv2.SIFT_create() if hasattr(cv2, "SIFT_create") else cv2.ORB_create(2000)
    kp1, des1 = detector.detectAndCompute(g1, None)
    kp2, des2 = detector.detectAndCompute(g2, None)
    if des1 is None or des2 is None:
        return {"error": "no descriptors", "inliers": 0}
    return _match_cv2(kp1, des1, kp2, des2)


def _detect_match_kornia(path_a: Path, path_b: Path):
    """DISK + LightGlue when torch/kornia are installed."""
    import torch  # type: ignore
    import kornia  # type: noqa: F401  # type: ignore
    from kornia.feature import DISK, LightGlue, SIFTFeature, match_adalam  # type: ignore

    device = "cpu"
    disk = DISK().eval().to(device)
    sift = SIFTFeature().eval().to(device)
    gl = LightGlue().eval().to(device)

    def feats(path):
        img = torch.from_numpy(_load_rgb(path)).permute(2, 0, 1)[None] / 255.0
        img = img.to(device)
        with torch.no_grad():
            lf = disk(img)
            sf = sift(img)
            desc = lf.descriptors if lf.descriptors is not None else sf.descriptors
            kps = lf.keypoints if lf.keypoints is not None else sf.keypoints
        return kps[0], desc[0]

    k1, d1 = feats(path_a)
    k2, d2 = feats(path_b)
    with torch.no_grad():
        m = gl({"image0": d1[None], "image1": d2[None]})
    # count mutual nearest neighbours as a coarse inlier proxy when no
    # geometric verification is requested; callers wanting RANSAC should
    # use the cv2 backend.
    return {"matches": int(m["matches"].shape[-1]) if "matches" in m else 0,
            "inliers": None, "backend": "kornia-disk-lightglue",
            "note": "descriptor matches only; run cv2 backend for RANSAC inliers"}


def _matcher_backends() -> dict:
    backends = {}
    try:
        import cv2  # noqa: F401
        backends["cv2"] = True
    except Exception:
        backends["cv2"] = False
    try:
        import torch, kornia  # noqa: F401
        backends["kornia"] = True
    except Exception:
        backends["kornia"] = False
    return backends


def match_views(image_dir: str, max_pairs: int = 6,
                backend: str = "auto") -> dict:
    """Estimate pairwise view overlap for a capture set.

    Pairs are consecutive frames plus a wrap-around pair. Returns per-pair
    match/inlier stats and an overlap verdict. Read-only; writes result.json
    under the artifact root.
    """
    root = Path(image_dir).expanduser().resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"not a directory: {root}"}
    images = _images(root)
    if len(images) < 2:
        return {"ok": False, "error": "need at least 2 images",
                "images": len(images)}

    backends = _matcher_backends()
    chosen = backend
    if chosen == "auto":
        chosen = "cv2" if backends["cv2"] else ("kornia" if backends["kornia"] else None)
    if chosen is None:
        return {"ok": False, "error": "no matcher backend available",
                "backends": backends,
                "hint": "install opencv-python or torch+kornia on the worker"}

    n = len(images)
    idx_pairs = [(i, i + 1) for i in range(n - 1)] + [(n - 1, 0)]
    if len(idx_pairs) > max_pairs:
        step = max(1, len(idx_pairs) // max_pairs)
        idx_pairs = idx_pairs[::step][:max_pairs]

    pairs = []
    fn = _detect_match_cv2 if chosen == "cv2" else _detect_match_kornia
    for i, j in idx_pairs:
        try:
            res = fn(images[i], images[j])
        except Exception as exc:  # keep one bad pair from killing the report
            res = {"error": str(exc), "inliers": 0}
        res.update({"a": images[i].name, "b": images[j].name})
        pairs.append(res)

    inliers = [p.get("inliers") for p in pairs if isinstance(p.get("inliers"), int)]
    median_inliers = float(np.median(inliers)) if inliers else 0.0
    weak = [p["a"] for p in pairs
            if isinstance(p.get("inliers"), int) and p["inliers"] < 15]
    verdict = ("views_well_linked" if median_inliers >= 30 and not weak
               else "weak_overlap_review_pairs" if median_inliers >= 10
               else "insufficient_overlap_revisit_capture")

    payload = {
        "ok": True,
        "dataset": str(root),
        "backend": chosen,
        "backends_available": backends,
        "pairs_tested": len(pairs),
        "median_inliers": median_inliers,
        "weak_pairs": weak,
        "pairs": pairs,
        "verdict": verdict,
        "read_only": True,
    }
    out = _artifact_dir("match_views", root.name)
    return _write_result(out, payload)


# ------------------------------------------------------- propose_foreground_masks

def _saliency_mask(rgb: np.ndarray) -> np.ndarray:
    """Heuristic foreground proposal: distance from a blurred background
    estimate, thresholded at mean+std, centre-weighted. Review-only.
    Computed on a downscaled copy (max dim 512) for speed, then resized."""
    from PIL import ImageFilter
    h0, w0 = rgb.shape[:2]
    scale = min(1.0, 512.0 / max(h0, w0))
    small = Image.fromarray(rgb.astype(np.uint8))
    if scale < 1.0:
        small = small.resize(
            (max(1, int(w0 * scale)), max(1, int(h0 * scale))),
            Image.Resampling.BILINEAR)
    bg = np.asarray(small.filter(ImageFilter.GaussianBlur(15)),
                    dtype=np.float32)
    fg = np.asarray(small, dtype=np.float32)
    dist = np.linalg.norm(fg - bg, axis=2)
    thr = dist.mean() + dist.std()
    mask = (dist > thr).astype(np.float32)
    h, w = mask.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cx = np.exp(-(((xx - w / 2) / (w * 0.75)) ** 2 +
                  ((yy - h / 2) / (h * 0.75)) ** 2))
    mask = mask * (0.5 + 0.5 * cx)
    mask[mask < 0.18] = 0
    out = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    if scale < 1.0:
        out = out.resize((w0, h0), Image.Resampling.BILINEAR)
    return np.asarray(out, dtype=np.uint8)


def propose_foreground_masks(image_dir: str, max_images: int = 14) -> dict:
    """Propose review-only foreground masks for a capture set.

    Deterministic heuristic saliency (no learned model): writes one L-mode
    PNG per image plus manifest.json under the artifact dir. Masks are
    proposals only — a human/agent must approve before masking is used for
    training. Read-only w.r.t. the source images.
    """
    root = Path(image_dir).expanduser().resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"not a directory: {root}"}
    images = _images(root)[:max_images]
    if not images:
        return {"ok": False, "error": "no images found"}

    out = _artifact_dir("propose_foreground_masks", root.name)
    masks_dir = out / "masks"
    masks_dir.mkdir(exist_ok=True)
    rows = []
    for path in images:
        rgb = _load_rgb(path)
        mask = _saliency_mask(rgb)
        name = path.stem + "_mask.png"
        Image.fromarray(mask, mode="L").save(masks_dir / name)
        rows.append({
            "image": path.name,
            "mask": f"masks/{name}",
            "coverage": round(float((mask > 0).mean()), 4),
        })
    manifest = {
        "method": "heuristic_saliency_v1",
        "review_only": True,
        "note": "proposals only — approval required before use in training",
        "images": rows,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    payload = {
        "ok": True,
        "dataset": str(root),
        "masks_written": len(rows),
        "mean_coverage": round(float(np.mean([r["coverage"] for r in rows])), 4),
        "review_only": True,
        "artifact_dir": str(out),
        "read_only": True,
    }
    return _write_result(out, payload)


# ------------------------------------------------------- score_capture_manifest

def score_capture_manifest(image_dir: str, manifest_path: str = "") -> dict:
    """Score a capture set against manifest + image-quality gates.

    Combines image_set_eval metrics with pack-manifest fields when a
    manifest.json is present (or an explicit path is given). Returns a
    0-100 score, per-gate detail, and a verdict.
    """
    sys_path_added = False
    try:
        from image_set_eval import evaluate  # type: ignore
    except ImportError:
        import sys
        script = Path(__file__).parents[2] / "scripts" / "gs" / "image_set_eval.py"
        sys.path.insert(0, str(script.parent))
        from image_set_eval import evaluate  # type: ignore
        sys_path_added = True

    root = Path(image_dir).expanduser().resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"not a directory: {root}"}
    metrics = evaluate(root)

    mpath = Path(manifest_path).expanduser() if manifest_path else root / "manifest.json"
    manifest = None
    if mpath.is_file():
        try:
            manifest = json.loads(mpath.read_text())
        except Exception as exc:
            return {"ok": False, "error": f"manifest unreadable: {exc}"}

    gates = dict(metrics["gates"])
    gates["manifest_present"] = manifest is not None
    if manifest is not None:
        files = manifest.get("files") or []
        hashed = sum(1 for f in files if f.get("sha256"))
        gates["manifest_hash_complete"] = bool(files) and hashed == len(files)
        gates["manifest_file_count_matches"] = (
            len(files) == metrics["images"] or not files
        )
        gates["privacy_declared"] = bool(manifest.get("privacy"))
    else:
        gates["manifest_hash_complete"] = False
        gates["manifest_file_count_matches"] = False
        gates["privacy_declared"] = False

    score = 0
    score += 20 if gates["non_empty"] else 0
    score += 15 if gates["same_dimensions"] else 0
    score += 15 if gates["duplicate_groups"] == 0 else 0
    score += 20 if gates["min_sharpness"] >= 5 else 0
    score += 10 if gates["sharpness_median"] >= 30 else 0
    score += 10 if gates["manifest_present"] else 0
    score += 10 if gates.get("manifest_hash_complete") else 0

    if score >= 90:
        verdict = "capture_excellent"
    elif score >= 70:
        verdict = "capture_usable_review_edges"
    elif score >= 40:
        verdict = "capture_marginal_revisit"
    else:
        verdict = "capture_reject"

    payload = {
        "ok": True,
        "dataset": str(root),
        "score": score,
        "verdict": verdict,
        "gates": gates,
        "metrics": metrics["gates"],
        "recommendation": metrics["recommendation"],
        "manifest": ({
            "pack_id": manifest.get("pack_id"),
            "path_id": manifest.get("path_id"),
            "privacy": manifest.get("privacy"),
            "file_count": len(manifest.get("files") or []),
        } if manifest else None),
        "read_only": True,
    }
    out = _artifact_dir("score_capture_manifest", root.name)
    return _write_result(out, payload)


# ------------------------------------------------------------ compare_gs_runs

def _find_images(root: Path) -> dict[str, Path]:
    found = {}
    for sub in ("out", "validation", "renders", "images", "."):
        d = root / sub if sub != "." else root
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in EXTS and p.name not in found:
                found[p.name] = str(p)
    return found


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a - b) ** 2))
    if mse == 0:
        return float("inf")
    return float(20 * np.log10(255.0 / np.sqrt(mse)))


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Single-scale SSIM on luma, 7x7-ish window via uniform filters."""
    def lum(x):
        return (0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2])
    def box(x, k=7):
        # integral-image box filter
        c = np.pad(x, ((k // 2, k // 2), (k // 2, k // 2)), mode="edge").cumsum(0).cumsum(1)
        return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
    x, y = lum(a), lum(b)
    mx, my = box(x), box(y)
    vx = np.clip(box(x * x) - mx * mx, 0, None)
    vy = np.clip(box(y * y) - my * my, 0, None)
    cxy = box(x * y) - mx * my
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mx * my + c1) * (2 * cxy + c2)) / \
        ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(s.mean())


def _ply_gaussians(path: Path) -> int | None:
    try:
        with path.open("rb") as fh:
            header = fh.read(4096).decode("latin1", "ignore")
        for line in header.splitlines():
            if line.startswith("element vertex"):
                return int(line.split()[-1])
    except Exception:
        return None
    return None


def _run_summary(root: Path) -> dict:
    summary = {"dir": str(root), "exists": root.is_dir()}
    if not root.is_dir():
        return summary
    summary["images"] = _find_images(root)
    metrics = root / "metrics.json"
    if metrics.is_file():
        try:
            summary["metrics"] = json.loads(metrics.read_text())
        except Exception:
            summary["metrics"] = {"unreadable": True}
    plys = sorted(root.rglob("*.ply"))
    summary["ply"] = [{"file": str(p.relative_to(root)),
                       "gaussians": _ply_gaussians(p)} for p in plys[:5]]
    for marker in ("point_cloud", "sparse", "images.bin", "cameras.bin"):
        hits = list(root.rglob(f"*{marker}*"))[:3]
        if hits:
            summary.setdefault("registration", []).append(
                str(hits[0].relative_to(root)))
    return summary


def compare_gs_runs(run_a: str, run_b: str) -> dict:
    """Compare two GS run directories: paired renders (PSNR/SSIM), PLY
    gaussian counts, metrics.json fields, registration artifacts.

    LPIPS is reported as skipped unless torch+lpips exist. Read-only.
    """
    a, b = Path(run_a).expanduser().resolve(), Path(run_b).expanduser().resolve()
    sa, sb = _run_summary(a), _run_summary(b)
    if not a.is_dir() or not b.is_dir():
        return {"ok": False, "error": "run directory missing",
                "run_a": sa, "run_b": sb}

    common = sorted(set(sa["images"]) & set(sb["images"]))
    pairs = []
    for name in common:
        try:
            ia = _load_rgb(Path(sa["images"][name]))
            ib = _load_rgb(Path(sb["images"][name]), size=ia.shape[1::-1])
            pairs.append({"image": name,
                          "psnr": round(_psnr(ia, ib), 3),
                          "ssim": round(_ssim(ia, ib), 4)})
        except Exception as exc:
            pairs.append({"image": name, "error": str(exc)})

    lpips_status = "skipped_no_torch_lpips"
    try:
        import lpips  # noqa: F401
        import torch  # noqa: F401
        lpips_status = "available_not_run"
    except Exception:
        pass

    ga = [p["gaussians"] for p in sa.get("ply", []) if p.get("gaussians")]
    gb = [p["gaussians"] for p in sb.get("ply", []) if p.get("gaussians")]
    psnr_vals = [p["psnr"] for p in pairs if "psnr" in p and p["psnr"] != float("inf")]
    ssim_vals = [p["ssim"] for p in pairs if "ssim" in p]

    if not common:
        verdict = "incomparable_no_shared_renders"
    elif psnr_vals and float(np.mean(psnr_vals)) >= 35 and \
            float(np.mean(ssim_vals or [0])) >= 0.9:
        verdict = "runs_near_identical"
    elif ga and gb:
        verdict = "compare_by_metrics_ply_counts_differ" \
            if ga[0] != gb[0] else "compare_by_metrics"
    else:
        verdict = "compare_by_metrics"

    payload = {
        "ok": True,
        "run_a": sa, "run_b": sb,
        "shared_renders": len(common),
        "render_pairs": pairs,
        "mean_psnr": round(float(np.mean(psnr_vals)), 3) if psnr_vals else None,
        "mean_ssim": round(float(np.mean(ssim_vals)), 4) if ssim_vals else None,
        "lpips": lpips_status,
        "ply_gaussians_a": ga, "ply_gaussians_b": gb,
        "verdict": verdict,
        "read_only": True,
    }
    out = _artifact_dir("compare_gs_runs",
                        f"{a.name}-vs-{b.name}")
    return _write_result(out, payload)
