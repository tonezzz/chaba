#!/usr/bin/env python3
"""Small multi-turn text-agent eval: Gemini 4 + Interactions API vs 3.x legacy.

Read-only eval using synthetic task text. Env: GEMINI_API_KEY, G4_MODEL,
BASELINE_MODEL, OUT. Writes one JSON result document.
"""
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from google import genai
from google.genai import types

MODEL = os.environ.get("G4_MODEL", "gemini-4-neon")
BASELINE = os.environ.get("BASELINE_MODEL", "gemini-3.8-flash")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-eval-result.json")

TOOLS = [{
    "type": "function",
    "name": "schedule_meeting",
    "description": "Schedules a meeting with attendees, date, time and topic.",
    "parameters": {
        "type": "object",
        "properties": {
            "attendees": {"type": "array", "items": {"type": "string"}},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "time": {"type": "string", "description": "HH:MM"},
            "topic": {"type": "string"},
        },
        "required": ["attendees", "date", "time", "topic"],
    },
}]
SYS = ("You are a concise scheduling assistant. Keep facts in mind across "
       "turns. When asked to schedule a meeting, call the schedule_meeting "
       "tool immediately with all four arguments.")

TASKS = [
    {"fact": "My project codename is Lighthouse. Remember it for later.",
     "tool": "Schedule a meeting with Bob and Alice on 2025-03-14 at 10:00 about Q3 planning.",
     "args": {"attendees": ["Bob", "Alice"], "date": "2025-03-14", "time": "10:00", "topic": "Q3 planning"},
     "recall": "What is my project codename, and when is the Q3 planning meeting?",
     "tokens": [["lighthouse"], ["2025-03-14", "march 14, 2025", "14 march 2025"], ["10:00"]]},
    {"fact": "Our staging cluster is called Birch. Remember it for later.",
     "tool": "Schedule a meeting with Carol and Dan on 2025-04-02 at 13:30 about the migration.",
     "args": {"attendees": ["Carol", "Dan"], "date": "2025-04-02", "time": "13:30", "topic": "the migration"},
     "recall": "What is our staging cluster called, and what time is the migration meeting?",
     "tokens": [["birch"], ["13:30"]]},
    {"fact": "The customer account is named Northwind. Remember it for later.",
     "tool": "Schedule a meeting with Erin on 2025-05-19 at 09:15 about renewal terms.",
     "args": {"attendees": ["Erin"], "date": "2025-05-19", "time": "09:15", "topic": "renewal terms"},
     "recall": "Which customer account did I mention, and on what date is the renewal meeting?",
     "tokens": [["northwind"], ["2025-05-19", "may 19, 2025", "19 may 2025"]]},
    {"fact": "My preferred timezone is Bangkok. Remember it for later.",
     "tool": "Schedule a meeting with Frank and Grace on 2025-06-07 at 16:45 about the audit.",
     "args": {"attendees": ["Frank", "Grace"], "date": "2025-06-07", "time": "16:45", "topic": "the audit"},
     "recall": "What is my preferred timezone, and who is attending the audit meeting?",
     "tokens": [["bangkok"], ["frank"], ["grace"]]},
    {"fact": "The release train is named Comet. Remember it for later.",
     "tool": "Schedule a meeting with Heidi on 2025-07-21 at 11:00 about the rollout.",
     "args": {"attendees": ["Heidi"], "date": "2025-07-21", "time": "11:00", "topic": "the rollout"},
     "recall": "What is the release train called, and what is the topic of the meeting?",
     "tokens": [["comet"], ["rollout"]]},
    {"fact": "Our fallback provider is Ollama. Remember it for later.",
     "tool": "Schedule a meeting with Ivan and Judy on 2025-08-11 at 08:30 about failover.",
     "args": {"attendees": ["Ivan", "Judy"], "date": "2025-08-11", "time": "08:30", "topic": "failover"},
     "recall": "What is our fallback provider, and when is the failover meeting?",
     "tokens": [["ollama"], ["2025-08-11", "august 11, 2025", "11 august 2025"], ["08:30"]]},
]


def retry(fn, attempts=3):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise last


def find_usage(obj):
    u = getattr(obj, "usage", None)
    if u is None:
        return {}
    d = u.model_dump() if hasattr(u, "model_dump") else (u if isinstance(u, dict) else {})
    out = {}
    for key in ("input_tokens", "prompt_token_count", "total_input_tokens"):
        if isinstance(d.get(key), int):
            out["input"] = d[key]
            break
    for key in ("output_tokens", "candidates_token_count", "total_output_tokens"):
        if isinstance(d.get(key), int):
            out["output"] = d[key]
            break
    if isinstance(d.get("total_tokens"), int):
        out["total"] = d["total_tokens"]
    return out


def step_types(obj):
    return [getattr(s, "type", None) for s in (getattr(obj, "steps", None) or [])]


def first_fc(obj):
    for s in (getattr(obj, "steps", None) or []):
        if getattr(s, "type", None) == "function_call":
            return s
    return None


def grade_tool(fc, expected):
    if fc is None or getattr(fc, "name", None) != "schedule_meeting":
        return False
    args = getattr(fc, "arguments", None) or {}
    if not isinstance(args, dict):
        return False
    norm = dict(args)
    if "attendees" in norm and isinstance(norm["attendees"], list):
        norm["attendees"] = sorted(norm["attendees"])
    exp = dict(expected)
    exp["attendees"] = sorted(exp["attendees"])
    return norm == exp


def grade_recall(text, groups):
    t = (text or "").lower()
    return all(any(alt.lower() in t for alt in group) for group in groups)


LEGACY_TOOLS = [types.Tool(function_declarations=[types.FunctionDeclaration(
    name="schedule_meeting",
    description="Schedules a meeting with attendees, date, time and topic.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "attendees": types.Schema(type="ARRAY", items=types.Schema(type="STRING")),
            "date": types.Schema(type="STRING", description="YYYY-MM-DD"),
            "time": types.Schema(type="STRING", description="HH:MM"),
            "topic": types.Schema(type="STRING"),
        },
        required=["attendees", "date", "time", "topic"],
    ),
)])]


def run_interactions(client, task, model, stateful):
    calls, usage_total, steps = [], {"input": 0, "output": 0}, []
    t0 = time.monotonic()
    if stateful:
        base = {}
    else:
        base = {"store": False}

    def create(**kw):
        d = dict(base)
        d.update(kw)
        return retry(lambda: client.interactions.create(**d))

    history = [{"type": "user_input", "content": [{"type": "text", "text": task["fact"]}]}] if not stateful else task["fact"]
    r1 = create(model=model, input=history, system_instruction=SYS, tools=TOOLS)
    calls.append({"turn": 1, "usage": find_usage(r1), "steps": step_types(r1)})
    steps += step_types(r1)

    if stateful:
        prev = r1.id
        r2 = create(model=model, input=task["tool"], previous_interaction_id=prev,
                    system_instruction=SYS, tools=TOOLS)
    else:
        hist = [{"type": "user_input", "content": [{"type": "text", "text": task["fact"]}]}]
        hist += [s.model_dump() for s in r1.steps]
        hist.append({"type": "user_input", "content": [{"type": "text", "text": task["tool"]}]})
        r2 = create(model=model, input=hist, system_instruction=SYS, tools=TOOLS)
    calls.append({"turn": 2, "usage": find_usage(r2), "steps": step_types(r2)})
    steps += step_types(r2)
    fc = first_fc(r2)

    result = [{"type": "text", "text": json.dumps({"ok": True, "scheduled": True})}]
    fresult = {"type": "function_result", "name": getattr(fc, "name", "schedule_meeting"),
               "call_id": getattr(fc, "id", ""), "result": result}
    if stateful:
        prev = r2.id
        r3a = create(model=model, input=[fresult], previous_interaction_id=prev,
                     system_instruction=SYS, tools=TOOLS)
    else:
        hist = [{"type": "user_input", "content": [{"type": "text", "text": task["fact"]}]}]
        hist += [s.model_dump() for s in r1.steps]
        hist.append({"type": "user_input", "content": [{"type": "text", "text": task["tool"]}]})
        hist += [s.model_dump() for s in r2.steps]
        hist.append(fresult)
        r3a = create(model=model, input=hist, system_instruction=SYS, tools=TOOLS)
    calls.append({"turn": 3, "usage": find_usage(r3a), "steps": step_types(r3a)})
    steps += step_types(r3a)

    if stateful:
        prev = r3a.id
        r3b = create(model=model, input=task["recall"], previous_interaction_id=prev,
                     system_instruction=SYS, tools=TOOLS)
    else:
        hist.append(fresult)
        hist += [s.model_dump() for s in r3a.steps]
        hist.append({"type": "user_input", "content": [{"type": "text", "text": task["recall"]}]})
        r3b = create(model=model, input=hist, system_instruction=SYS, tools=TOOLS)
    calls.append({"turn": 4, "usage": find_usage(r3b), "steps": step_types(r3b)})
    steps += step_types(r3b)

    for c in calls:
        for k in ("input", "output"):
            usage_total[k] += c["usage"].get(k, 0) or 0
    return {
        "tool_ok": grade_tool(fc, task["args"]),
        "tool_args": (getattr(fc, "arguments", None) if fc else None),
        "expected_args": task["args"],
        "recall_ok": grade_recall(getattr(r3b, "output_text", None), task["tokens"]),
        "final_text": getattr(r3b, "output_text", None),
        "usage": usage_total,
        "calls": calls,
        "steps": sorted(set(s for s in steps if s)),
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def run_legacy(client, task, model):
    contents = []
    usage_total = {"input": 0, "output": 0}
    t0 = time.monotonic()

    def call():
        r = retry(lambda: client.models.generate_content(
            model=model, contents=contents,
            config=types.GenerateContentConfig(tools=LEGACY_TOOLS, system_instruction=SYS)))
        um = getattr(r, "usage_metadata", None)
        if um:
            usage_total["input"] += getattr(um, "prompt_token_count", 0) or 0
            usage_total["output"] += getattr(um, "candidates_token_count", 0) or 0
        return r

    contents.append(types.Content(role="user", parts=[types.Part(text=task["fact"])]))
    r1 = call()
    contents.append(r1.candidates[0].content)
    contents.append(types.Content(role="user", parts=[types.Part(text=task["tool"])]))
    r2 = call()
    r2_content = r2.candidates[0].content
    contents.append(r2_content)
    fc = next((p.function_call for p in r2_content.parts if getattr(p, "function_call", None)), None)
    if fc:
        contents.append(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name=fc.name, response={"ok": True, "scheduled": True}))]))
    r3 = call()
    final = getattr(r3, "text", None)
    return {
        "tool_ok": (grade_tool(SimpleNamespace(name=fc.name, arguments=dict(fc.args or {})),
                               task["args"]) if fc else False),
        "tool_args": (dict(fc.args or {}) if fc else None),
        "expected_args": task["args"],
        "recall_ok": grade_recall(final, task["tokens"]),
        "final_text": final,
        "usage": usage_total,
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def main():
    client = genai.Client()
    arms = {
        "interactions_stateful_" + MODEL: lambda t: run_interactions(client, t, MODEL, True),
        "interactions_stateless_" + MODEL: lambda t: run_interactions(client, t, MODEL, False),
        "legacy_generatecontent_" + BASELINE: lambda t: run_legacy(client, t, BASELINE),
    }
    out = {"schema": "g4-interactions-eval", "schema_version": 1,
           "date": datetime.now(timezone.utc).isoformat(), "host": "idc03",
           "key_printed": False, "model": MODEL, "baseline": BASELINE, "arms": {}}
    for name, fn in arms.items():
        rows = []
        for i, task in enumerate(TASKS, 1):
            try:
                r = fn(task)
                r["task"] = i
            except Exception as e:
                r = {"task": i, "error": f"{type(e).__name__}: {str(e)[:220]}"}
            rows.append(r)
            print(name, i, "tool", rows[-1].get("tool_ok"), "recall", rows[-1].get("recall_ok"),
                  "error", rows[-1].get("error"), flush=True)
        good = [r for r in rows if r.get("error") is None]
        out["arms"][name] = {
            "rows": rows,
            "n": len(rows),
            "completed": len(good),
            "tool_exact": sum(bool(r.get("tool_ok")) for r in good),
            "recall_ok": sum(bool(r.get("recall_ok")) for r in good),
            "both_ok": sum(bool(r.get("tool_ok")) and bool(r.get("recall_ok")) for r in good),
            "input_tokens": sum((r.get("usage") or {}).get("input", 0) for r in good),
            "output_tokens": sum((r.get("usage") or {}).get("output", 0) for r in good),
            "mean_elapsed_s": round(sum(r.get("elapsed_s", 0) for r in good) / len(good), 2) if good else None,
        }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
