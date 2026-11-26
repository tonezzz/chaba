#!/usr/bin/env python3
"""Compare gemini-3.1-flash-lite with 3.5-flash-lite on free tier.

Reuses the graded stateful agent loop from g4-interactions-eval.py and adds a
small surface-compatibility comparison. Read-only, synthetic text only.
Env: GEMINI_API_KEY, OUT, TASK_LIMIT.
"""
import importlib.util
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone

from google import genai

OUT = os.environ.get("OUT", "/tmp/opencode/g4-model-compare.json")
TASK_LIMIT = int(os.environ.get("TASK_LIMIT", "4"))
MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]

spec = importlib.util.spec_from_file_location(
    "g", "/tmp/opencode/g4-interactions-eval.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
client = genai.Client()


def dump(obj):
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    return str(obj)


def norm(s):
    s = re.sub(r"\([^)]*\)", "", str(s or "")).lower().strip()
    s = re.sub(r"^(the|a|an)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip(" .,!?")


def grade_relaxed(r):
    got, exp = r.get("tool_args") or {}, r.get("expected_args") or {}
    return bool(got.get("date") == exp.get("date") and got.get("time") == exp.get("time")
                and sorted(got.get("attendees") or []) == sorted(exp.get("attendees") or [])
                and (norm(exp.get("topic")) in norm(got.get("topic"))
                     or norm(got.get("topic")) in norm(exp.get("topic"))))


def agent_loop(model):
    rows = []
    for i, task in enumerate(g.TASKS[:TASK_LIMIT], 1):
        try:
            r = g.run_interactions(client, task, model, True)
            r["task"] = i
            r["tool_relaxed"] = grade_relaxed(r)
            row = {k: r.get(k) for k in ("task", "tool_ok", "tool_relaxed", "recall_ok",
                                         "usage", "elapsed_s", "steps", "tool_args",
                                         "expected_args", "final_text")}
        except Exception as e:
            row = {"task": i, "error": f"{type(e).__name__}: {str(e)[:250]}"}
        rows.append(row)
        print("agent", model, i, "tool", row.get("tool_ok"), "relaxed", row.get("tool_relaxed"),
              "recall", row.get("recall_ok"), "err", str(row.get("error", ""))[:100], flush=True)
    good = [r for r in rows if not r.get("error")]
    return {
        "rows": rows, "completed": len(good), "n": len(rows),
        "tool_exact": sum(bool(r.get("tool_ok")) for r in good),
        "tool_relaxed": sum(bool(r.get("tool_relaxed")) for r in good),
        "recall": sum(bool(r.get("recall_ok")) for r in good),
        "both_relaxed": sum(bool(r.get("tool_relaxed")) and bool(r.get("recall_ok")) for r in good),
        "input_tokens": sum((r.get("usage") or {}).get("input", 0) for r in good),
        "output_tokens": sum((r.get("usage") or {}).get("output", 0) for r in good),
        "mean_elapsed_s": round(sum(r.get("elapsed_s", 0) for r in good) / len(good), 2) if good else None,
    }


def streaming(model):
    stream = client.interactions.create(
        model=model, input="Count from 1 to 8, separated by commas. Nothing else.", stream=True)
    events, deltas, text, status, usage = Counter(), Counter(), "", None, None
    for ev in stream:
        et = getattr(ev, "event_type", None)
        events[str(et)] += 1
        if et == "step.delta":
            d = getattr(ev, "delta", None)
            deltas[str(getattr(d, "type", None))] += 1
            if getattr(d, "type", None) == "text":
                text += getattr(d, "text", "") or ""
        elif et == "interaction.completed":
            inter = getattr(ev, "interaction", None)
            status = getattr(inter, "status", None)
            usage = dump(getattr(inter, "usage", None))
    return {"event_types": dict(events), "delta_types": dict(deltas), "text": text[:160],
            "status": status, "usage": usage}


def structured(model):
    schema = {"type": "object", "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "summary": {"type": "string"}}, "required": ["sentiment", "summary"]}
    r = client.interactions.create(
        model=model, input="The new UI is incredibly intuitive. Summarize in one short sentence.",
        response_format={"type": "text", "mime_type": "application/json", "schema": schema})
    raw = getattr(r, "output_text", None)
    parsed = json.loads(raw) if raw else None
    return {"raw": (raw or "")[:200],
            "schema_valid": bool(isinstance(parsed, dict)
                                 and parsed.get("sentiment") in ("positive", "neutral", "negative")
                                 and isinstance(parsed.get("summary"), str)),
            "usage": dump(getattr(r, "usage", None))}


def background(model):
    r = client.interactions.create(
        model=model, input="Write one sentence about lighthouses.", background=True)
    iid = getattr(r, "id", None)
    statuses = [getattr(r, "status", None)]
    t0 = time.monotonic()
    while time.monotonic() - t0 < 45:
        g_ = client.interactions.get(id=iid)
        st = getattr(g_, "status", None)
        statuses.append(st)
        if st not in ("in_progress", "queued", "requires_action"):
            break
        time.sleep(3)
    return {"statuses": statuses, "terminal": statuses[-1],
            "output_text": str(getattr(g_, "output_text", None))[:160]}


def flex(model):
    r = client.interactions.create(
        model=model, input="Reply with exactly: TIEROK", service_tier="flex")
    return {"echoed_tier": str(getattr(r, "service_tier", None)),
            "text": str(getattr(r, "output_text", None))[:60],
            "usage": dump(getattr(r, "usage", None))}


def code_execution(model):
    r = client.interactions.create(
        model=model,
        input="Use Python to compute the 20th Fibonacci number. Reply with the number only.",
        tools=[{"type": "code_execution"}])
    return {"text": str(getattr(r, "output_text", None))[:100],
            "steps": [str(getattr(s, "type", None)) for s in (getattr(r, "steps", None) or [])],
            "usage": dump(getattr(r, "usage", None))}


SURFACES = {"streaming": streaming, "structured": structured, "background": background,
            "flex": flex, "code_execution": code_execution}


def main():
    out = {"schema": "g4-model-compare", "schema_version": 1,
           "date": datetime.now(timezone.utc).isoformat(), "host": "idc03",
           "key_printed": False, "task_limit": TASK_LIMIT, "models": {}}
    for model in MODELS:
        entry = {"agent_loop": agent_loop(model), "surfaces": {}}
        for name, fn in SURFACES.items():
            try:
                entry["surfaces"][name] = {"ok": True, **fn(model)}
            except Exception as e:
                entry["surfaces"][name] = {"ok": False,
                                           "error": f"{type(e).__name__}: {str(e)[:250]}"}
            print("surface", model, name, entry["surfaces"][name]["ok"], flush=True)
        out["models"][model] = entry
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
