#!/usr/bin/env python3
"""voice-miniapp backend — mic WAV in → whisper STT → hermes3:8b → Piper TTS out.
Served via tailscale HTTPS on omen. (ADA-0816 voice-tier1)

Language-aware TTS (voice-thai-voice-install, 2026-11-24): replies
containing Thai characters are synthesized with the th_TH-tsync2 Piper
voice; everything else stays on en_US-lessac. The LLM is told to answer
in Thai when the transcript contains Thai.
"""
import io
import json
import logging
import os
import re
import tempfile
import urllib.request
import wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, StreamingResponse
import faster_whisper
from piper import PiperVoice

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STT = faster_whisper.WhisperModel("small", device="cpu", compute_type="int8")
OLLAMA = "http://127.0.0.1:11434/api/generate"
LLM = "hermes3:8b"
PIPER_DIR = os.path.expanduser("~/.local/share/piper_voices")
VOICE_EN = os.path.join(PIPER_DIR, "en/en_US/lessac/medium/en_US-lessac-medium.onnx")
VOICE_TH = os.path.join(PIPER_DIR, "th/th_TH/tsync2/medium/th_TH-tsync2-medium.onnx")
TTS_EN = PiperVoice.load(VOICE_EN)
TTS_TH = PiperVoice.load(VOICE_TH)
VOICES = {"en": TTS_EN, "th": TTS_TH}
THAI_RE = re.compile(r"[฀-๿]")
SYSTEM_EN = ("You are a voice assistant. ALWAYS reply in English — the "
             "speech synthesizer only speaks English. Answer in 1-2 short "
             "conversational sentences, no reasoning, no preamble, no markdown.")
SYSTEM_TH = ("คุณเป็นผู้ช่วยเสียง ตอบเป็นภาษาไทยเสมอ — Answer in Thai, "
             "1-2 short conversational sentences, no reasoning, no preamble, "
             "no markdown.")

HERE = Path(__file__).resolve().parent

# Per-reply turn counter — lets the client drop stale in-flight audio.
_turn = 0
CHUNK_MS = 160


def has_thai(text: str) -> bool:
    return bool(THAI_RE.search(text or ""))


def voice_for(text: str) -> PiperVoice:
    return TTS_TH if has_thai(text) else TTS_EN


def transcribe(audio: np.ndarray) -> str:
    segments, _ = STT.transcribe(audio, language=None)
    return " ".join(s.text.strip() for s in segments).strip()


def ask_llm(prompt: str, thai: bool = False) -> str:
    body = json.dumps({"model": LLM,
                       "system": SYSTEM_TH if thai else SYSTEM_EN,
                       "prompt": prompt,
                       "stream": False,
                       "options": {"temperature": 0.6}}).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()).get("response", "").strip()


def tts_chunks(text: str, voice: PiperVoice, chunk_ms: int = CHUNK_MS):
    """Stream Piper synthesis output in ~chunk_ms PCM16 chunks (s16le mono,
    voice rate). First chunk arrives as soon as synthesis produces audio —
    the client starts speaking before the reply is fully synthesized."""
    bytes_per_ms = int(voice.config.sample_rate) * 2 // 1000
    frame_bytes = chunk_ms * bytes_per_ms
    buf = b""
    for chunk in voice.synthesize(text):
        buf += bytes(chunk.audio_int16_bytes)
        while len(buf) >= frame_bytes:
            yield buf[:frame_bytes]
            buf = buf[frame_bytes:]
    if buf:
        yield buf


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.post("/api/log")
async def js_log(body: dict):
    """Error beacon from the browser — lets us read client-side failures."""
    import logging
    logging.getLogger("uvicorn.error").warning(
        "browser: %s", json.dumps(body)[:400])
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "llm": LLM,
            "tts_loaded": True,
            "tts_voices": sorted(VOICES)}


@app.post("/api/voice")
async def voice(audio: UploadFile):
    raw = await audio.read()
    # Browser sends WAV (any rate) or webm/opus (MediaRecorder) —
    # decode to 16k mono PCM for whisper.
    import io as _io
    arr = None
    if audio.content_type and "webm" in audio.content_type:
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(raw); tmp = f.name
        try:
            p = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp, "-ac", "1", "-ar", "16000",
                 "-f", "s16le", "-"],
                capture_output=True, timeout=60)
            if p.returncode == 0:
                data = p.stdout
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        finally:
            os.unlink(tmp)
    if arr is None:
        try:
            with wave.open(_io.BytesIO(raw), "rb") as w:
                rate = w.getframerate()
                data = w.readframes(w.getnframes())
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            if rate != 16000:
                import scipy.signal
                arr = scipy.signal.resample_poly(arr, 16000, rate)
        except Exception as e:
            return {"text": "", "reply": f"audio decode failed: {e}"}
    if arr is None or len(arr) < 8000:
        return {"text": "", "reply": "Sorry, I did not catch that."}

    text = transcribe(arr)
    if not text:
        return {"text": "", "reply": "Sorry, I did not catch that."}
    thai_in = has_thai(text)
    reply = ask_llm(text, thai=thai_in)
    tts = voice_for(reply)
    rate = int(tts.config.sample_rate)

    global _turn
    _turn += 1
    turn = _turn
    logging.getLogger("uvicorn.error").warning(
        "voice turn #%d: %r -> %r (tts=%s)", turn, text[:80], reply[:120],
        "th" if tts is TTS_TH else "en")
    # Headers must be latin-1-safe — URL-encode transcripts/replies (Thai etc.)
    from urllib.parse import quote
    return StreamingResponse(
        tts_chunks(reply, tts),
        media_type="audio/x-pcm;bit-depth=16;rate={}".format(rate),
        headers={"X-Turn": str(turn), "X-Transcript": quote(text),
                 "X-Reply": quote(reply),
                 "X-Rate": str(rate), "X-Channels": "1",
                 "Access-Control-Expose-Headers": "X-Turn, X-Transcript, X-Reply, X-Rate, X-Channels"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8520)
