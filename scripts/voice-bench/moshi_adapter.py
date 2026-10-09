#!/usr/bin/env python3
"""voice-bench transport adapter for kyutai-labs/moshi (PyTorch server).

Moshi is a full-duplex speech-to-speech model: it speaks over the user
(no VAD/STT/LLM/TTS pipeline, no tool plumbing). Its websocket protocol is
binary frames — client sends b"\\x01" + opus, server replies
b"\\x00" handshake, b"\\x01" + opus audio, b"\\x02" + utf8 text tokens.

This adapter owns the moshi server subprocess and exposes the harness's
lingua franca:

    GET  /       -> 200 once the adapter is listening (bench.py readiness;
                     moshi itself may still be loading weights)
    POST /bench  (body: wav bytes)
      -> {"transcript": <moshi's spoken reply as text>,
          "tool_call": null,
          "first_audio_ms": <send-to-first-audio-byte>,
          "reply_audio_ms": <ms of reply audio received>}

Run inside a venv with `moshi` + `sphn` installed:

    python moshi_adapter.py --port 8999 --moshi-port 8998

Env knobs: MOSHI_DEVICE (default cuda), MOSHI_HF_REPO
(default kyutai/moshiko-pytorch-bf16), MOSHI_CMD to fully override the
spawn command. --no-spawn attaches to an already-running moshi server.
"""
import argparse
import asyncio
import io
import os
import subprocess
import sys
import time
import wave

import numpy as np

MOSHI_SR = 24000           # mimi sample rate
CHUNK = 1920               # 80 ms @ 24 kHz
FRAME_S = CHUNK / MOSHI_SR
WAIT_FIRST_S = 300.0       # wait this long for moshi's first reply frame
                           # (CPU moshi lags far behind realtime)
QUIET_S = 20.0             # after replies start, stop when silent this long
REPLY_WINDOW_S = 90.0      # max collect window once moshi starts replying;
                           # a full-duplex model may never go quiet on its own
CAP_S = 600.0              # hard per-request cap
MOSHI_BOOT_S = 1800.0      # weight load + warmup can take a while on CPU

ARGS = None
_moshi_ready = False


def wav_to_pcm(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"expected 16-bit pcm, got {sw * 8}-bit")
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    if sr != MOSHI_SR:
        n = int(len(pcm) * MOSHI_SR / sr)
        pcm = np.interp(np.linspace(0, len(pcm), n, endpoint=False),
                        np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


async def wait_moshi(host: str, port: int, deadline_s: float):
    import aiohttp
    deadline = time.monotonic() + deadline_s
    async with aiohttp.ClientSession() as s:
        while time.monotonic() < deadline:
            try:
                async with s.get(f"http://{host}:{port}/api/chat",
                                 timeout=aiohttp.ClientTimeout(5)) as r:
                    # aiohttp ws upgrade request without headers -> 4xx means
                    # the app is up; connection refused means still loading
                    return
            except aiohttp.ClientResponseError:
                return
            except Exception:
                await asyncio.sleep(5)
    raise TimeoutError("moshi server never came up")


async def bench_roundtrip(wav_bytes: bytes) -> dict:
    import aiohttp
    import sphn

    global _moshi_ready
    if not _moshi_ready:
        print("[adapter] waiting for moshi server...", flush=True)
        await wait_moshi(ARGS.moshi_host, ARGS.moshi_port, MOSHI_BOOT_S)
        _moshi_ready = True
        print("[adapter] moshi ready", flush=True)

    pcm = wav_to_pcm(wav_bytes)
    uri = f"ws://{ARGS.moshi_host}:{ARGS.moshi_port}/api/chat"
    text_parts = []
    reply_audio_ms = 0.0
    first_audio_ms = None
    first_audio_t = None
    last_msg = time.monotonic()

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(uri, timeout=aiohttp.ClientTimeout(CAP_S)) as ws:
            # handshake: server sends b"\x00"
            msg = await ws.receive(timeout=60)
            if msg.type != aiohttp.WSMsgType.BINARY or msg.data != b"\x00":
                raise RuntimeError(f"bad moshi handshake: {msg.type}")

            writer = sphn.OpusStreamWriter(MOSHI_SR)
            reader = sphn.OpusStreamReader(MOSHI_SR)
            t0 = time.monotonic()

            async def send_pcm(buf: np.ndarray):
                for i in range(0, len(buf), CHUNK):
                    frame = buf[i:i + CHUNK]
                    if len(frame) < CHUNK:
                        frame = np.pad(frame, (0, CHUNK - len(frame)))
                    payload = writer.append_pcm(frame.astype(np.float32))
                    if payload:
                        await ws.send_bytes(b"\x01" + payload)

            async def send_paced(buf: np.ndarray):
                # realtime-paced: moshi is a streaming model; dumping all
                # frames instantly just builds a backlog it must chew
                # through before replying
                for i in range(0, len(buf), CHUNK):
                    frame = buf[i:i + CHUNK]
                    if len(frame) < CHUNK:
                        frame = np.pad(frame, (0, CHUNK - len(frame)))
                    payload = writer.append_pcm(frame.astype(np.float32))
                    if payload:
                        await ws.send_bytes(b"\x01" + payload)
                    await asyncio.sleep(FRAME_S)

            async def sender():
                await send_paced(pcm)
                # full-duplex: keep the mic "live" with silence so moshi
                # can finish its turn
                silence = np.zeros(CHUNK, dtype=np.float32)
                while not ws.closed:
                    quiet = time.monotonic() - last_msg
                    if first_audio_ms is None:
                        if quiet > WAIT_FIRST_S:
                            break
                    elif quiet > QUIET_S or \
                            time.monotonic() - first_audio_t > REPLY_WINDOW_S:
                        break
                    payload = writer.append_pcm(silence)
                    if payload:
                        await ws.send_bytes(b"\x01" + payload)
                    await asyncio.sleep(FRAME_S)

            async def receiver():
                nonlocal first_audio_ms, first_audio_t, last_msg, reply_audio_ms
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.BINARY:
                        break
                    data = msg.data
                    if not data:
                        continue
                    last_msg = time.monotonic()
                    kind, payload = data[0], data[1:]
                    if kind == 1:
                        if first_audio_ms is None:
                            first_audio_t = time.monotonic()
                            first_audio_ms = round((first_audio_t - t0) * 1000)
                        out = reader.append_bytes(payload)
                        reply_audio_ms += 1000.0 * len(out) / MOSHI_SR
                    elif kind == 2:
                        text_parts.append(payload.decode("utf8", "replace"))

            snd = asyncio.create_task(sender())
            rcv = asyncio.create_task(receiver())
            try:
                await asyncio.wait_for(snd, timeout=CAP_S)
            finally:
                await ws.close()
                for t in (snd, rcv):
                    t.cancel()

    transcript = "".join(text_parts).strip()
    return {
        "transcript": transcript or None,
        "tool_call": None,          # moshi has no tool plumbing — by design
        "first_audio_ms": first_audio_ms,
        "reply_audio_ms": round(reply_audio_ms),
    }


async def handle_bench(request):
    import aiohttp.web
    body = await request.read()
    try:
        result = await bench_roundtrip(body)
    except Exception as e:
        return aiohttp.web.json_response(
            {"transcript": None, "tool_call": None,
             "first_audio_ms": None, "error": str(e)}, status=500)
    return aiohttp.web.json_response(result)


async def handle_health(request):
    import aiohttp.web
    return aiohttp.web.Response(text="ok")


def main():
    import aiohttp.web

    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8999)
    ap.add_argument("--moshi-host", default="127.0.0.1")
    ap.add_argument("--moshi-port", type=int, default=8998)
    ap.add_argument("--no-spawn", action="store_true")
    ARGS = ap.parse_args()

    proc = None
    if not ARGS.no_spawn:
        already_up = False
        try:
            import urllib.request
            urllib.request.urlopen(
                f"http://{ARGS.moshi_host}:{ARGS.moshi_port}/api/chat",
                timeout=2)
            already_up = True
        except urllib.error.HTTPError:
            already_up = True      # 4xx = app listening, ws needs upgrade
        except Exception:
            pass
        if already_up:
            print("[adapter] moshi already listening; attaching "
                  "(--no-spawn equivalent)", flush=True)
            ARGS.no_spawn = True
    if not ARGS.no_spawn:
        device = os.environ.get("MOSHI_DEVICE", "cuda")
        hf_repo = os.environ.get("MOSHI_HF_REPO", "kyutai/moshiko-pytorch-bf16")
        cmd = os.environ.get("MOSHI_CMD") or " ".join(
            [sys.executable, "-m", "moshi.server",
             "--host", ARGS.moshi_host, "--port", str(ARGS.moshi_port),
             "--device", device, "--hf-repo", hf_repo])
        proc = subprocess.Popen(
            cmd, shell=True, env=dict(os.environ, PYTHONUNBUFFERED="1"))
        print(f"[adapter] spawned moshi server pid={proc.pid}: {cmd}",
              flush=True)

    app = aiohttp.web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_post("/bench", handle_bench)
    try:
        aiohttp.web.run_app(app, host=ARGS.host, port=ARGS.port,
                            print=None)
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
