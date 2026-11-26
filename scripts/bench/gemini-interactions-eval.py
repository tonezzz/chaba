#!/usr/bin/env python3
"""Gemini Interactions API eval — stateful vs stateless vs generateContent.

Read-only eval. Runs a fixed 8-task tool+recall set across lanes:
  g35l_stateful/g31l_stateful  gemini-3.5/3.1-flash-lite, previous_interaction_id
  g35l_int/g31l_int            same models, full step history resent each call
  g35l_gen                     gemini-3.5-flash-lite via models.generate_content
  g4h_stateful/g4h_stateless/g4n_stateful  gemini-4 lanes (quota-gated)

Usage: harness.py <out.json> [lane,lane,...]   (ONLY_TASKS env filters tasks)
Key from env GEMINI_API_KEY_MICHAEL only; value never printed.
"""
import json, os, sys, time, math, traceback

from google import genai
from google.genai import types as gtypes

API_VERSION = "v1beta"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/gemini-eval/results.json"
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
ONLY_TASKS = set(os.environ.get("ONLY_TASKS", "").split(",")) if os.environ.get("ONLY_TASKS") else None

client = genai.Client(api_key=os.environ["GEMINI_API_KEY_MICHAEL"])

# ---------------- fake tools ----------------

def t_get_weather(a):
    return {"city": a.get("city"), "temp_c": 18, "condition": "sunny", "units": "celsius"}

def t_search_kb(a):
    q = (a.get("query") or "").lower()
    docs = {
        "deploy lock": "deploy-card.sh uses flock /tmp/pfg-deploy.lock; never bypass it",
        "single writer": "only the served checkout on idc03 auto-commits; satellites push via git-safe-push.sh",
        "board api": "card mutations from non-writer hosts go through board-api on idc03",
    }
    for k, v in docs.items():
        if k in q:
            return {"query": a.get("query"), "results": [{"title": k, "snippet": v}]}
    return {"query": a.get("query"), "results": []}

def t_calculator(a):
    expr = str(a.get("expression", "")).replace("^", "**")
    allowed = set("0123456789+-*/().% ")
    if not set(expr) <= allowed:
        return {"error": "invalid expression"}
    try:
        return {"expression": expr, "value": eval(expr, {"__builtins__": {}}, {})}
    except Exception as e:
        return {"error": str(e)}

def t_get_stock(a):
    prices = {"AAPL": 232.5, "MSFT": 428.1, "GOOGL": 178.9, "TSLA": 342.0}
    s = (a.get("symbol") or "").upper()
    if s in prices:
        return {"symbol": s, "price_usd": prices[s], "change_pct": 1.2}
    return {"error": f"unknown symbol {s}"}

def t_create_reminder(a):
    return {"status": "created", "text": a.get("text"), "time": a.get("time")}

def t_get_time(a):
    return {"timezone": a.get("timezone"), "local_time": "14:32", "date": "2026-11-26"}

TOOL_IMPL = {
    "get_weather": t_get_weather,
    "search_kb": t_search_kb,
    "calculator": t_calculator,
    "get_stock": t_get_stock,
    "create_reminder": t_create_reminder,
    "get_time": t_get_time,
}

TOOLS_JSON = [
    {"type": "function", "name": "get_weather",
     "description": "Get current weather for a city",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    {"type": "function", "name": "search_kb",
     "description": "Search the Chaba knowledge base for a topic",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"type": "function", "name": "calculator",
     "description": "Evaluate an arithmetic expression",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}},
    {"type": "function", "name": "get_stock",
     "description": "Get the current stock price for a ticker symbol",
     "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"type": "function", "name": "create_reminder",
     "description": "Create a reminder with text and time",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "time": {"type": "string"}}, "required": ["text", "time"]}},
    {"type": "function", "name": "get_time",
     "description": "Get the current local time for a timezone",
     "parameters": {"type": "object", "properties": {"timezone": {"type": "string"}}, "required": ["timezone"]}},
]

SYSTEM = ("You are a concise assistant with access to tools. "
          "Use the tools when they help answer. Keep final answers brief. "
          "When asked to recall earlier facts, answer from the conversation.")

# ---------------- task set (fixed) ----------------

def task(tid, turns):
    return {"id": tid, "turns": turns}

TASKS = [
    task("t1_weather_reminder", [
        {"user": "What's the weather in Paris right now? Also set a reminder to call mom at 17:00.",
         "expect": {"calls": [{"name": "get_weather", "args": {"city": "paris"}},
                              {"name": "create_reminder", "args": {"time": "17:00"}}],
                    "answer_has": ["18", "sunny"]}},
        {"user": "What did you say the weather was, and what time is my reminder?",
         "expect": {"answer_has": ["18", "17:00"]}},
    ]),
    task("t2_kb_calc_recall", [
        {"user": "Search the knowledge base for the deploy lock rule.",
         "expect": {"calls": [{"name": "search_kb", "args": {"query_contains": "deploy lock"}}],
                    "answer_has": []}},
        {"user": "How many minutes are in 2.5 hours? Also, in one sentence, what does the doc say about the deploy lock?",
         "expect": {"calls": [{"name": "calculator"}],
                    "answer_has": ["150", "flock", "deploy"]}},
    ]),
    task("t3_stock_compare", [
        {"user": "Get the stock price of AAPL.",
         "expect": {"calls": [{"name": "get_stock", "args": {"symbol": "aapl"}}]}},
        {"user": "Now get MSFT too.",
         "expect": {"calls": [{"name": "get_stock", "args": {"symbol": "msft"}}]}},
        {"user": "Which is more expensive, and by how much per share?",
         "expect": {"answer_has": ["msft", "195"]}},
    ]),
    task("t4_time_calc_chain", [
        {"user": "What time is it in Tokyo right now?",
         "expect": {"calls": [{"name": "get_time", "args": {"timezone_contains": "tokyo"}}],
                    "answer_has": ["14:32"]}},
        {"user": "If a meeting starts 90 minutes after that Tokyo time, what time does it start? Also what was the original time again?",
         "expect": {"calls": [{"name": "calculator"}],
                    "answer_has": ["16:02", "14:32"]}},
    ]),
    task("t5_two_weather", [
        {"user": "Compare the weather in Berlin and Tokyo — get both.",
         "expect": {"calls": [{"name": "get_weather", "args": {"city_contains": "berlin"}},
                              {"name": "get_weather", "args": {"city_contains": "tokyo"}}],
                    "answer_has": ["sunny"]}},
        {"user": "Which city did I ask about first?",
         "expect": {"answer_has": ["berlin"]}},
    ]),
    task("t6_fact_recall", [
        {"user": "Remember these facts: project codename is Nighthawk, budget is 4200 USD, deadline is Friday.",
         "expect": {}},
        {"user": "What is my project codename and budget?",
         "expect": {"answer_has": ["nighthawk", "4200"]}},
        {"user": "And the deadline?",
         "expect": {"answer_has": ["friday"]}},
    ]),
    task("t7_calc_then_recall", [
        {"user": "What is 17% of 340?",
         "expect": {"calls": [{"name": "calculator"}], "answer_has": ["57.8"]}},
        {"user": "Double that number.",
         "expect": {"calls": [{"name": "calculator"}], "answer_has": ["115.6"]}},
    ]),
    task("t8_thai_recall", [
        {"user": "My wifi password hint is 'two cats and a blue door'. Search the KB for 'board api' too.",
         "expect": {"calls": [{"name": "search_kb", "args": {"query_contains": "board api"}}]}},
        {"user": "สวัสดี — what was my wifi password hint again?",
         "expect": {"answer_has": ["two cats", "blue door"]}},
    ]),
]

# ---------------- helpers ----------------

def norm(s):
    return str(s).lower()

def args_match(got, want):
    got_n = {k: norm(v) for k, v in (got or {}).items()}
    for k, v in want.items():
        real = k[:-9] if k.endswith("_contains") else k
        if real not in got_n or norm(v) not in got_n[real]:
            return False
    return True

def extract_text(resp):
    """Best-effort final text from an Interaction."""
    ot = getattr(resp, "output_text", None)
    if ot:
        return ot
    texts = []
    for s in getattr(resp, "steps", None) or []:
        if getattr(s, "type", None) == "model_output":
            for c in getattr(s, "content", None) or []:
                t = getattr(c, "text", None)
                if t:
                    texts.append(t)
    return "\n".join(texts)

def func_calls(resp):
    out = []
    for s in getattr(resp, "steps", None) or []:
        if getattr(s, "type", None) == "function_call":
            out.append({"id": getattr(s, "id", ""), "name": getattr(s, "name", ""),
                        "arguments": getattr(s, "arguments", {}) or {}})
    return out

def serialize_steps(resp):
    """Rebuild resendable step dicts from a response, preserving thought
    signatures (required by Gemini 3 function-call replay)."""
    steps = []
    for s in getattr(resp, "steps", None) or []:
        try:
            d = s.model_dump(by_alias=True, exclude_none=True, mode="json")
        except Exception:
            continue
        if isinstance(d, dict) and d.get("type"):
            steps.append(d)
    return steps

def usage_of(resp):
    u = getattr(resp, "usage", None)
    if u is None:
        return {}
    def g(n):
        v = getattr(u, n, None)
        return v if isinstance(v, int) else 0
    return {"input": g("total_input_tokens"), "output": g("total_output_tokens"),
            "thought": g("total_thought_tokens"), "total": g("total_tokens")}

def call_with_retry(fn, tries=3, base=15):
    last = None
    for i in range(tries):
        try:
            return fn(), None
        except Exception as e:
            last = e
            s = str(e)
            fatal = ("limit: 0" in s or "per day" in s and "429" in s or "not found" in s.lower()
                     or "404" in s and "not found" in s.lower())
            if fatal or i == tries - 1:
                return None, e
            time.sleep(base * (i + 1))
    return None, last

# ---------------- lanes ----------------

def run_interaction_turn(model, mode, sys_inst, user_text, conv, prev_id, calls_log, lane):
    """Run one user turn through the Interactions API tool loop.
    mode: 'stateful' (prev_id) or 'stateless' (full history in conv).
    Returns (answer_text, new_prev_id). Mutates calls_log."""
    user_step = {"type": "user_input", "content": [{"type": "text", "text": user_text}]}
    pending = [user_step]
    answer = ""
    for _ in range(6):  # tool-loop cap
        if mode == "stateful":
            inp = pending
            kw = {"previous_interaction_id": prev_id} if prev_id else {}
        else:
            inp = conv + pending
            kw = {}
        t0 = time.time()
        resp, err = call_with_retry(lambda: client.interactions.create(
            model=model, input=inp, tools=TOOLS_JSON, system_instruction=sys_inst,
            api_version=API_VERSION, timeout=120, **kw))
        lat = time.time() - t0
        rec = {"lane": lane, "model": model, "mode": mode, "latency_s": round(lat, 2),
               "input_steps": len(inp) if isinstance(inp, list) else 1}
        if err:
            rec["error"] = f"{type(err).__name__}: {str(err)[:300]}"
            calls_log.append(rec)
            return "", prev_id, True
        rec["status"] = str(getattr(resp, "status", ""))
        rec["usage"] = usage_of(resp)
        rec["interaction_id"] = getattr(resp, "id", None)
        calls_log.append(rec)
        prev_id = getattr(resp, "id", prev_id)
        if mode == "stateless":
            conv.extend(pending)
            conv.extend(serialize_steps(resp))
            pending = []
        fcs = func_calls(resp)
        if fcs:
            results = []
            for fc in fcs:
                impl = TOOL_IMPL.get(fc["name"])
                try:
                    res = impl(fc["arguments"]) if impl else {"error": "unknown tool"}
                except Exception as e:
                    res = {"error": str(e)}
                results.append({"type": "function_result", "call_id": fc["id"],
                                "name": fc["name"], "result": json.dumps(res)})
                rec.setdefault("tool_calls", []).append(
                    {"name": fc["name"], "arguments": fc["arguments"], "result": res})
            pending = results
            continue
        # no function calls -> final answer
        answer = extract_text(resp)
        return answer, prev_id, False
    return answer, prev_id, False

def run_gen_turn(model, sys_inst, user_text, contents, calls_log, lane):
    """Classic generateContent lane (current 3.x stateless path)."""
    contents.append(gtypes.Content(role="user", parts=[gtypes.Part.from_text(text=user_text)]))
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=model, contents=contents,
            config=gtypes.GenerateContentConfig(
                system_instruction=sys_inst,
                tools=[gtypes.Tool(function_declarations=[
                    gtypes.FunctionDeclaration(**{k: v for k, v in t.items() if k != "type"})
                    for t in TOOLS_JSON])]))
    except Exception as e:
        calls_log.append({"lane": lane, "model": model, "mode": "generateContent",
                          "latency_s": round(time.time() - t0, 2),
                          "error": f"{type(e).__name__}: {str(e)[:300]}"})
        return "", True
    lat = time.time() - t0
    cand = resp.candidates[0] if resp.candidates else None
    parts = cand.content.parts if cand and cand.content else []
    answer_parts, fr_parts, calls = [], [], []
    for p in parts:
        if p.function_call:
            fc = p.function_call
            impl = TOOL_IMPL.get(fc.name)
            try:
                res = impl(dict(fc.args or {})) if impl else {"error": "unknown tool"}
            except Exception as e:
                res = {"error": str(e)}
            calls.append({"name": fc.name, "arguments": dict(fc.args or {}), "result": res})
            fr_parts.append(gtypes.Part.from_function_response(
                name=fc.name, response=res))
        elif p.text:
            answer_parts.append(p.text)
    um = getattr(resp, "usage_metadata", None)
    calls_log.append({"lane": lane, "model": model, "mode": "generateContent",
                      "latency_s": round(lat, 2),
                      "usage": {"input": getattr(um, "prompt_token_count", 0) or 0,
                                "output": getattr(um, "candidates_token_count", 0) or 0,
                                "thought": getattr(um, "thoughts_token_count", 0) or 0,
                                "total": getattr(um, "total_token_count", 0) or 0},
                      "tool_calls": calls or None})
    # append model content then tool responses, loop if calls
    if calls:
        contents.append(gtypes.Content(role="model", parts=parts))
        contents.append(gtypes.Content(role="user", parts=fr_parts))
        # recurse once more for the follow-up answer (cap 4 rounds)
        return run_gen_turn(model, sys_inst, "", contents, calls_log, lane) if False else _gen_continue(model, sys_inst, contents, calls_log, lane)
    answer = "".join(answer_parts)
    contents.append(gtypes.Content(role="model", parts=[gtypes.Part.from_text(text=answer)]))
    return answer, False

def _gen_continue(model, sys_inst, contents, calls_log, lane, depth=0):
    if depth > 4:
        return "", True
    t0 = time.time()
    try:
        resp = client.models.generate_content(
            model=model, contents=contents,
            config=gtypes.GenerateContentConfig(
                system_instruction=sys_inst,
                tools=[gtypes.Tool(function_declarations=[
                    gtypes.FunctionDeclaration(**{k: v for k, v in t.items() if k != "type"})
                    for t in TOOLS_JSON])]))
    except Exception as e:
        calls_log.append({"lane": lane, "model": model, "mode": "generateContent",
                          "latency_s": round(time.time() - t0, 2),
                          "error": f"{type(e).__name__}: {str(e)[:300]}"})
        return "", True
    lat = time.time() - t0
    cand = resp.candidates[0] if resp.candidates else None
    parts = cand.content.parts if cand and cand.content else []
    answer_parts, fr_parts, calls = [], [], []
    for p in parts:
        if p.function_call:
            fc = p.function_call
            impl = TOOL_IMPL.get(fc.name)
            try:
                res = impl(dict(fc.args or {})) if impl else {"error": "unknown tool"}
            except Exception as e:
                res = {"error": str(e)}
            calls.append({"name": fc.name, "arguments": dict(fc.args or {}), "result": res})
            fr_parts.append(gtypes.Part.from_function_response(name=fc.name, response=res))
        elif p.text:
            answer_parts.append(p.text)
    um = getattr(resp, "usage_metadata", None)
    calls_log.append({"lane": lane, "model": model, "mode": "generateContent",
                      "latency_s": round(lat, 2),
                      "usage": {"input": getattr(um, "prompt_token_count", 0) or 0,
                                "output": getattr(um, "candidates_token_count", 0) or 0,
                                "thought": getattr(um, "thoughts_token_count", 0) or 0,
                                "total": getattr(um, "total_token_count", 0) or 0},
                      "tool_calls": calls or None})
    if calls:
        contents.append(gtypes.Content(role="model", parts=parts))
        contents.append(gtypes.Content(role="user", parts=fr_parts))
        return _gen_continue(model, sys_inst, contents, calls_log, lane, depth + 1)
    answer = "".join(answer_parts)
    contents.append(gtypes.Content(role="model", parts=[gtypes.Part.from_text(text=answer)]))
    return answer, False

# ---------------- grading ----------------

def grade_task(task, lane_answers, lane_calls):
    """lane_answers: {turn_idx: answer_text}; lane_calls: flat call log for lane."""
    checks = []
    call_seq = []
    for c in lane_calls:
        for tc in c.get("tool_calls") or []:
            call_seq.append(tc)
    ci = 0
    for ti, turn in enumerate(task["turns"]):
        exp = turn.get("expect") or {}
        ans = norm(lane_answers.get(ti, ""))
        for want in exp.get("calls", []):
            # find a matching call in order
            found = None
            for j in range(ci, len(call_seq)):
                tc = call_seq[j]
                if tc["name"] == want["name"] and args_match(tc.get("arguments"), want.get("args", {})):
                    found = j
                    break
            if found is None:
                checks.append({"turn": ti, "check": f"call:{want['name']}", "pass": False})
            else:
                ci = found + 1
                checks.append({"turn": ti, "check": f"call:{want['name']}:{json.dumps(want.get('args', {}), sort_keys=True)}", "pass": True})
        for tok in exp.get("answer_has", []):
            checks.append({"turn": ti, "check": f"answer_has:{tok}", "pass": norm(tok) in ans})
        for tok in exp.get("answer_lacks", []):
            checks.append({"turn": ti, "check": f"answer_lacks:{tok}", "pass": norm(tok) not in ans})
    npass = sum(1 for c in checks if c["pass"])
    return {"checks": checks, "score": round(npass / len(checks), 3) if checks else None,
            "n_checks": len(checks)}

# ---------------- runner ----------------

def run_all():
    all_results = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "key_var": "GEMINI_API_KEY_MICHAEL", "api_version": API_VERSION,
                   "sdk": "google-genai", "lanes": {}, "calls": []}
    lanes = [
        ("g35l_stateful", "gemini-3.5-flash-lite", "stateful"),
        ("g31l_stateful", "gemini-3.1-flash-lite", "stateful"),
        ("g35l_int", "gemini-3.5-flash-lite", "stateless"),
        ("g31l_int", "gemini-3.1-flash-lite", "stateless"),
        ("g35l_gen", "gemini-3.5-flash-lite", "generateContent"),
        ("g4h_stateful", "gemini-4-hydrogen", "stateful"),
        ("g4h_stateless", "gemini-4-hydrogen", "stateless"),
        ("g4n_stateful", "gemini-4-neon", "stateful"),
    ]
    for lane, model, mode in lanes:
        if ONLY and lane not in ONLY:
            continue
        print(f"=== lane {lane} model={model} mode={mode} ===", flush=True)
        # fresh per-task grading: run tasks one at a time, tagging calls
        lane_res = {"model": model, "mode": mode, "tasks": {}, "call_log": [],
                    "consecutive_fatal": 0, "blocked": False}
        for task in TASKS:
            if ONLY_TASKS and task["id"] not in ONLY_TASKS:
                continue
            if lane_res["blocked"]:
                lane_res["tasks"][task["id"]] = {"skipped": "lane blocked"}
                continue
            t0 = time.time()
            task_calls = []
            if mode == "generateContent":
                contents = []
                answers, fatal = {}, False
                for ti, turn in enumerate(task["turns"]):
                    ans, err = run_gen_turn(model, SYSTEM, turn["user"], contents, task_calls, lane)
                    answers[ti] = ans
                    if err:
                        fatal = True
                        break
            else:
                conv, prev_id, answers, fatal = [], None, {}, False
                for ti, turn in enumerate(task["turns"]):
                    ans, prev_id, err = run_interaction_turn(
                        model, mode, SYSTEM, turn["user"], conv, prev_id, task_calls, lane)
                    answers[ti] = ans
                    if err:
                        fatal = True
                        break
            g = grade_task(task, answers, task_calls)
            lane_res["tasks"][task["id"]] = {
                "answers": answers, "fatal": fatal, "wall_s": round(time.time() - t0, 1),
                "score": g["score"], "n_checks": g["n_checks"],
                "checks": g["checks"], "calls": task_calls}
            lane_res["call_log"].extend(task_calls)
            lane_res["consecutive_fatal"] = lane_res["consecutive_fatal"] + 1 if fatal else 0
            if lane_res["consecutive_fatal"] >= 2:
                lane_res["blocked"] = True
            print(f"  {task['id']}: score={g['score']} fatal={fatal} wall={time.time()-t0:.0f}s", flush=True)
        all_results["lanes"][lane] = lane_res
        # checkpoint after each lane
        with open(OUT, "w") as f:
            json.dump(all_results, f, indent=1, default=str)
    all_results["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(OUT, "w") as f:
        json.dump(all_results, f, indent=1, default=str)
    print("DONE ->", OUT, flush=True)

if __name__ == "__main__":
    run_all()
