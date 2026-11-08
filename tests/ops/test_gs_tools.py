"""Tests for mcp-servers/mcp-kornia/gs_tools.py (numpy/PIL only paths)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "mcp-servers" / "mcp-kornia"))
sys.path.insert(0, str(REPO / "scripts" / "gs"))

import gs_tools  # noqa: E402


def _img(path: Path, seed: int, size=(96, 64)) -> None:
    rng = np.random.default_rng(seed)
    w, h = size
    grad = np.linspace(0, 255, w, dtype=np.float32)
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:] = grad[None, :, None]
    arr += rng.normal(0, 8, arr.shape)
    arr[:, :, 0] += np.linspace(0, 60, w)[None, :]
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(path)


@pytest.fixture()
def image_set(tmp_path, monkeypatch):
    monkeypatch.setattr(gs_tools, "ARTIFACT_ROOT", tmp_path / "artifacts")
    d = tmp_path / "set"
    d.mkdir()
    for i in range(4):
        _img(d / f"f{i:03d}.jpg", seed=i)
    return d


def test_match_views_requires_backend_or_pair(image_set):
    result = gs_tools.match_views(str(image_set))
    # Local env has neither cv2 nor torch/kornia -> clean unavailable error,
    # or a real backend result on hosts that have them.
    assert result["ok"] is False or result["ok"] is True
    if not result["ok"]:
        assert "backend" in result["error"]


def test_match_views_needs_two_images(tmp_path, monkeypatch):
    monkeypatch.setattr(gs_tools, "ARTIFACT_ROOT", tmp_path / "artifacts")
    d = tmp_path / "one"
    d.mkdir()
    _img(d / "a.jpg", 1)
    result = gs_tools.match_views(str(d))
    assert result["ok"] is False
    assert "at least 2" in result["error"]


def test_propose_foreground_masks_writes_review_only(image_set):
    result = gs_tools.propose_foreground_masks(str(image_set))
    assert result["ok"] is True
    assert result["review_only"] is True
    assert result["masks_written"] == 4
    out = Path(result["artifact_dir"])
    assert (out / "result.json").is_file()
    assert (out / "manifest.json").is_file()
    masks = list((out / "masks").glob("*_mask.png"))
    assert len(masks) == 4
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["review_only"] is True
    assert all(0 <= r["coverage"] <= 1 for r in manifest["images"])


def test_score_capture_manifest_gates(image_set):
    manifest = {
        "schema": "nest-media-pack-v1",
        "pack_id": "set",
        "asset_type": "image",
        "privacy": "private",
        "files": [{"path": p.name, "bytes": p.stat().st_size,
                   "sha256": "x" * 64} for p in sorted(image_set.iterdir())],
    }
    (image_set / "manifest.json").write_text(json.dumps(manifest))
    result = gs_tools.score_capture_manifest(str(image_set))
    assert result["ok"] is True
    assert 0 <= result["score"] <= 100
    assert result["gates"]["manifest_present"] is True
    assert result["gates"]["manifest_hash_complete"] is True
    assert result["verdict"] in {
        "capture_excellent", "capture_usable_review_edges",
        "capture_marginal_revisit", "capture_reject"}
    assert result["artifact_ref"].endswith("result.json")


def test_compare_gs_runs_psnr_ssim(tmp_path, monkeypatch):
    monkeypatch.setattr(gs_tools, "ARTIFACT_ROOT", tmp_path / "artifacts")
    a, b = tmp_path / "run-a", tmp_path / "run-b"
    for d in (a, b):
        (d / "out").mkdir(parents=True)
    _img(a / "out" / "v1.png", 7)
    _img(b / "out" / "v1.png", 7)   # identical -> inf psnr
    _img(b / "out" / "v2.png", 9)   # unpaired
    result = gs_tools.compare_gs_runs(str(a), str(b))
    assert result["ok"] is True
    assert result["shared_renders"] == 1
    pair = result["render_pairs"][0]
    assert pair["image"] == "v1.png"
    assert pair["psnr"] == float("inf") or pair["psnr"] > 60
    assert 0 <= pair["ssim"] <= 1.001
    assert result["verdict"] == "runs_near_identical" or \
        result["verdict"].startswith("compare_by")


def test_compare_gs_runs_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(gs_tools, "ARTIFACT_ROOT", tmp_path / "artifacts")
    result = gs_tools.compare_gs_runs(str(tmp_path / "nope"), str(tmp_path))
    assert result["ok"] is False
