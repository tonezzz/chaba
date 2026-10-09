"""Combo adapters — protocol plumbing between bench.py and orchestrators that
don't speak the harness's fallback POST-/bench shape.

An adapter is a callable:

    adapter(combo, fx, timeout) -> dict with keys
        transcript, tool_call ({name, args} | None), first_audio_ms

bench.py picks the adapter named by combos.yml `adapter:` and folds the
returned dict into lib.fixture_result.
"""
import base64
import json
import time
import wave
from pathlib import Path

# Tool surface we expose to the combo under test. Names/args match
# manifest.yml expected_tool_call so tool_call_match() can score directly.
HA_TOOLS = [
    {"type": "function", "name": "hass_turn_on",
     "description": "Turn on a Home Assistant device or area.",
     "parameters": {"type": "object", "properties": {
         "domain": {"type": "string"}, "area": {"type": "string"},
         "entity": {"type": "string"}},
         "required": []}},
    {"type": "function", "name": "hass_turn_off",
     "description": "Turn off a Home Assistant device or area.",
     "parameters": {"type": "object", "properties": {
         "domain": {"type": "string"}, "area": {"type": "string"},
         "entity": {"type": "string"}},
         "required": []}},
    {"type": "function", "name": "hass_set_temperature",
     "description": "Set a climate target temperature.",
     "parameters": {"type": "object", "properties": {
         "area": {"type": "string"}, "temperature": {"type": "number"}},
         "required": ["temperature"]}},
    {"type": "function", "name": "hass_lock",
     "description": "Lock a Home Assistant lock entity.",
     "parameters": {"type": "object", "properties": {
         "entity": {"type": "string"}}, "required": []}},
    {"type": "function", "name": "hass_get_state",
     "description": "Read the current state of a Home Assistant entity.",
     "parameters": {"type": "object", "properties": {
         "entity": {"type": "string"}}, "required": ["entity"]}},
]

INSTRUCTIONS = (
    "You are Ada, a bilingual English/Thai smart-home voice assistant. "
    "Reply in the same language the user spoke, in under 15 words. "
    "When the user asks to control a device or asks about device state, "
    "call the matching hass_* tool immediately."
)


def _wav_pcm(path):
    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        return w.readframes(w.getnframes()), w.getframerate()


def openai_realtime(combo, fx, timeout):
    """Stream a fixture through an OpenAI-Realtime-compatible ws endpoint
    (e.g. huggingface/speech-to-speech `serve`).

    Sends session.update (instructions + HA tools + server VAD), streams the
    wav as input_audio_buffer.append chunks at real-time pace with trailing
    silence so server-VAD closes the turn, then collects:
      transcript      <- conversation.item.input_audio_transcription.completed
      tool_call       <- response.function_call_arguments.done
      first_audio_ms  <- first response.output_audio.delta after audio send
      total           <- response.done (all responses idle)
    """
    import asyncio
    import websockets

    wav = Path(fx["wav"])
    pcm, rate = _wav_pcm(wav)
    url = combo["endpoint"].rstrip("/")
    if "realtime" not in url:
        url += "/v1/realtime"

    # ~1.0 s of trailing silence so server_vad sees end-of-speech.
    silence = b"\x00" * int(rate * 1.0) * 2
    payload = pcm + silence
    chunk_ms = 100
    chunk_bytes = int(rate * chunk_ms / 1000) * 2

    async def run():
        out = {"transcript": None, "tool_call": None,
               "first_audio_ms": None, "assistant_text": None,
               "events_seen": [], "session_id": None}
        # pool=1 servers reject a connect that races the previous session's
        # release — retry a few times before giving up
        ws = None
        # pool=1 servers keep the slot ~10s past client disconnect while
        # handlers drain (server logs "SESSION_END not drained after 10.0s"),
        # so allow ~40s of retries
        for attempt in range(20):
            try:
                ws = await websockets.connect(url, max_size=None,
                                              open_timeout=15)
                # probe: server closes/rejects slot-less connections early
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    ev0 = json.loads(raw)
                    t0 = ev0.get("type")
                    out["events_seen"].append(t0)
                    if t0 == "session.created":
                        out["session_id"] = (
                            ev0.get("session") or {}).get("id")
                        break
                    if t0 == "error":
                        out["server_error"] = ev0
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        ws = None
                        if attempt == 19:
                            raise RuntimeError(f"session rejected: {ev0}")
                        await asyncio.sleep(2)
                        continue
                    break  # any other greeting: proceed
                except asyncio.TimeoutError:
                    break  # connected but no greeting — proceed anyway
            except Exception:
                if ws:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                ws = None
                if attempt == 19:
                    raise
                await asyncio.sleep(2)
        if ws is None:
            raise RuntimeError("could not acquire a realtime session")
        async with ws:
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": INSTRUCTIONS,
                    "tools": HA_TOOLS,
                    "audio": {"input": {
                        "turn_detection": {
                            "type": "server_vad",
                            "interrupt_response": True}}},
                }}))
            send_done = None
            start = time.monotonic()
            done_ev = asyncio.Event()

            async def sender():
                nonlocal send_done
                for i in range(0, len(payload), chunk_bytes):
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(
                            payload[i:i + chunk_bytes]).decode()}))
                    await asyncio.sleep(chunk_ms / 1000)
                send_done = time.monotonic()

            async def receiver():
                while not done_ev.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except asyncio.TimeoutError:
                        break
                    ev = json.loads(raw)
                    t = ev.get("type", "")
                    out["events_seen"].append(t)
                    if t == "session.created":
                        out["session_id"] = (ev.get("session") or {}).get("id")
                    elif t == "conversation.item.input_audio_transcription.completed":
                        if ev.get("transcript"):
                            out["transcript"] = ev["transcript"]
                    elif t == "response.function_call_arguments.done":
                        if out["tool_call"] is None:
                            try:
                                args = json.loads(ev.get("arguments") or "{}")
                            except json.JSONDecodeError:
                                args = {"_raw": ev.get("arguments")}
                            out["tool_call"] = {
                                "name": ev.get("name"), "args": args}
                    elif t == "response.output_audio.delta":
                        if out["first_audio_ms"] is None and send_done:
                            out["first_audio_ms"] = round(
                                (time.monotonic() - send_done) * 1000)
                    elif t == "response.output_audio_transcript.done":
                        out["assistant_text"] = ev.get("transcript")
                    elif t == "response.done":
                        # keep reading briefly in case a function_call_output
                        # follow-up is needed; stop once no tool call pending
                        if out["tool_call"] is None or out["assistant_text"]:
                            done_ev.set()
                            return
                    elif t == "error":
                        out["server_error"] = ev

            send_task = asyncio.create_task(sender())
            recv_task = asyncio.create_task(receiver())
            try:
                await asyncio.wait_for(done_ev.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            # grace period for a straggler response.done
            try:
                await asyncio.wait_for(recv_task, timeout=5)
            except asyncio.TimeoutError:
                recv_task.cancel()
            send_task.cancel()
            out["elapsed_ms"] = round((time.monotonic() - start) * 1000)
            return out

    r = asyncio.run(run())
    return {
        "transcript": r.get("transcript"),
        "tool_call": r.get("tool_call"),
        "first_audio_ms": r.get("first_audio_ms"),
        "assistant_text": r.get("assistant_text"),
        "elapsed_ms": r.get("elapsed_ms"),
        "error": json.dumps(r.get("server_error"))
        if r.get("server_error") else None,
        "events_seen": sorted(set(r.get("events_seen") or [])),
    }


ADAPTERS = {"openai_realtime": openai_realtime}
