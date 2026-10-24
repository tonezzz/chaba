#!/usr/bin/env python3
"""decision-arena — benchmark decision models on OUR corpus (BEN-0826).

Corpus: jev-bench confirm-gate (noul) + tool-routing (choice),
doc-pilot pipeline-compat edges (noul), stagnation cases (noul).
Backends: jev-student (idc03:8778), jevos (CPU binary, :8017),
Laya (pip, local). Same wire shape /v1/systemone.

Metrics: accuracy overall + per type, latency p50, cost estimate.
"""
import json, os, statistics, subprocess, sys, time, urllib.request

STUDENT = "http://100.102.134.91:8778"
JEVOS = "http://127.0.0.1:8017"
LAYA_URL = "http://127.0.0.1:8021"

def ask(base, state, questions, timeout=120):
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    req = urllib.request.Request(base + "/v1/systemone",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return r.get("answers", {}), round((time.time() - t0) * 1000)
    except Exception as e:
        return {"_err": str(e)[:80]}, round((time.time() - t0) * 1000)

def parse(ans, qtype):
    if not isinstance(ans, dict):
        return None
    if qtype == "noul":
        p = ans.get("noul")
        return "true" if isinstance(p, (int, float)) and p >= 0.5 else "false"
    if qtype == "choice":
        return ans.get("choice")
    if qtype == "score":
        return ans.get("score")
    return None

# --- corpus ---------------------------------------------------------
CONFIRM = [
    ("yes, publish it", True), ("Yes", True), ("go ahead", True),
    ("ยืนยันครับ", True), ("ใช่ ทำเลย", True),
    ("remember that the lab stack design is approved", False),
    ("turn off the TV ok", False), ("what is the weather today", False),
    ("save this to memory please", False),
    ("confirm delete the old page", False),
]
N_CONFIRM = {"type": "noul",
    "instructions": "Did the user explicitly affirm or confirm? The turn counts as affirmation only when it is a standalone short affirmation or begins with one. An approval word embedded inside a longer request does NOT count.",
    "criteria": {"true": "the whole turn is a short affirmation, or it leads with one",
                 "false": "no affirmation present, or an affirmative word is buried inside a longer request"}}
TOOL = [
    ("remember that the washing machine repairman comes Friday", "remember"),
    ("what did we decide about the idc02 server yesterday?", "recall"),
    ("turn off the living room TV", "control"),
    ("how do you say thank you in Thai?", "answer"),
    ("is the flood warning still active for Bangkok?", "search"),
    ("play the pool camera on screen one", "control"),
    ("save to memory: wifi password is on the fridge", "remember"),
    ("what time did I go to bed last night?", "recall"),
]
N_TOOL = {"type": "choice",
    "instructions": "Choose the action Ada should take first.",
    "criteria": {"remember": "store the information in long-term memory",
                 "recall": "search memory / past sessions to answer",
                 "control": "act on a smart-home device (switch, scene, media)",
                 "answer": "no tool needed - just speak the answer",
                 "search": "search the web for current information"}}
PIPE = [("doc-embeds-ss1", "doc-render-ss1"), ("doc-render-ss1", "doc-vo-ss1"),
        ("doc-vo-ss1", "doc-assemble-ss1"), ("doc-embeds-ss1", "doc-assemble-ss1")]
N_PIPE = {"type": "noul",
    "instructions": "Block A produces the output that block B consumes as input - is this edge valid in a render pipeline?",
    "criteria": {"true": "B consumes what A produces (valid dependency)",
                 "false": "the outputs/inputs do not match (invalid edge)"}}
STAG = [
    ("agent loop: same tool call 'search' 14 times, same args, no new output", True),
    ("agent loop: alternating read/search/read with growing context and new files found", False),
    ("bench run: identical progress bar at 0% for 4 hours, no new artifacts", True),
    ("agent: 5 distinct actions, each completed with a logged result", False),
    ("agent: retrying 'ollama pull' 9 times after identical 500 errors", True),
]
N_STAG = {"type": "noul",
    "instructions": "Is this agent trajectory semantically stagnant (no real progress, repeating the same action/outcome)?",
    "criteria": {"true": "stagnant - repeated identical actions with no progress",
                 "false": "progressing - distinct actions and new results"}}

def build_corpus():
    out = []
    for turn, exp in CONFIRM:
        out.append({"id": "confirm-%s" % turn[:12], "state": turn,
                    "questions": {"q": N_CONFIRM}, "qtype": "noul",
                    "expected": "true" if exp else "false"})
    for turn, exp in TOOL:
        out.append({"id": "tool-%s" % turn[:12], "state": turn,
                    "questions": {"q": N_TOOL}, "qtype": "choice", "expected": exp})
    for a, b in PIPE:
        out.append({"id": "pipe-%s-%s" % (a[:8], b[:8]),
                    "state": "Block A: %s. Block B: %s." % (a, b),
                    "questions": {"q": N_PIPE}, "qtype": "noul", "expected": "true"})
    for i, (s, exp) in enumerate(STAG):
        out.append({"id": "stag-%d" % i, "state": s,
                    "questions": {"q": N_STAG}, "qtype": "noul",
                    "expected": "true" if exp else "false"})
    return out

def run_backend(name, base, corpus):
    lat, correct, total = [], 0, 0
    per = {}
    for case in corpus:
        answers, ms = ask(base, case["state"], case["questions"])
        lat.append(ms)
        got = parse(answers.get("q"), case["qtype"])
        exp = case["expected"]
        ok = got == exp
        correct += 1 if ok else 0
        total += 1
        per.setdefault(case["qtype"], [0, 0])
        per[case["qtype"]][1] += 1
        per[case["qtype"]][0] += 1 if ok else 0
    acc = correct / total if total else 0
    return {"backend": name, "accuracy": round(acc, 3),
            "correct": correct, "total": total,
            "per_type": {k: round(v[0] / v[1], 3) if v[1] else 0
                         for k, v in per.items()},
            "lat_p50_ms": round(statistics.median(lat), 1) if lat else 0}

def ask_laya(state, questions, timeout=180):
    import laya
    agent = laya.load("convaiinnovations/laya")
    t0 = time.time()
    try:
        r = agent.system_one(state, questions)
        return r.get("answers", {}), round((time.time() - t0) * 1000)
    except Exception as e:
        return {"_err": str(e)[:80]}, round((time.time() - t0) * 1000)


def run_laya(corpus):
    lat, correct, total, per = [], 0, 0, {}
    for case in corpus:
        answers, ms = ask_laya(case["state"], case["questions"])
        lat.append(ms)
        got = parse(answers.get("q"), case["qtype"])
        ok = got == case["expected"]
        correct += 1 if ok else 0
        total += 1
        per.setdefault(case["qtype"], [0, 0])
        per[case["qtype"]][1] += 1
        per[case["qtype"]][0] += 1 if ok else 0
    return {"backend": "laya", "accuracy": round(correct / total, 3) if total else 0,
            "correct": correct, "total": total,
            "per_type": {k: round(v[0] / v[1], 3) if v[1] else 0 for k, v in per.items()},
            "lat_p50_ms": round(statistics.median(lat), 1) if lat else 0}


def main():
    corpus = build_corpus()
    backends = []
    # jev-student
    try:
        a, _ = ask(STUDENT, "ping", {"q": {"type": "noul", "instructions": "ping"}})
        backends.append(run_backend("jev-student", STUDENT, corpus))
    except Exception as e:
        print("student down:", e)
    # jevos
    try:
        a, _ = ask(JEVOS, "ping", {"q": {"type": "noul", "instructions": "ping"}})
        backends.append(run_backend("jevos", JEVOS, corpus))
    except Exception as e:
        print("jevos down:", e)
    # laya (in-process)
    try:
        backends.append(run_laya(corpus))
    except Exception as e:
        print("laya down:", e)

    print("\n== decision-arena ==")
    print("%-12s %8s %6s %8s %8s %8s %10s" % ("backend", "acc", "noul", "choice", "n", "lat_p50", "correct"))
    for b in backends:
        pt = b["per_type"]
        print("%-12s %8.3f %6s %8s %8d %8.1f %8d/%d" % (
            b["backend"], b["accuracy"], pt.get("noul", "-"),
            pt.get("choice", "-"), b["total"], b["lat_p50_ms"],
            b["correct"], b["total"]))
    out = os.path.expanduser("~/.cache/decision-arena.json")
    json.dump(backends, open(out, "w"), indent=1)
    print("wrote", out)

if __name__ == "__main__":
    main()