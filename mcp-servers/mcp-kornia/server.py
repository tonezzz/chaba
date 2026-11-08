#!/usr/bin/env python3
"""FastMCP adapter for deterministic Gaussian capture evaluation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "scripts" / "gs"))

from image_set_eval import evaluate  # noqa: E402
import gs_tools  # noqa: E402

mcp = FastMCP("mcp-kornia")


@mcp.tool()
def inspect_image_set(image_dir: str) -> str:
    """Evaluate a local image set for Gaussian Splat capture readiness.

    Read-only. Returns dimensions, duplicate hashes, luma statistics,
    deterministic sharpness, gates, and a recommendation.
    """
    root = Path(image_dir).expanduser().resolve()
    if not root.is_dir():
        return json.dumps({"error": f"not a directory: {root}"})
    return json.dumps(evaluate(root), ensure_ascii=False, indent=2)


@mcp.tool()
def match_views(image_dir: str, max_pairs: int = 6,
                backend: str = "auto") -> str:
    """Estimate pairwise view overlap for a capture set.

    Uses cv2 SIFT/ORB + BFMatcher + RANSAC when available, else kornia
    DISK/LightGlue descriptor matches. Read-only; writes result.json under
    the artifact root and returns its artifact_ref.
    """
    return json.dumps(
        gs_tools.match_views(image_dir, max_pairs=max_pairs, backend=backend),
        ensure_ascii=False, indent=2)


@mcp.tool()
def propose_foreground_masks(image_dir: str, max_images: int = 14) -> str:
    """Propose review-only foreground masks for a capture set.

    Deterministic heuristic saliency; writes mask PNGs + manifest under the
    artifact root. Masks are proposals only — approval required before use.
    """
    return json.dumps(
        gs_tools.propose_foreground_masks(image_dir, max_images=max_images),
        ensure_ascii=False, indent=2)


@mcp.tool()
def score_capture_manifest(image_dir: str, manifest_path: str = "") -> str:
    """Score a capture set against image-quality and manifest gates.

    Combines image_set_eval metrics with pack-manifest fields; returns a
    0-100 score, per-gate detail, verdict, and artifact_ref.
    """
    return json.dumps(
        gs_tools.score_capture_manifest(image_dir, manifest_path=manifest_path),
        ensure_ascii=False, indent=2)


@mcp.tool()
def compare_gs_runs(run_a: str, run_b: str) -> str:
    """Compare two GS run directories.

    Paired renders get PSNR/SSIM; PLY gaussian counts, metrics.json fields,
    and registration artifacts are summarized. LPIPS only when torch+lpips
    exist. Read-only; returns artifact_ref.
    """
    return json.dumps(
        gs_tools.compare_gs_runs(run_a, run_b),
        ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
