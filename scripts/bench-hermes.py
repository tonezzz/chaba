#!/usr/bin/env python3
"""bench-hermes.py — card try-hermes: evidence-first eval of hermes3:8b vs
the current T1 local roster on omen ollama.

Three probes matching the card's AQ:

  toolcall_native   POST /api/chat WITH `tools` — does ollama's parser get
                    a schema-conformant call out of <tool_call> output?
  toolcall_prompted POST /api/chat, prompt-only ("emit JSON only") — raw
                    JSON fidelity without template support. This is the
                    arm that matters for OpenClaw-style loops on models
                    whose template lacks tools.
  routing           intent classification into a fixed label set
                    (the T1 routing job).
  reasoning         short checkable reasoning Q&A.

Metrics per model×arm: score %, json-parse rate, timeout count,
mean/p50 latency, eval tok/s. Baselines are the T1 roster on omen
(qwen3:4b, phi3-gguf) so the AQ "≥ current T1" is a same-host compare.

Usage:
  python3 scripts/bench-hermes.py                      # all models, all probes
  python3 scripts/bench-hermes.py --models hermes3:8b  # subject only
  python3 scripts/bench-hermes.py --reps 1 --json /tmp/h.json
Env: OLLAMA_URL (default http://100.75.102.88:11434 — omen tailnet)
"""
import argparse
import json
import re
import statistics
import time
import urllib.request

OLLAMA = None  # set in main
TIMEOUT = 120

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "units": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_light",
            "description": "Set a Home Assistant light's state",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "brightness_pct": {"type": "integer", "minimum": 0, "maximum": 100},
                    "rgb_color": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["entity_id", "brightness_pct"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search the personal memory bank",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "bank": {"type": "string", "enum": ["all", "personal", "home", "people"]},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder for the user",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "when": {"type": "string", "description": "ISO-8601 datetime"},
                },
                "required": ["text", "when"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create_event",
            "description": "Create a calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "start", "end"],
            },
        },
    },
]

# (user utterance, expected tool, required arg keys that must appear)
TOOLCALL_CASES = [
    ("What's the weather in Bangkok in fahrenheit?", "get_weather", {"location", "units"}),
    ("Set the living room light to 40 percent brightness.", "set_light", {"entity_id", "brightness_pct"}),
    ("Search my memory for the wifi password.", "memory_search", {"query"}),
    ("Remind me tomorrow at 2026-10-11T09:00:00+07:00 to call the dentist.", "create_reminder", {"text", "when"}),
    ("Create a calendar event 'Team sync' from 2026-10-12T10:00:00Z to 2026-10-12T10:30:00Z with kk@example.com.",
     "calendar_create_event", {"title", "start", "end"}),
]

ROUTING_CASES = [
    ("what's the wifi password again", "MEMORY"),
    ("remind me when KK's birthday is", "MEMORY"),
    ("did we already pay the electricity bill this month", "MEMORY"),
    ("what's the latest news on SpaceX", "SEARCH"),
    ("what time is it in Tokyo right now", "SEARCH"),
    ("turn off the living room lights", "HA_ACTION"),
    ("set the bedroom aircon to 24 degrees", "HA_ACTION"),
    ("how are you feeling today", "CHAT"),
    ("tell me a joke", "CHAT"),
    ("what is the capital of France", "CHAT"),
    ("write a python function that reverses a string", "CODE"),
    ("why does my regex fail on empty input", "CODE"),
]

REASONING_CASES = [
    ("A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
     "How much does the ball cost? Answer with the number of cents only.", ["5"]),
    ("I have 3 apples. I eat 1, buy 5 more, then give 2 to a friend. "
     "How many apples do I have? Answer with the number only.", ["5"]),
    ("If it takes 5 machines 5 minutes to make 5 widgets, how many minutes "
     "would it take 100 machines to make 100 widgets? Answer with the number only.", ["5"]),
    ("Alice is taller than Bob. Bob is taller than Carol. Who is the shortest? "
     "Answer with the name only.", ["carol"]),
    ("A farmer has 17 sheep. All but 9 die. How many are left? "
     "Answer with the number only.", ["9"]),
    ("What is 15% of 200? Answer with the number only.", ["30"]),
    ("Yesterday was Wednesday. What day is the day after tomorrow? "
     "Answer with the day name only.", ["saturday"]),
]

ROUTING_SYS = (
    "You are an intent router. Classify the user message into exactly one label:\n"
    "MEMORY = recall of the user's personal stored facts/history\n"
    "SEARCH = needs live/current external information\n"
    "HA_ACTION = control a smart-home device\n"
    "CODE = programming help\n"
    "CHAT = general knowledge or casual conversation\n"
    "Reply with ONLY the label."
)

PROMPTED_SYS = (
    "You are a function-calling AI. You may call one function to answer the user.\n"
    "Available functions:\n" +
    "\n".join(json.dumps(t["function"]) for t in TOOLS) +
    "\nRespond with ONLY a JSON object of the form "
    '{"name": "<function-name>", "arguments": {...}}. No other text.'
)


def chat(model, messages, tools=None):
    """POST /api/chat. Returns (content, tool_calls, eval_tps, latency_s, err)."""
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"temperature": 0.2, "seed": 42, "num_predict": 512}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        OLLAMA + "/api/chat", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except Exception as e:
        return "", [], 0.0, time.time() - t0, str(e)
    lat = time.time() - t0
    msg = d.get("message", {})
    tps = d.get("eval_count", 0) / (d.get("eval_duration", 1) / 1e9) if d.get("eval_duration") else 0
    return msg.get("content", ""), msg.get("tool_calls") or [], tps, lat, None


def strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def extract_json(text):
    """First {...} block in text, or None."""
    text = strip_think(text)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def run_probe(model, name, reps, log):
    """Returns dict of metrics + list of per-call records."""
    recs = []
    if name == "toolcall_native":
        for utt, want_fn, want_args in TOOLCALL_CASES * reps:
            content, calls, tps, lat, err = chat(model, [{"role": "user", "content": utt}], tools=TOOLS)
            ok = parse_ok = False
            if err:
                recs.append(dict(case=utt[:40], err=err, lat=lat, ok=False))
                continue
            if calls:
                fn = calls[0].get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parse_ok = True
                ok = fn.get("name") == want_fn and want_args <= set(args)
            recs.append(dict(case=utt[:40], ok=ok, parse_ok=parse_ok, lat=lat,
                             tps=tps, raw=strip_think(content)[:200] or json.dumps(calls)[:200]))
    elif name == "toolcall_prompted":
        for utt, want_fn, want_args in TOOLCALL_CASES * reps:
            content, _, tps, lat, err = chat(
                model, [{"role": "system", "content": PROMPTED_SYS},
                        {"role": "user", "content": utt}])
            obj = extract_json(content) if not err else None
            parse_ok = obj is not None
            ok = (parse_ok and obj.get("name") == want_fn
                  and want_args <= set(obj.get("arguments") or {}))
            recs.append(dict(case=utt[:40], ok=ok, parse_ok=parse_ok, lat=lat,
                             tps=tps, err=err, raw=strip_think(content)[:200]))
    elif name == "routing":
        for utt, want in ROUTING_CASES * reps:
            content, _, tps, lat, err = chat(
                model, [{"role": "system", "content": ROUTING_SYS},
                        {"role": "user", "content": utt}])
            got = strip_think(content).strip().upper().split()[0] if not err and strip_think(content) else ""
            got = re.sub(r"[^A-Z_]", "", got)
            recs.append(dict(case=utt[:40], want=want, got=got, ok=got == want,
                             parse_ok=bool(got), lat=lat, tps=tps, err=err))
    elif name == "reasoning":
        for q, want_any in REASONING_CASES * reps:
            content, _, tps, lat, err = chat(model, [{"role": "user", "content": q}])
            txt = strip_think(content).lower()
            ok = any(w in txt for w in want_any) if not err else False
            recs.append(dict(case=q[:40], ok=ok, parse_ok=not err and bool(txt),
                             lat=lat, tps=tps, err=err, raw=txt[:120]))
    n = len(recs)
    timeouts = sum(1 for r in recs if r.get("err") and "timed out" in r["err"].lower())
    errors = sum(1 for r in recs if r.get("err"))
    lat_ok = [r["lat"] for r in recs if not r.get("err")]
    tps = [r["tps"] for r in recs if r.get("tps")]
    summary = dict(
        n=n, score=round(100 * sum(bool(r.get("ok")) for r in recs) / max(n, 1), 1),
        parse_rate=round(100 * sum(bool(r.get("parse_ok")) for r in recs) / max(n, 1), 1),
        errors=errors, timeouts=timeouts,
        lat_mean=round(statistics.mean(lat_ok), 1) if lat_ok else None,
        lat_p50=round(statistics.median(lat_ok), 1) if lat_ok else None,
        tps_mean=round(statistics.mean(tps), 1) if tps else None,
    )
    log(f"    {name:18s} score={summary['score']:5.1f}% parse={summary['parse_rate']:5.1f}% "
        f"err={errors} t/o={timeouts} p50={summary['lat_p50']}s tps={summary['tps_mean']}")
    return {"summary": summary, "records": recs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["hermes3:8b", "qwen3:4b", "phi3-gguf"])
    ap.add_argument("--probes", nargs="+",
                    default=["toolcall_native", "toolcall_prompted", "routing", "reasoning"])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    global OLLAMA
    import os
    OLLAMA = os.environ.get("OLLAMA_URL", "http://100.75.102.88:11434").rstrip("/")

    out = {"ollama": OLLAMA, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": {}}
    for model in args.models:
        print(f"[{model}]")
        out["results"][model] = {}
        for probe in args.probes:
            out["results"][model][probe] = run_probe(model, probe, args.reps, print)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
