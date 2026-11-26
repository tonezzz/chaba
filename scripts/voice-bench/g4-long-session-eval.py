#!/usr/bin/env python3
"""Long-session Interactions eval: stateful vs stateless token growth.

Free-tier, synthetic text only. Env: GEMINI_API_KEY, MODEL, OUT.
"""
import json
import os
import time
from datetime import datetime, timezone

from google import genai

MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-long-session-result.json")
SYS = ("You are a concise note-taking assistant. Remember every codename and "
       "meeting detail for later recall. When asked to schedule a meeting, call "
       "the schedule_meeting tool immediately.")
TOOLS = [{
    "type": "function",
    "name": "schedule_meeting",
    "description": "Schedules a meeting with attendees, date, time and topic.",
    "parameters": {"type": "object", "properties": {
        "attendees": {"type": "array", "items": {"type": "string"}},
        "date": {"type": "string"}, "time": {"type": "string"}, "topic": {"type": "string"}},
        "required": ["attendees", "date", "time", "topic"]},
}]
FACTS = [
    "Project codename one is Lighthouse.",
    "Project codename two is Birch.",
    "Project codename three is Northwind.",
    "Project codename four is Comet.",
    "Project codename five is Beacon.",
    "Project codename six is Harbor.",
    "Project codename seven is Falcon.",
    "Project codename eight is Willow.",
]
MEETINGS = [
    ("Schedule a meeting with Bob on 2025-03-14 at 10:00 about planning.", "2025-03-14"),
    ("Schedule a meeting with Carol on 2025-04-02 at 13:30 about migration.", "2025-04-02"),
    ("Schedule a meeting with Dan on 2025-05-19 at 09:15 about renewal.", "2025-05-19"),
    ("Schedule a meeting with Erin on 2025-06-07 at 16:45 about audit.", "2025-06-07"),
]
FILLERS = [
    "In one word, what kind of work is this?",
    "In one word, are you keeping the notes?",
    "In one word, should I continue?",
    "In one word, are we ready for recall?",
]
RECALL = ("List all eight project codenames, then list the four meeting dates. "
          "Do not omit any.")


def retry(fn, attempts=4):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise last


def usage(r):
    u = getattr(r, "usage", None)
    if not u:
        return {"input": 0, "output": 0}
    return {"input": getattr(u, "total_input_tokens", 0) or 0,
            "output": getattr(u, "total_output_tokens", 0) or 0}


def run(stateful):
    client = genai.Client()
    common = {"model": MODEL, "system_instruction": SYS, "tools": TOOLS}
    prev = None
    history = [{"type": "user_input", "content": [{"type": "text", "text": FACTS[0]}]}]
    calls = []

    def send(text=None, step=None):
        nonlocal prev
        if stateful:
            payload = {"input": text if step is None else [step]}
            if prev:
                payload["previous_interaction_id"] = prev
        else:
            if text is not None:
                history.append({"type": "user_input", "content": [{"type": "text", "text": text}]})
            if step is not None:
                history.append(step)
            payload = {"input": [dict(s) for s in history]}
        r = retry(lambda: client.interactions.create(**common, **payload))
        if not stateful:
            history.extend([s.model_dump() for s in r.steps])
        else:
            prev = r.id
        calls.append({"usage": usage(r), "steps": [s.type for s in r.steps]})
        return r

    t0 = time.monotonic()
    for f in FACTS[1:]:
        send(text=f)
    for req, date in MEETINGS:
        r = send(text=req)
        fc = next((s for s in r.steps if s.type == "function_call"), None)
        step = {"type": "function_result", "name": getattr(fc, "name", "schedule_meeting"),
                "call_id": getattr(fc, "id", ""),
                "result": [{"type": "text", "text": json.dumps({"ok": True, "scheduled": True})}]}
        send(step=step)
    for filler in FILLERS:
        send(text=filler)
    final = send(text=RECALL)
    ins = [c["usage"]["input"] for c in calls]
    outs = [c["usage"]["output"] for c in calls]
    text = (getattr(final, "output_text", None) or "").lower()
    recall = sum(1 for f in FACTS if f.split("is ")[-1].rstrip(".").lower() in text)
    dates = sum(1 for _, d in MEETINGS if d in text)
    return {"mode": "stateful" if stateful else "stateless", "calls": len(calls),
            "input_tokens": sum(ins), "output_tokens": sum(outs),
            "first_input": ins[0], "last_input": ins[-1],
            "input_series": ins, "recall_codenames": recall, "recall_dates": dates,
            "final_text": getattr(final, "output_text", None),
            "mean_step_types": sorted(set(s for c in calls for s in c["steps"])),
            "elapsed_s": round(time.monotonic() - t0, 2)}


def main():
    out = {"schema": "g4-long-session-eval", "schema_version": 1,
           "date": datetime.now(timezone.utc).isoformat(), "model": MODEL,
           "key_printed": False, "arms": {}}
    for stateful in (True, False):
        mode = "stateful" if stateful else "stateless"
        try:
            r = run(stateful)
        except Exception as e:
            r = {"mode": mode, "error": f"{type(e).__name__}: {str(e)[:250]}"}
        out["arms"][mode] = r
        print(mode, json.dumps({k: v for k, v in r.items() if k not in ("input_series", "final_text")})[:500], flush=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
