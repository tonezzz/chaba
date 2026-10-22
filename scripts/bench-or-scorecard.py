#!/usr/bin/env python3
"""bench-or-scorecard.py — card openclaw-bench-per-model-scorecard (KNB-0174).

Per-model scorecard across the GhostRoute OR :free rotation (the model
allowlist in tony-omen ~/.openclaw/openclaw.json), run through the same
OpenAI-compat surface the openclaw-gateway uses: POST /chat/completions
on OpenRouter with the model pinned. The gateway itself is loopback-only
on tony-omen (:18789) — per-model pinning must go to OR directly; this
is the documented emulation (docs/ssot/jobs/models/2026-10-22-edu-agent-bench.yml).

Probe shape follows scripts/bench-hermes.py (the jev-bench shape used for
the T1 eval): per model x arm -> score%, parse_rate%, errors, timeouts,
mean/p50 latency, tok/s. Arms:

  toolcall_native    `tools=` function calling — name + required args.
  toolcall_prompted  prompt-only JSON call emission (no tools=) — the
                     resilience surface for models without native tools.
  routing            intent classification into a fixed label set.
  reasoning          short checkable Q&A.
  json_strict        response_format=json_object — the schema-shape
                     flake that kills free models on tool loops.

Budget guards (card brief): <=50 calls/model (we use ~33), global min
request interval to protect the shared OR key (mddb embeddings),
per-model circuit breaker so a dead model can't hang the run.

Usage:
  OPENROUTER_API_KEY=... python3 scripts/bench-or-scorecard.py \
      --models-file /tmp/models.json --out reports/or-free-scorecard-2026-10-22
Env: OPENROUTER_API_KEY (required — load from secrets on a key-holding
host, never commit), OR_BASE (default https://openrouter.ai/api/v1).
"""
import argparse
import concurrent.futures
import json
import os
import re
import statistics
import threading
import time
import urllib.error
import urllib.request

OR_BASE = os.environ.get("OR_BASE", "https://openrouter.ai/api/v1").rstrip("/")
TIMEOUT = 90
MIN_INTERVAL = 3.5          # global min seconds between request starts
CBREAK = 6                  # consecutive failures -> abort model
MAX_ROUNDS_NOTE = "single-shot probes (no tool loop) — each case is 1 call"

_tools = [  # same 5 tool defs as bench-hermes.py — continuity with T1 eval
    {"type": "function", "function": {
        "name": "get_weather", "description": "Get current weather for a location",
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string", "description": "City name"},
            "units": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
         "required": ["location"]}}},
    {"type": "function", "function": {
        "name": "set_light", "description": "Set a Home Assistant light's state",
        "parameters": {"type": "object", "properties": {
            "entity_id": {"type": "string"},
            "brightness_pct": {"type": "integer", "minimum": 0, "maximum": 100},
            "rgb_color": {"type": "array", "items": {"type": "integer"}}},
         "required": ["entity_id", "brightness_pct"]}}},
    {"type": "function", "function": {
        "name": "memory_search", "description": "Search the personal memory bank",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "bank": {"type": "string", "enum": ["all", "personal", "home", "people"]}},
         "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "create_reminder", "description": "Create a reminder for the user",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "when": {"type": "string", "description": "ISO-8601 datetime"}},
         "required": ["text", "when"]}}},
    {"type": "function", "function": {
        "name": "calendar_create_event", "description": "Create a calendar event",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "start": {"type": "string"},
            "end": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string"}}},
         "required": ["title", "start", "end"]}}},
]

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
]

# (prompt, required top-level keys) — schema-shape flake probe.
JSON_STRICT_CASES = [
    ('Return a JSON object: {"action": "search", "query": "wifi password", "confidence": 0.9}. '
     'Echo it back exactly.', {"action", "query", "confidence"}),
    ('Extract to JSON: "Tony asked Ada to turn off the porch light at 21:04". '
     'Keys: who (string), what (string), when (string).', {"who", "what", "when"}),
    ('Reply ONLY with JSON: {"ok": true, "items": ["a","b","c"], "count": 3}.',
     {"ok", "items", "count"}),
    ('Classify this utterance "remind me to call the dentist" as JSON: '
     '{"intent": one of MEMORY|SEARCH|ACTION|CHAT, "confidence": number 0-1}.',
     {"intent", "confidence"}),
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
    "\n".join(json.dumps(t["function"]) for t in _tools) +
    "\nRespond with ONLY a JSON object of the form "
    '{"name": "<function-name>", "arguments": {...}}. No other text.'
)


class RateLimiter:
    def __init__(self, interval):
        self.interval, self.lock, self.next = interval, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            t = max(now, self.next)
            self.next = t + self.interval
            delay = t - now
        if delay > 0:
            time.sleep(delay)


class ORClient:
    def __init__(self, key, limiter):
        self.key, self.limiter = key, limiter

    def chat(self, model, messages, tools=None, json_mode=False):
        """Returns (content, tool_calls, usage, resolved_model, latency, err)."""
        body = {"model": model, "messages": messages, "temperature": 0.2,
                "max_tokens": 512}
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            OR_BASE + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.key}",
                     "HTTP-Referer": "https://github.com/tonezzz/chaba",
                     "X-Title": "chaba or-scorecard"})
        err = None
        for attempt in range(2):  # one retry on transient
            self.limiter.wait()
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    d = json.loads(r.read())
                ch = (d.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                return (msg.get("content") or "", msg.get("tool_calls") or [],
                        d.get("usage") or {}, d.get("model"),
                        time.time() - t0, None)
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read()[:200].decode(errors="replace")
                except Exception:
                    detail = ""
                err = f"HTTP {e.code} {detail[:120]}"
                lat = time.time() - t0
                if e.code not in (429, 500, 502, 503, 504):
                    return "", [], {}, None, lat, err
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                lat = time.time() - t0
            time.sleep(4 * (attempt + 1))
        return "", [], {}, None, lat, err


def strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def extract_json(text):
    m = re.search(r"\{.*\}", strip_think(text), flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def run_probe(client, model, name, log):
    recs = []
    fail_streak = 0

    def rec(case, ok=False, parse_ok=False, lat=0, tps=0, err=None, raw="", resolved=None):
        nonlocal fail_streak
        fail_streak = 0 if not err else fail_streak + 1
        recs.append(dict(case=case[:40], ok=ok, parse_ok=parse_ok, lat=round(lat, 2),
                         tps=round(tps, 1), err=err, raw=(raw or "")[:200],
                         resolved=resolved))
        return fail_streak >= CBREAK

    def tps_of(usage, lat):
        ct = int((usage or {}).get("completion_tokens") or 0)
        return ct / lat if lat > 0 else 0

    aborted = False
    if name == "toolcall_native":
        for utt, want_fn, want_args in TOOLCALL_CASES:
            content, calls, usage, resolved, lat, err = client.chat(
                model, [{"role": "user", "content": utt}], tools=_tools)
            ok = parse_ok = False
            if not err and calls:
                fn = (calls[0].get("function") or {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parse_ok = True
                ok = fn.get("name") == want_fn and want_args <= set(args)
            aborted = rec(utt, ok, parse_ok, lat, tps_of(usage, lat), err,
                          strip_think(content) or json.dumps(calls)[:200], resolved)
            if aborted:
                break
    elif name == "toolcall_prompted":
        for utt, want_fn, want_args in TOOLCALL_CASES:
            content, _, usage, resolved, lat, err = client.chat(
                model, [{"role": "system", "content": PROMPTED_SYS},
                        {"role": "user", "content": utt}])
            obj = extract_json(content) if not err else None
            parse_ok = obj is not None
            ok = (parse_ok and obj.get("name") == want_fn
                  and want_args <= set(obj.get("arguments") or {}))
            aborted = rec(utt, ok, parse_ok, lat, tps_of(usage, lat), err,
                          strip_think(content), resolved)
            if aborted:
                break
    elif name == "routing":
        for utt, want in ROUTING_CASES:
            content, _, usage, resolved, lat, err = client.chat(
                model, [{"role": "system", "content": ROUTING_SYS},
                        {"role": "user", "content": utt}])
            txt = strip_think(content)
            got = re.sub(r"[^A-Z_]", "", txt.strip().upper().split()[0]) if not err and txt else ""
            aborted = rec(utt, got == want, bool(got), lat, tps_of(usage, lat), err,
                          txt, resolved)
            if aborted:
                break
    elif name == "reasoning":
        for q, want_any in REASONING_CASES:
            content, _, usage, resolved, lat, err = client.chat(
                model, [{"role": "user", "content": q}])
            txt = strip_think(content).lower()
            aborted = rec(q, bool(txt) and any(w in txt for w in want_any),
                          bool(txt), lat, tps_of(usage, lat), err, txt, resolved)
            if aborted:
                break
    elif name == "json_strict":
        for p, want_keys in JSON_STRICT_CASES:
            content, _, usage, resolved, lat, err = client.chat(
                model, [{"role": "user", "content": p}], json_mode=True)
            obj = extract_json(content) if not err else None
            parse_ok = obj is not None
            ok = parse_ok and want_keys <= set(obj)
            aborted = rec(p, ok, parse_ok, lat, tps_of(usage, lat), err,
                          strip_think(content), resolved)
            if aborted:
                break

    n = len(recs)
    timeouts = sum(1 for r in recs if r.get("err") and "timed out" in str(r["err"]).lower())
    errors = sum(1 for r in recs if r.get("err"))
    lat_ok = [r["lat"] for r in recs if not r.get("err")]
    tps = [r["tps"] for r in recs if r.get("tps")]
    resolved = sorted({r["resolved"] for r in recs if r.get("resolved")})
    summary = dict(
        n=n, aborted=aborted,
        score=round(100 * sum(bool(r.get("ok")) for r in recs) / max(n, 1), 1),
        parse_rate=round(100 * sum(bool(r.get("parse_ok")) for r in recs) / max(n, 1), 1),
        errors=errors, timeouts=timeouts,
        lat_mean=round(statistics.mean(lat_ok), 1) if lat_ok else None,
        lat_p50=round(statistics.median(lat_ok), 1) if lat_ok else None,
        tps_mean=round(statistics.mean(tps), 1) if tps else None,
        resolved_models=resolved)
    log(f"    {model:55s} {name:18s} score={summary['score']:5.1f}% "
        f"parse={summary['parse_rate']:5.1f}% err={errors} t/o={timeouts} "
        f"p50={summary['lat_p50']}s tps={summary['tps_mean']}"
        + (" ABORTED" if aborted else ""))
    return {"summary": summary, "records": recs}


def bench_model(client, model, probes, log):
    res = {}
    for probe in probes:
        res[probe] = run_probe(client, model, probe, log)
    return model, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-file", required=True,
                    help="JSON: {bench: [...], dead: [...], paid: [...]}")
    ap.add_argument("--probes", nargs="+",
                    default=["toolcall_native", "toolcall_prompted", "routing",
                             "reasoning", "json_strict"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", required=True, help="report prefix (no ext)")
    args = ap.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY not set")
    spec = json.load(open(args.models_file))
    models = spec["bench"]
    limiter = RateLimiter(MIN_INTERVAL)
    client = ORClient(key, limiter)

    out = {"at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "or_base": OR_BASE,
           "note": MAX_ROUNDS_NOTE, "dead_ids": spec.get("dead", []),
           "paid_refs": spec.get("paid", []), "results": {}}
    log = lambda *a: print(*a, flush=True)
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(bench_model, client, m, args.probes, log): m
                for m in models}
        for fut in concurrent.futures.as_completed(futs):
            m, res = fut.result()
            out["results"][m] = res
    out["elapsed_s"] = round(time.time() - t0)

    jpath, mpath = args.out + ".json", args.out + ".md"
    with open(jpath, "w") as f:
        json.dump(out, f, indent=1)
    write_md(out, mpath, spec)
    print(f"wrote {jpath} and {mpath} in {out['elapsed_s']}s")


def write_md(out, path, spec):
    arms = ["toolcall_native", "toolcall_prompted", "routing", "reasoning",
            "json_strict"]
    lines = ["# OR :free rotation scorecard — " + out["at"], "",
             "Shape: jev-bench/bench-hermes arms vs OR /chat/completions, model",
             "pinned per row. `openrouter/free` row = auto-router (resolved_models",
             "shows what it actually picked). Dead ids = in the ghostroute",
             "allowlist but absent from the live OR :free shelf today.", ""]
    lines.append("## Scorecard")
    lines.append("")
    hdr = "| model | " + " | ".join(a.replace("toolcall_", "tc_") for a in arms) + \
          " | p50 s | err | tps |"
    lines += [hdr, "|" + "---|" * (len(arms) + 4)]
    order = spec.get("bench", [])
    def row(m):
        r = out["results"].get(m) or {}
        cells, lats, errs, tps = [], [], 0, []
        for a in arms:
            s = (r.get(a) or {}).get("summary") or {}
            if not s:
                cells.append("-")
                continue
            mark = "*" if s.get("aborted") else ""
            cells.append(f"{s.get('score','-')}{mark}")
            if s.get("lat_p50"):
                lats.append(s["lat_p50"])
            errs += s.get("errors") or 0
            if s.get("tps_mean"):
                tps.append(s["tps_mean"])
        p50 = round(statistics.median(lats), 1) if lats else "-"
        tp = round(statistics.mean(tps), 1) if tps else "-"
        return f"| {m} | " + " | ".join(cells) + f" | {p50} | {errs} | {tp} |"
    for m in order:
        if m in out["results"]:
            lines.append(row(m))
    lines += ["", "(* = run aborted early by circuit breaker — 6 consecutive",
              "  failures; score is over attempted cases only)", ""]
    if out.get("dead_ids"):
        lines += ["## Dead ids still in the ghostroute allowlist", ""]
        for d in out["dead_ids"]:
            lines.append(f"- `{d}` — not on the live :free shelf; drop from rotation")
        lines.append("")
    resolved = out["results"].get("openrouter/free", {})
    seen = set()
    for a in arms:
        seen.update((resolved.get(a) or {}).get("summary", {}).get("resolved_models") or [])
    if seen:
        lines += ["## openrouter/free resolved to", ""]
        for s in sorted(seen):
            lines.append(f"- `{s}`")
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
