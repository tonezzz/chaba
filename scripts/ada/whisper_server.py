"""ada-whisper — faster-whisper HTTP endpoint for msg-lane STT.

Runs on tony-omen (GTX 1650). Serves large-v3 int8_float16 to the msg
relays (tg_relay / line_relay on idc03) over plain LAN/tailnet HTTP.

  POST /transcribe   multipart "file" or raw body (+ ?filename= for suffix)
                     optional form/query field "lang" (e.g. th, en)
                     -> {"text", "language", "language_probability",
                         "duration_s", "elapsed_s", "model", "device"}
  GET  /health       -> {"ok", "loaded", "model", "device", "vram_free_mb"}

GPU citizenship (ssot.gpu one-workload policy): the model loads lazily on
first request and unloads after WHISPER_IDLE_S idle seconds so the VRAM is
free for ollama/imagen between clips. On a CUDA load failure the server
asks local ollama to unload its models (keep_alive=0), retries once, then
falls back to CPU int8 so the endpoint stays up either way.

Decode is ffmpeg -> 16kHz mono f32 numpy — the PyAV path is deliberately
avoided (av/faster-whisper kwarg drift has broken it before).

Env:
  WHISPER_MODEL        default large-v3
  WHISPER_DEVICE       default cuda
  WHISPER_COMPUTE      default int8_float16
  WHISPER_CPU_COMPUTE  default int8
  WHISPER_BIND         default 0.0.0.0:8790
  WHISPER_IDLE_S       default 300 (0 = stay resident)
  WHISPER_BEAM         default 1
  WHISPER_TOKEN        optional — require "Authorization: Bearer <token>"
  OLLAMA_URL           default http://127.0.0.1:11434
"""

from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

log = logging.getLogger("ada-whisper")

MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3")
DEVICE = os.environ.get("WHISPER_DEVICE", "cuda")
COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8_float16")
CPU_COMPUTE = os.environ.get("WHISPER_CPU_COMPUTE", "int8")
BIND = os.environ.get("WHISPER_BIND", "0.0.0.0:8790")
IDLE_S = float(os.environ.get("WHISPER_IDLE_S", "300"))
BEAM = int(os.environ.get("WHISPER_BEAM", "1"))
TOKEN = os.environ.get("WHISPER_TOKEN", "").strip()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

_lock = threading.Lock()
_state = {"model": None, "device": None, "last_used": 0.0}
MIN_FREE_MB = int(os.environ.get("WHISPER_MIN_FREE_MB", "1500"))


def _vram_free_mb() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def _ollama_evict() -> bool:
    """Unload every model ollama currently holds (keep_alive=0)."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps",
                                    timeout=3) as r:
            models = json.loads(r.read()).get("models", [])
    except Exception:
        return False
    if not models:
        return False
    for m in models:
        try:
            req = urllib.request.Request(
                OLLAMA_URL + "/api/generate",
                data=json.dumps(
                    {"model": m["name"], "keep_alive": 0}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
            log.info("evicted ollama model %s", m.get("name"))
        except Exception as exc:
            log.warning("ollama evict %s failed: %s", m.get("name"), exc)
    time.sleep(2)
    return True


def _load() -> None:
    from faster_whisper import WhisperModel
    try:
        _state["model"] = WhisperModel(
            MODEL_NAME, device=DEVICE, compute_type=COMPUTE)
        _state["device"] = DEVICE
    except Exception as exc:
        free = _vram_free_mb()
        log.warning("cuda load failed (%s); vram_free=%s", exc, free)
        if free is not None and free < MIN_FREE_MB and _ollama_evict():
            try:
                _state["model"] = WhisperModel(
                    MODEL_NAME, device=DEVICE, compute_type=COMPUTE)
                _state["device"] = DEVICE
                return
            except Exception as exc2:
                log.warning("cuda retry after evict failed: %s", exc2)
        _state["model"] = WhisperModel(
            MODEL_NAME, device="cpu", compute_type=CPU_COMPUTE)
        _state["device"] = "cpu"
    log.info("whisper %s loaded on %s (vram_free=%s MB)",
             MODEL_NAME, _state["device"], _vram_free_mb())


def _unload() -> None:
    if _state["model"] is None:
        return
    _state["model"] = None
    _state["device"] = None
    gc.collect()
    log.info("whisper unloaded after idle (vram_free=%s MB)",
             _vram_free_mb())


def _idle_watcher() -> None:
    while True:
        time.sleep(30)
        if IDLE_S <= 0:
            continue
        with _lock:
            if (_state["model"] is not None
                    and time.monotonic() - _state["last_used"] > IDLE_S):
                _unload()


def _decode(path: str):
    """ffmpeg -> 16 kHz mono f32 numpy (no PyAV)."""
    import numpy as np
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path,
         "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1",
         "-ar", "16000", "-"],
        capture_output=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(
            f"ffmpeg decode failed: {out.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(out.stdout, dtype=np.float32)


app = FastAPI(title="ada-whisper")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "loaded": _state["model"] is not None,
            "model": MODEL_NAME, "device": _state["device"],
            "idle_s": IDLE_S, "vram_free_mb": _vram_free_mb()}


@app.post("/transcribe")
async def transcribe(request: Request,
                     file: UploadFile | None = File(None),
                     lang: str | None = Form(None)):
    if TOKEN:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    if file is not None:
        data = await file.read()
        suffix = Path(file.filename or "clip").suffix or ".bin"
    else:
        data = await request.body()
        suffix = Path(request.query_params.get(
            "filename", "clip.ogg")).suffix or ".ogg"
    if not data:
        return JSONResponse({"error": "empty audio"}, status_code=400)

    t0 = time.time()
    tmp = tempfile.NamedTemporaryFile(
        suffix=suffix, prefix="aw-", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        with _lock:
            if _state["model"] is None:
                _load()
            audio = _decode(tmp.name)
            duration = len(audio) / 16000.0
            segments, info = _state["model"].transcribe(
                audio, beam_size=BEAM, language=lang or None)
            text = " ".join(s.text.strip() for s in segments).strip()
            _state["last_used"] = time.monotonic()
        return {"text": text, "language": info.language,
                "language_probability": round(info.language_probability, 3),
                "duration_s": round(duration, 2),
                "elapsed_s": round(time.time() - t0, 2),
                "model": MODEL_NAME, "device": _state["device"]}
    except Exception as exc:
        log.exception("transcribe failed")
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s ada-whisper: %(message)s")
    host, _, port = BIND.rpartition(":")
    threading.Thread(target=_idle_watcher, daemon=True).start()
    log.info("listening on %s model=%s idle_s=%s", BIND, MODEL_NAME, IDLE_S)
    uvicorn.run(app, host=host or "0.0.0.0", port=int(port or 8790),
                log_level="warning")


if __name__ == "__main__":
    main()
