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
import os
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


GEMINI_MODEL = os.environ.get(
    "GEMINI_LIVE_MODEL",
    os.environ.get("GEV_GEMINI_MODEL", "gemini-3.8-live"))


def _clean_schema(schema):
    """Same cleanup gev-gemini/bridge.py applies — Live rejects
    additionalProperties."""
    if not isinstance(schema, dict):
        return schema
    schema = dict(schema)
    schema.pop("additionalProperties", None)
    schema.pop("additional_properties", None)
    for key, val in schema.items():
        if isinstance(val, dict):
            schema[key] = _clean_schema(val)
        elif isinstance(val, list):
            schema[key] = [_clean_schema(v) if isinstance(v, dict) else v
                           for v in val]
    return schema


def load_gemini_key():
    """GEMINI_API_KEY from env, else GEMINI_KEY_FILE / the default secrets
    file. Raises RuntimeError when neither yields a key."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        secret = os.environ.get(
            "GEMINI_KEY_FILE",
            os.path.expanduser("~/.config/secrets/gemini-api-key.env"))
        try:
            for line in Path(secret).read_text().splitlines():
                line = line.strip().lstrip("export ").strip()
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"\'')
        except OSError:
            pass
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set and key file unreadable")
    return api_key


def thinking_mode_for(model, thinking_level=None):
    """gemini-3.8-live-extended-thinking needs thinkingConfig.thinkingLevel
    (low|medium|high) and NON_BLOCKING tool declarations; plain 3.8-live
    rejects thinkingLevel (docs/live-api/thinking)."""
    level = thinking_level or os.environ.get("GEMINI_THINKING_LEVEL")
    mode = "extended-thinking" in (model or "") or bool(level)
    return mode, (level or ("LOW" if mode else None))


def live_setup(model, thinking_level=None):
    """BidiGenerateContent setup message for the harness HA_TOOLS surface."""
    thinking_mode, level = thinking_mode_for(model, thinking_level)
    declarations = []
    for t in HA_TOOLS:
        d = {"name": t["name"], "description": t.get("description", ""),
             "parameters": _clean_schema(t.get("parameters")
                                         or {"type": "object"})}
        if thinking_mode:
            # extended-thinking runs tools asynchronously; BLOCKING
            # declarations are rejected at setup (docs/live-api/thinking).
            d["behavior"] = "NON_BLOCKING"
        declarations.append(d)
    generation_config = {"responseModalities": ["AUDIO"]}
    if thinking_mode:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": level.upper()}
    return {"setup": {
        "model": f"models/{model}",
        "generationConfig": generation_config,
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "tools": [{"functionDeclarations": declarations}],
    }}


def gemini_live(combo, fx, timeout):
    """Stream a fixture through the current Gemini Live path — same client
    shape as gev-gemini/bridge.py: google-genai aio.live.connect with AUDIO
    modality + input/output audio transcription, PCM16@16k pushed via
    send_realtime_input at real-time pace.

    Tool surface is the harness's HA_TOOLS (not GEV's tools.json) so
    tool_call_match scores the same hass_* calls as every other combo.
    This is the golden baseline row the fallbacks are compared against.

    Since gemini-3.8-live, a tool call can be followed by an early
    turnComplete and then a SECOND spoken turn after the toolResponse. Skip
    at most one such early completion so the spoken confirmation is counted.
    Latency is anchored to end-of-speech (input transcription), not to the
    end of the trailing silence, so fast models are not penalised.

      transcript      <- server_content.input_transcription (accumulated)
      tool_call       <- msg.tool_call.function_calls (first; answered with
                         a stub response so the turn completes)
      first_audio_ms  <- first msg.data (audio chunk) after audio send
      total           <- server_content.turn_complete
    """
    import asyncio

    api_key = load_gemini_key()

    wav = Path(fx["wav"])
    pcm, rate = _wav_pcm(wav)
    if rate != 16000:
        raise RuntimeError(f"{wav.name}: expected 16kHz, got {rate}")
    # ~1.0 s trailing silence so Gemini VAD sees end-of-speech.
    payload = pcm + b"\x00" * rate * 2
    chunk_ms = 100
    chunk_bytes = int(rate * chunk_ms / 1000) * 2

    # combos.yml `gemini_model`/`thinking_level` win over env so a combo is
    # self-describing; env stays the override for ad-hoc runs.
    model = (combo.get("gemini_model")
             or os.environ.get("GEMINI_LIVE_MODEL", GEMINI_MODEL))
    thinking_level = (combo.get("thinking_level")
                      or os.environ.get("GEMINI_THINKING_LEVEL"))
    thinking_mode, thinking_level = thinking_mode_for(model, thinking_level)
    setup_msg = live_setup(model, thinking_level)

    async def run():
        import websockets
        out = {"transcript": None, "tool_call": None,
               "first_audio_ms": None, "assistant_text": None,
               "events_seen": [], "session_id": None}
        transcripts = []
        assistant_parts = []
        url = ("wss://generativelanguage.googleapis.com/ws/"
               "google.ai.generativelanguage.v1beta.GenerativeService."
               f"BidiGenerateContent?key={api_key}")
        start = time.monotonic()
        async with websockets.connect(url, max_size=None) as ws:
            # NOTE: this raw BidiGenerateContent JSON shape is the same one
            # stacks/web/gemini-mic-test/server.mjs drives. The google-genai
            # SDK path (aio.live.connect + send_realtime_input) connected but
            # had its audio turns silently ignored on this host (2026-10-09).
            await ws.send(json.dumps(setup_msg))
            send_done = None
            speech_end = None
            awaiting_final = False
            early_skipped = False
            last_status = None
            status_seen = False
            idle_since = None
            done_ev = asyncio.Event()

            async def sender():
                nonlocal send_done
                for i in range(0, len(payload), chunk_bytes):
                    await ws.send(json.dumps({"realtimeInput": {"audio": {
                        "data": base64.b64encode(
                            payload[i:i + chunk_bytes]).decode(),
                        "mimeType": "audio/pcm;rate=16000"}}}))
                    await asyncio.sleep(chunk_ms / 1000)
                await ws.send(json.dumps(
                    {"realtimeInput": {"audioStreamEnd": True}}))
                send_done = time.monotonic()

            async def receiver():
                nonlocal speech_end, awaiting_final, early_skipped
                nonlocal last_status, status_seen, idle_since
                deadline = time.monotonic() + timeout
                while not done_ev.is_set():
                    # 2 s slices so an IDLE-without-turnComplete safety
                    # timer can fire; overall deadline preserves `timeout`.
                    slice_to = min(2.0, max(0.05, deadline - time.monotonic()))
                    try:
                        raw = await asyncio.wait_for(ws.recv(),
                                                     timeout=slice_to)
                    except asyncio.TimeoutError:
                        if (thinking_mode and idle_since
                                and time.monotonic() - idle_since > 4):
                            out["events_seen"].append("idle_no_tc_done")
                            done_ev.set()
                            return
                        if time.monotonic() >= deadline:
                            break
                        continue
                    try:
                        m = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    sc = m.get("serverContent") or {}
                    # interactionStatus rides top-level (toolCall msgs) or
                    # inside serverContent (utterance msgs) on thinking Live.
                    st = m.get("interactionStatus") or sc.get("interactionStatus")
                    if st:
                        status_seen = True
                        last_status = st
                        out["events_seen"].append(
                            f"interaction_{str(st).lower()}")
                        idle_since = (time.monotonic()
                                      if st == "IDLE" else None)
                    it = sc.get("inputTranscription") or {}
                    if it.get("text"):
                        out["events_seen"].append("input_transcription")
                        transcripts.append(it["text"])
                        if speech_end is None:
                            speech_end = time.monotonic()
                    ot = sc.get("outputTranscription") or {}
                    if ot.get("text"):
                        out["events_seen"].append("output_transcription")
                        assistant_parts.append(ot["text"])
                        awaiting_final = False
                    for part in ((sc.get("modelTurn") or {}).get("parts") or []):
                        if part.get("inlineData", {}).get("data"):
                            # VAD-anchored latency: fast models may answer
                            # before the trailing silence finishes streaming.
                            anchor = speech_end or send_done
                            if out["first_audio_ms"] is None and anchor:
                                out["first_audio_ms"] = round(
                                    (time.monotonic() - anchor) * 1000)
                            awaiting_final = False
                            out["events_seen"].append("audio")
                    if sc.get("interrupted"):
                        out["events_seen"].append("interrupted")
                    if sc.get("turnComplete"):
                        if thinking_mode and status_seen:
                            # Thinking Live: turnComplete ends an utterance,
                            # not the request — fillers complete with
                            # IN_PROGRESS; only IDLE means the session is
                            # done (docs/live-api/thinking).
                            if last_status == "IDLE":
                                out["events_seen"].append("turn_complete")
                                done_ev.set()
                                return
                            out["events_seen"].append(
                                "utterance_turn_complete")
                            continue
                        # 3.8-live can emit an early turnComplete with a tool
                        # call, then a final spoken turn after toolResponse.
                        # Skip at most one such early completion per tool.
                        if awaiting_final and not early_skipped:
                            out["events_seen"].append("early_turn_complete")
                            early_skipped = True
                            continue
                        out["events_seen"].append("turn_complete")
                        done_ev.set()
                        return
                    if "toolCall" in m:
                        out["events_seen"].append("tool_call")
                        responses = []
                        for call in (m["toolCall"].get("functionCalls") or []):
                            if out["tool_call"] is None:
                                out["tool_call"] = {
                                    "name": call.get("name"),
                                    "args": call.get("args") or {}}
                            responses.append({
                                "id": call.get("id", ""),
                                "name": call.get("name", ""),
                                "response": {"ok": True,
                                             "result": "done (bench stub)"}})
                        if responses:
                            try:
                                await ws.send(json.dumps({"toolResponse": {
                                    "functionResponses": responses}}))
                            except Exception as e:
                                out["tool_response_error"] = str(e)
                        if responses:
                            awaiting_final = True
                            early_skipped = False
                    if m.get("error"):
                        out["server_error"] = m["error"]
                        done_ev.set()
                        return

            send_task = asyncio.create_task(sender())
            recv_task = asyncio.create_task(receiver())
            try:
                await asyncio.wait_for(done_ev.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.wait_for(recv_task, timeout=5)
            except asyncio.TimeoutError:
                recv_task.cancel()
            send_task.cancel()
            out["elapsed_ms"] = round((time.monotonic() - start) * 1000)
            out["transcript"] = "".join(transcripts).strip() or None
            out["assistant_text"] = "".join(assistant_parts).strip() or None
            if out.get("server_error"):
                out["error"] = json.dumps(out["server_error"])
            return out

    r = asyncio.run(run())
    return {
        "transcript": r.get("transcript"),
        "tool_call": r.get("tool_call"),
        "first_audio_ms": r.get("first_audio_ms"),
        "assistant_text": r.get("assistant_text"),
        "elapsed_ms": r.get("elapsed_ms"),
        "error": r.get("error"),
        "events_seen": sorted(set(r.get("events_seen") or [])),
    }


ADAPTERS = {"openai_realtime": openai_realtime, "gemini_live": gemini_live}
