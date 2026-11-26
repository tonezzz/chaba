#!/usr/bin/env python3
"""Probe untested Interactions API surfaces on the free-tier lite model.

Read-only, synthetic text only. Env: GEMINI_API_KEY, MODEL, OUT.
"""
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone

from google import genai

MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-interactions-surfaces.json")
client = genai.Client()
results = {}


def dump(obj):
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    return str(obj)


def record(name, fn):
    t0 = time.monotonic()
    try:
        out = fn() or {}
        results[name] = {"ok": True, "elapsed_s": round(time.monotonic() - t0, 2), **out}
    except Exception as e:
        results[name] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:400]}",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    r = results[name]
    print(name, "OK" if r["ok"] else "FAIL", str(r.get("error", ""))[:180], flush=True)


def streaming_text():
    stream = client.interactions.create(
        model=MODEL,
        input="Count from 1 to 12, separated by commas. Nothing else.",
        stream=True,
    )
    events, deltas, text, iid, final_status, usage = Counter(), Counter(), "", None, None, None
    n = 0
    for ev in stream:
        n += 1
        et = getattr(ev, "event_type", None)
        events[str(et)] += 1
        if et == "interaction.created":
            iid = getattr(getattr(ev, "interaction", None), "id", None)
        elif et == "step.delta":
            d = getattr(ev, "delta", None)
            dt = getattr(d, "type", None)
            deltas[str(dt)] += 1
            if dt == "text":
                text += getattr(d, "text", "") or ""
            eid = getattr(ev, "event_id", None)
            if eid and "event_id_sample" not in locals():
                event_id_sample = str(eid)
        elif et == "interaction.completed":
            inter = getattr(ev, "interaction", None)
            final_status = getattr(inter, "status", None)
            usage = dump(getattr(inter, "usage", None))
    out = {"id": iid, "n_events": n, "event_types": dict(events),
           "delta_types": dict(deltas), "text": text[:300],
           "status": final_status, "usage": usage}
    if "event_id_sample" in locals():
        out["event_id_sample"] = event_id_sample
    return out


TOOLS = [{
    "type": "function", "name": "get_weather",
    "description": "Get the current weather in a given location",
    "parameters": {"type": "object", "properties": {
        "location": {"type": "string", "description": "City and state"}},
        "required": ["location"]},
}]


def streaming_tool():
    stream = client.interactions.create(
        model=MODEL, input="What is the weather in Paris, France?",
        tools=TOOLS, stream=True,
    )
    iid, call_id, call_name, args, status, deltas = None, None, None, "", None, Counter()
    for ev in stream:
        et = getattr(ev, "event_type", None)
        if et == "interaction.created":
            iid = getattr(getattr(ev, "interaction", None), "id", None)
        elif et == "step.start":
            s = getattr(ev, "step", None)
            if getattr(s, "type", None) == "function_call":
                call_id, call_name = getattr(s, "id", None), getattr(s, "name", None)
        elif et == "step.delta":
            d = getattr(ev, "delta", None)
            deltas[str(getattr(d, "type", None))] += 1
            if getattr(d, "type", None) == "arguments_delta":
                args += getattr(d, "arguments", "") or ""
        elif et == "interaction.completed":
            status = getattr(getattr(ev, "interaction", None), "status", None)
    out = {"id": iid, "call_id": call_id, "call_name": call_name,
           "accumulated_args": args[:300], "status": status,
           "delta_types": dict(deltas)}
    if call_id:
        result_step = {"type": "function_result", "name": call_name, "call_id": call_id,
                       "result": [{"type": "text", "text": '{"weather":"Sunny, 22C"}'}]}
        stream2 = client.interactions.create(
            model=MODEL, previous_interaction_id=iid, input=[result_step], stream=True)
        text, events2 = "", Counter()
        for ev in stream2:
            et = getattr(ev, "event_type", None)
            events2[str(et)] += 1
            if et == "step.delta":
                d = getattr(ev, "delta", None)
                if getattr(d, "type", None) == "text":
                    text += getattr(d, "text", "") or ""
        out["resume_events"] = dict(events2)
        out["resume_text"] = text[:300]
    return out


FEEDBACK_SCHEMA = {"type": "object", "properties": {
    "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
    "summary": {"type": "string"}},
    "required": ["sentiment", "summary"]}


def structured_nonstream():
    r = client.interactions.create(
        model=MODEL,
        input="The new UI is incredibly intuitive. Summarize in one short sentence.",
        response_format={"type": "text", "mime_type": "application/json", "schema": FEEDBACK_SCHEMA})
    raw = getattr(r, "output_text", None)
    parsed = json.loads(raw) if raw else None
    return {"id": getattr(r, "id", None), "raw": (raw or "")[:300], "parsed": parsed,
            "schema_valid": bool(isinstance(parsed, dict) and
                                 parsed.get("sentiment") in ("positive", "neutral", "negative")
                                 and isinstance(parsed.get("summary"), str)),
            "usage": dump(getattr(r, "usage", None))}


def structured_stream():
    stream = client.interactions.create(
        model=MODEL,
        input="The new UI is incredibly intuitive. Summarize in one short sentence.",
        response_format={"type": "text", "mime_type": "application/json", "schema": FEEDBACK_SCHEMA},
        stream=True)
    text, deltas = "", Counter()
    for ev in stream:
        if getattr(ev, "event_type", None) == "step.delta":
            d = getattr(ev, "delta", None)
            deltas[str(getattr(d, "type", None))] += 1
            if getattr(d, "type", None) == "text":
                text += getattr(d, "text", "") or ""
    parsed = json.loads(text) if text else None
    return {"text": text[:300], "delta_types": dict(deltas),
            "schema_valid": bool(isinstance(parsed, dict) and
                                 parsed.get("sentiment") in ("positive", "neutral", "negative")
                                 and isinstance(parsed.get("summary"), str))}


def background():
    r = client.interactions.create(
        model=MODEL, input="Write one sentence about lighthouses.",
        background=True)
    iid = getattr(r, "id", None)
    statuses = [getattr(r, "status", None)]
    t0 = time.monotonic()
    while time.monotonic() - t0 < 45:
        g = client.interactions.get(id=iid)
        st = getattr(g, "status", None)
        statuses.append(st)
        if st not in ("in_progress", "queued", "requires_action"):
            break
        time.sleep(3)
    return {"id": iid, "statuses": statuses,
            "terminal_status": statuses[-1],
            "output_text": str(getattr(g, "output_text", None))[:300],
            "steps": [getattr(s, "type", None) for s in (getattr(g, "steps", None) or [])]}


def retrieve_steps():
    r = client.interactions.create(
        model=MODEL, input="Reply with exactly: STOREOK",
        system_instruction="Be concise.", store=True)
    iid = getattr(r, "id", None)
    g = client.interactions.get(id=iid)
    out = {"id": iid, "get_status": getattr(g, "status", None),
           "get_output_text": str(getattr(g, "output_text", None))[:100],
           "steps": [dump(s) for s in (getattr(g, "steps", None) or [])][:4],
           "usage": dump(getattr(g, "usage", None))}
    try:
        client.interactions.delete(id=iid)
        out["delete"] = "ok"
    except Exception as e:
        out["delete"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def main():
    record("streaming_text", streaming_text)
    record("streaming_tool", streaming_tool)
    record("structured_nonstream", structured_nonstream)
    record("structured_stream", structured_stream)
    record("background", background)
    record("retrieve_steps", retrieve_steps)
    out = {"schema": "g4-interactions-surfaces", "schema_version": 1,
           "date": datetime.now(timezone.utc).isoformat(), "host": "idc03",
           "model": MODEL, "key_printed": False, "results": results}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
