#!/usr/bin/env python3
"""Generate voice-bench fixture audio from fixtures/manifest.yml.

Engines (pick with --engine):
  gemini  - Gemini TTS (gemini-2.5-flash-preview-tts) via GEMINI_API_KEY
  azure   - Azure Speech TTS via AZURE_SPEECH_KEY + AZURE_SPEECH_REGION
  tone    - offline placeholder: a deterministic harmonic tone derived
            from the phrase hash. NOT speech — use only to seed fixture
            files when no TTS key is available (e.g. CI, offline dev).
            Re-run with a real engine before trusting WER numbers.

All output is 16 kHz mono 16-bit PCM wav named <id>.wav next to the
manifest. Idempotent: existing files are skipped unless --force.
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys
import urllib.request
import wave
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.yml"
RATE = 16000

VOICES = {
    ("gemini", "en"): "Puck",
    ("gemini", "th"): "Kore",
    ("azure", "en"): "en-US-JennyNeural",
    ("azure", "th"): "th-TH-PremwadeeNeural",
    ("edge", "en"): "en-US-AriaNeural",
    ("edge", "th"): "th-TH-PremwadeeNeural",
}


def write_wav(path, pcm, rate=RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def synth_tone(phrase, lang):
    """Deterministic ~2.2 s harmonic sweep keyed by the phrase text."""
    seed = int.from_bytes(hashlib.sha256(phrase.encode()).digest()[:8], "big")
    rng = seed
    n = int(RATE * 2.2)
    out = bytearray()
    f0 = 180 + (seed % 120)
    for i in range(n):
        rng = (1103515245 * rng + 12345) & 0x7FFFFFFF
        t = i / RATE
        f = f0 + 90 * math.sin(2 * math.pi * 0.8 * t) + (rng % 30)
        env = min(1.0, i / 2000, (n - i) / 2000)
        s = int(12000 * env * math.sin(2 * math.pi * f * t))
        out += struct.pack("<h", max(-32768, min(32767, s)))
    return bytes(out)


def synth_gemini(phrase, lang):
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    body = {
        "contents": [{"parts": [{"text": phrase}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": VOICES[("gemini", lang)]
                    }
                }
            },
        },
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    import base64
    pcm = base64.b64decode(b64)
    # Gemini returns 24 kHz PCM; naive downsample to 16 kHz.
    out = bytearray()
    for i in range(0, len(pcm) - 3, 6):
        out += pcm[i:i + 4]
    return bytes(out)


def synth_azure(phrase, lang):
    key = os.environ["AZURE_SPEECH_KEY"]
    region = os.environ["AZURE_SPEECH_REGION"]
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    voice = VOICES[("azure", lang)]
    ssml = (
        f"<speak version='1.0' xml:lang='{'th-TH' if lang == 'th' else 'en-US'}'>"
        f"<voice name='{voice}'>{phrase}</voice></speak>"
    )
    req = urllib.request.Request(url, data=ssml.encode(), headers={
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
        "User-Agent": "voice-bench",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def synth_edge(phrase, lang):
    """Free Microsoft Edge TTS — no key required. Returns 16 kHz mono PCM."""
    import asyncio
    import subprocess
    import tempfile

    import edge_tts

    voice = VOICES[("edge", lang)]
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        mp3 = tmp.name
    try:
        last = None
        for attempt in range(5):
            try:
                asyncio.run(edge_tts.Communicate(phrase, voice).save(mp3))
                break
            except Exception as e:
                last = e
                import time as _t
                _t.sleep(2 * (attempt + 1))
        else:
            raise last
        out = subprocess.run(
            ["ffmpeg", "-y", "-v", "quiet", "-i", mp3,
             "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-"],
            check=True, capture_output=True)
        return out.stdout
    finally:
        os.unlink(mp3)


SYNTH = {"tone": synth_tone, "gemini": synth_gemini, "azure": synth_azure,
         "edge": synth_edge}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=SYNTH, default="tone")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    manifest = yaml.safe_load(MANIFEST.read_text())
    made = skipped = 0
    for fx in manifest["fixtures"]:
        out = HERE / f"{fx['id']}.wav"
        if out.exists() and not args.force:
            skipped += 1
            continue
        pcm = SYNTH[args.engine](fx["phrase"], fx["lang"])
        write_wav(out, pcm)
        made += 1
        print(f"wrote {out.name} ({len(pcm)//2} samples)")
    print(f"done: {made} written, {skipped} skipped (engine={args.engine})")
    if args.engine == "tone":
        print("NOTE: tone fixtures are placeholders, not speech — "
              "re-run with --engine gemini or azure for real WER numbers.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
