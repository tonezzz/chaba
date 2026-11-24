#!/usr/bin/env python3
"""Privately qualify KK's voice references and synthesize one VYNCX smoke line."""

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


def command_json(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-400:]}")
    return json.loads(result.stdout)


def srt_first_line(path: Path) -> str:
    text_lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.isdigit() or "-->" in value:
            continue
        value = re.sub(r"<[^>]+>", "", value)
        if value:
            text_lines.append(value)
    if not text_lines:
        raise ValueError("Thai subtitle file contains no narration text")
    return text_lines[0]


def transcribe(model, wav_path: Path, max_ref_seconds: float) -> tuple[str, float, float, float]:
    import numpy as np
    import soundfile as sf

    # Decode with soundfile first; Colab's PyAV build can reject faster-whisper's
    # metadata_errors argument when it opens even a valid WAV path.
    audio, sample_rate = sf.read(wav_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != 16000:
        target_len = int(len(audio) * 16000 / sample_rate)
        audio = np.interp(
            np.linspace(0, len(audio) - 1, target_len),
            np.arange(len(audio)),
            audio).astype("float32")
    segments, info = model.transcribe(
        audio, language="th", beam_size=5, vad_filter=True)
    segments = list(segments)
    if not segments:
        return "", -99.0, 1.0, 0.0
    usable = [segment for segment in segments
              if segment.end <= max_ref_seconds]
    if not usable:
        return "", -99.0, 1.0, 0.0
    text = "".join(segment.text for segment in usable).strip()
    avg_logprob = sum(segment.avg_logprob for segment in usable) / len(usable)
    no_speech = sum(segment.no_speech_prob for segment in usable) / len(usable)
    return (text, float(avg_logprob), float(no_speech),
            float(usable[-1].end))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-dir", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    voice_dir = Path(args.voice_dir)
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = voice_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "private narration clone" not in manifest.get("scope", ""):
        raise ValueError("voice manifest does not authorize this private clone probe")
    if "no public" not in manifest.get("sharing", ""):
        raise ValueError("voice manifest must prohibit public sharing")

    from faster_whisper import WhisperModel
    import numpy as np
    import soundfile as sf

    candidates = []
    with tempfile.TemporaryDirectory(prefix="kk-voice-clone-") as temp:
        temp_dir = Path(temp)
        asr = WhisperModel("large-v3", device="cpu", compute_type="int8")
        for record in manifest["samples"]:
            source = voice_dir / record["file"]
            if not source.is_file() or source.stat().st_size != record["bytes"]:
                raise ValueError(f"voice source size mismatch: {source.name}")
            digest = sha256(source)
            if digest != record["sha256"]:
                raise ValueError(f"voice source hash mismatch: {source.name}")

            metadata = command_json([
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_name,sample_rate,channels:format=duration",
                "-of", "json", str(source)])
            duration = float(metadata["format"]["duration"])
            wav_path = temp_dir / f"{source.stem}-24k.wav"
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-i", str(source),
                "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
                str(wav_path)], check=True)
            asr_path = temp_dir / f"{source.stem}-16k.wav"
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-i", str(source),
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(asr_path)], check=True)
            text, logprob, no_speech, usable_end = transcribe(
                asr, asr_path, min(duration, 12.0))
            candidates.append({
                "name": source.name,
                "sha256": digest,
                "duration_s": round(duration, 3),
                "codec": metadata["streams"][0].get("codec_name"),
                "sample_rate": int(metadata["streams"][0].get("sample_rate", 0)),
                "channels": int(metadata["streams"][0].get("channels", 0)),
                "transcript": text,
                "asr_avg_logprob": round(logprob, 3),
                "asr_no_speech_prob": round(no_speech, 3),
                "usable_end_s": round(min(usable_end, 12.0), 3),
                "wav_path": str(wav_path),
            })

        eligible = [
            item for item in candidates
            if 5.0 <= item["usable_end_s"] <= 12.0
            and len(item["transcript"]) >= 8
            and item["asr_avg_logprob"] > -1.2
            and item["asr_no_speech_prob"] < 0.6
        ]
        if not eligible:
            (output_dir / "candidate-transcripts.md").write_text(
                render_candidates(candidates), encoding="utf-8")
            verdict = {
                "schema": 1,
                "status": "needs-better-reference",
                "scope": "private voice clone probe only",
                "consent_ref": "OPS-0952; Tony reports KK voice-clone permission",
                "public_release": False,
                "candidate_count": len(candidates),
            }
            (output_dir / "verdict.json").write_text(
                json.dumps(verdict, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            (output_dir / "report.md").write_text(
                "# KK voice-clone probe\n\nNo clip passed the reference-quality gate. "
                "No clone audio was generated. See private candidate transcripts.\n",
                encoding="utf-8")
            raise SystemExit("No transcripted 5-12s voice reference passed the gate")

        selected = max(
            eligible,
            key=lambda item: (
                item["asr_avg_logprob"],
                -abs(item["usable_end_s"] - 9.0)))
        ref_path = Path(selected["wav_path"])
        trimmed_ref = temp_dir / "selected-ref.wav"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", str(ref_path),
            "-t", str(selected["usable_end_s"]), "-ac", "1", "-ar", "24000",
            "-c:a", "pcm_s16le", str(trimmed_ref)], check=True)
        target = srt_first_line(Path(args.srt))
        del asr

        import torch
        from f5_tts_th.tts import TTS

        has_cuda = torch.cuda.is_available()
        if has_cuda:
            torch.cuda.reset_peak_memory_stats()
        tts = TTS(model="v2")
        waveform = tts.infer(
            ref_audio=str(trimmed_ref),
            ref_text=selected["transcript"],
            gen_text=target,
            step=32,
            cfg=2.0,
            speed=1.0)
        if isinstance(waveform, tuple):
            waveform = waveform[0]
        waveform = np.asarray(waveform, dtype=np.float32).squeeze()
        if waveform.ndim > 1:
            waveform = waveform.mean(axis=0)
        if not np.isfinite(waveform).all():
            raise ValueError("clone output contains non-finite samples")
        rms = float(np.sqrt(np.mean(np.square(waveform))))
        duration = len(waveform) / 24000
        if duration < 1.0 or rms < 0.001:
            raise ValueError("clone output is empty or effectively silent")
        clone_path = output_dir / "clone-smoke.wav"
        sf.write(clone_path, waveform, 24000)
        gpu_peak = round(torch.cuda.max_memory_allocated() / 1e9, 2) if has_cuda else 0.0

    candidates_path = output_dir / "candidate-transcripts.md"
    candidates_path.write_text(render_candidates(candidates), encoding="utf-8")
    verdict = {
        "schema": 1,
        "status": "probe-pass",
        "scope": "private one-line clone smoke only",
        "consent_ref": "OPS-0952; Tony reports KK voice-clone permission",
        "engine": "VYNCX v2 / F5-TTS-TH",
        "reference": {
            "file": selected["name"],
            "sha256": selected["sha256"],
            "duration_s": selected["duration_s"],
            "used_s": selected["usable_end_s"],
            "asr_avg_logprob": selected["asr_avg_logprob"],
            "transcript": selected["transcript"],
        },
        "target_text": target,
        "clone_audio": {
            "file": clone_path.name,
            "sample_rate": 24000,
            "duration_s": round(duration, 3),
            "rms": round(rms, 5),
            "bytes": clone_path.stat().st_size,
        },
        "gpu_peak_gb": gpu_peak,
        "visibility": "private",
        "public_release": False,
        "full_video_mux": False,
        "human_listen_required_before_full_narration": True,
    }
    (output_dir / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (output_dir / "report.md").write_text(
        "\n".join([
            "# Private KK voice-clone smoke",
            "",
            "- VYNCX v2 generated one private Thai line from the consented voice reference.",
            "- This is a smoke test, not the full narration and not muxed into video.",
            "- ASR transcript and candidate metadata are private artifacts; verify by listening before full narration.",
            f"- Output: `{clone_path.name}` ({duration:.2f}s, 24kHz, {clone_path.stat().st_size} bytes).",
            f"- Peak GPU allocation: {gpu_peak:.2f}GB.",
            "- No external TTS API or public release.",
            "",
        ]),
        encoding="utf-8")
    print(json.dumps({
        "status": verdict["status"],
        "reference": selected["name"],
        "output": clone_path.name,
        "duration_s": round(duration, 3),
        "gpu_peak_gb": gpu_peak,
    }))
    return 0


def render_candidates(candidates: list[dict]) -> str:
    lines = [
        "# Private KK reference-clip transcript candidates",
        "",
        "Generated locally with faster-whisper large-v3; transcript needs human review.",
        "",
        "| Clip | Duration | ASR avg logprob | No-speech | Transcript |",
        "|---|---:|---:|---:|---|",
    ]
    for item in candidates:
        text = item["transcript"].replace("|", "\\|")
        lines.append(
            f"| {item['name']} | {item['duration_s']:.2f}s | "
            f"{item['asr_avg_logprob']:.3f} | "
            f"{item['asr_no_speech_prob']:.3f} | {text} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
