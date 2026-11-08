import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts/ops/video-qc.py"
SPEC = importlib.util.spec_from_file_location("video_qc", SCRIPT)
video_qc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video_qc)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_video_qc_accepts_generated_video(tmp_path):
    video = tmp_path / "sample.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", "testsrc=size=96x64:rate=8", "-t", "1",
        "-c:v", "libx264", str(video),
    ], check=True)
    result = video_qc.qc(video)
    assert result["ok"], result
    assert result["checks"]["has_video"]
    assert result["checks"]["video_decodes"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_video_qc_rejects_empty_black_video(tmp_path):
    video = tmp_path / "black.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", "color=c=black:size=96x64:rate=8", "-t", "1",
        "-c:v", "libx264", str(video),
    ], check=True)
    result = video_qc.qc(video)
    assert not result["ok"]
    assert "video appears entirely black" in result["errors"]
