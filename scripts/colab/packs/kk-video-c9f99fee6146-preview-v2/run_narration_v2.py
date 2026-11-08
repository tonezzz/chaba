#!/usr/bin/env python3
"""Generate private, subtitle-aligned VYNCX narration cues."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2}),(\d{3})", value)
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def parse_cues(path: Path) -> list[dict]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    cues = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise ValueError("malformed SRT cue")
        timing = re.fullmatch(
            r"\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*"
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*", lines[1])
        if not timing:
            raise ValueError("malformed SRT timing line")
        text = re.sub(r"<[^>]+>", "", "\n".join(lines[2:])).strip()
        if not text:
            raise ValueError("empty subtitle cue")
        start, end = map(parse_srt_time, timing.groups())
        if end - start != 15.0:
            raise ValueError("V2 narration cues must each occupy 15 seconds")
        cues.append({"start": start, "end": end, "text": text})
    if len(cues) != 4:
        raise ValueError(f"expected four Thai cues, got {len(cues)}")
    for index, cue in enumerate(cues):
        if cue["start"] != index * 15:
            raise ValueError("Thai subtitle cues must be contiguous 15-second slots")
    return cues


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-dir", type=Path, required=True)
    parser.add_argument("--probe-verdict", type=Path, required=True)
    parser.add_argument("--srt", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    import numpy as np
    import soundfile as sf
    import torch
    from f5_tts_th.tts import TTS

    voice_manifest = json.loads(
        (args.voice_dir / "manifest.json").read_text(encoding="utf-8"))
    if "private narration clone" not in voice_manifest.get("scope", ""):
        raise ValueError("voice manifest does not authorize private narration")
    if "no public" not in voice_manifest.get("sharing", ""):
        raise ValueError("voice manifest must prohibit public sharing")

    probe = json.loads(args.probe_verdict.read_text(encoding="utf-8"))
    if (probe.get("status") != "probe-pass"
            or probe.get("visibility") != "private"
            or probe.get("public_release") is not False):
        raise ValueError("completed private voice-clone probe did not pass")
    reference = probe["reference"]
    record = next(
        (item for item in voice_manifest.get("samples", [])
         if item.get("file") == reference["file"]),
        None)
    if not record:
        raise ValueError("probe reference is absent from the consent manifest")
    ref_path = args.voice_dir / record["file"]
    if (not ref_path.is_file()
            or ref_path.stat().st_size != record["bytes"]
            or sha256(ref_path) != record["sha256"]
            or record["sha256"] != reference["sha256"]):
        raise ValueError("selected voice reference no longer matches its hashes")
    used_seconds = float(reference["used_s"])
    if not 5 <= used_seconds <= 12:
        raise ValueError("selected reference duration is outside the qualified range")

    cues = parse_cues(args.srt)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix="kk-v2-narration-", dir=args.out_dir) as temp:
        temp_dir = Path(temp)
        ref_wav = temp_dir / "selected-reference.wav"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(ref_path),
            "-t", f"{used_seconds:.3f}", "-ac", "1", "-ar", "24000",
            "-c:a", "pcm_s16le", str(ref_wav)], check=True)

        has_cuda = torch.cuda.is_available()
        if not has_cuda:
            raise RuntimeError("private narration pack requires the approved CUDA lane")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        tts = TTS(model="v2")
        records = []
        padded_cues = []
        for index, cue in enumerate(cues, start=1):
            waveform = tts.infer(
                ref_audio=str(ref_wav),
                ref_text=reference["transcript"],
                gen_text=cue["text"],
                step=32,
                cfg=2.0,
                speed=1.0)
            if isinstance(waveform, tuple):
                waveform = waveform[0]
            waveform = np.asarray(waveform, dtype=np.float32).squeeze()
            if waveform.ndim > 1:
                waveform = waveform.mean(axis=0)
            if waveform.ndim != 1 or not np.isfinite(waveform).all():
                raise ValueError(f"cue {index} has invalid audio samples")
            duration = len(waveform) / 24000
            rms = float(np.sqrt(np.mean(np.square(waveform))))
            if not 1.0 <= duration < 15.0 or rms < 0.001:
                raise ValueError(
                    f"cue {index} failed audio QC: {duration:.2f}s RMS {rms:.5f}")
            cue_path = args.out_dir / f"cue-{index:02d}.wav"
            temp_path = temp_dir / cue_path.name
            sf.write(temp_path, waveform, 24000, subtype="PCM_16")
            os_replace(temp_path, cue_path)
            cue_info = sf.info(cue_path)
            if (cue_info.samplerate != 24000 or cue_info.channels != 1
                    or cue_info.frames == 0):
                raise ValueError(f"cue {index} failed WAV read-back verification")
            padded = np.pad(waveform, (0, 15 * 24000 - len(waveform)))
            padded_cues.append(padded)
            records.append({
                "cue": index,
                "text": cue["text"],
                "duration_s": round(duration, 3),
                "rms": round(rms, 5),
                "bytes": cue_path.stat().st_size,
                "sha256": sha256(cue_path),
            })

        narration = np.concatenate(padded_cues)
        narration_tmp = temp_dir / "narration.wav"
        sf.write(narration_tmp, narration, 24000, subtype="PCM_16")
        final_narration = args.out_dir / "narration.wav"
        os_replace(narration_tmp, final_narration)
        peak_gpu_gb = round(torch.cuda.max_memory_allocated() / 1e9, 2)
        del tts
        torch.cuda.empty_cache()

    metadata = {
        "schema": 1,
        "status": "pass",
        "scope": "private four-cue narration for Sacred Father V2",
        "engine": "VYNCX v2 / F5-TTS-TH",
        "consent_ref": "OPS-0952; private V2 approval",
        "reference": {
            "file": reference["file"],
            "sha256": reference["sha256"],
            "used_s": used_seconds,
        },
        "cues": records,
        "narration": {
            "file": final_narration.name,
            "sample_rate": 24000,
            "duration_s": len(narration) / 24000,
            "bytes": final_narration.stat().st_size,
            "sha256": sha256(final_narration),
        },
        "gpu_peak_gb": peak_gpu_gb,
        "visibility": "private",
        "public_release": False,
    }
    (args.out_dir / "narration-verdict.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "status": metadata["status"],
        "cues": len(records),
        "duration_s": metadata["narration"]["duration_s"],
        "gpu_peak_gb": peak_gpu_gb,
    }))
    return 0


def os_replace(source: Path, target: Path) -> None:
    import os
    os.replace(source, target)


if __name__ == "__main__":
    raise SystemExit(run())
