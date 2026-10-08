#!/usr/bin/env python3
"""Generate fixture wavs for scripts/voice-bench.

English fixtures are synthesized with piper (the same TTS under bench —
circular for absolute WER but fine for latency); Thai fixtures use gTTS
since no Thai piper voice exists. Output: 16kHz mono wav next to manifest.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PIPER = ROOT / ".bench-tools/piper/piper"
VOICE = ROOT / ".bench-tools/voices/en_US-lessac-medium.onnx"


def synth_en(text: str, out: Path):
    p = subprocess.run(
        [str(PIPER), "-m", str(VOICE), "-f", str(out)],
        input=text.encode(), capture_output=True,
    )
    p.check_returncode()


def synth_th(text: str, out: Path):
    from gtts import gTTS
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = f.name
    gTTS(text=text, lang="th").save(tmp)
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-ar", "16000", "-ac", "1", str(out)],
        capture_output=True,
    ).check_returncode()


def main():
    manifest = yaml.safe_load((HERE / "fixtures/manifest.yml").read_text())
    for fx in manifest["fixtures"]:
        if fx.get("status") == "skipped" or not fx.get("wav"):
            continue
        out = HERE / "fixtures" / fx["wav"]
        if out.exists():
            print(f"skip {fx['id']} (exists)")
            continue
        if fx["lang"] == "th":
            synth_th(fx["text"], out)
        else:
            synth_en(fx["text"], out)
        # normalize en wavs to 16k mono too (piper emits 22050)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out), "-ar", "16000", "-ac", "1", str(out) + ".tmp.wav"],
            capture_output=True,
        ).check_returncode()
        (Path(str(out) + ".tmp.wav")).replace(out)
        print(f"gen  {fx['id']} -> {fx['wav']}")


if __name__ == "__main__":
    sys.exit(main())
