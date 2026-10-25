#!/usr/bin/env python3
"""decision-arena — benchmark decision models on OUR corpus (BEN-0826).

Corpus: jev-bench confirm-gate (noul) + tool-routing (choice),
doc-pilot pipeline-compat edges (noul), stagnation cases (noul).
Backends: jev-student (idc03:8778), jevos (CPU binary, :8017),
Laya (pip, local). Same wire shape /v1/systemone.

Metrics: accuracy overall + per type, latency p50, cost estimate.

Flags:
  --corpus-only   validate + describe the labeled corpus, no backend
                  calls (the corpus verifier — exits nonzero on malformed
                  corpus: duplicate ids, out-of-criteria labels, class
                  imbalance beyond a single-class type).
  --out PATH      also write per-case records {id,qtype,expected,got,ms}
                  per backend for disagreement analysis.
Env: JEV_STUDENT_URL / JEVOS_URL / LAYA_URL override backend bases.
"""
import json, os, statistics, subprocess, sys, time, urllib.request

STUDENT = os.environ.get("JEV_STUDENT_URL", "http://100.102.134.91:8778")
JEVOS = os.environ.get("JEVOS_URL", "http://127.0.0.1:8017")
LAYA_URL = os.environ.get("LAYA_URL", "http://127.0.0.1:8021")

CORPUS_VERSION = 2  # v1 = 27 cases; v2 = 50 labeled cases (2026-10-25)

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
# Label conventions per question spec below. Keep classes balanced —
# a single-class type measures nothing.
CONFIRM = [
    ("yes, publish it", True), ("go ahead", True),
    ("ยืนยันครับ", True), ("ใช่ ทำเลย", True),
    ("ok, but only the staging page", True),
    ("sure — and also update the footer", True),
    ("remember that the lab stack design is approved", False),
    ("turn off the TV ok", False), ("what is the weather today", False),
    ("confirm delete the old page", False),
    ("no wait, don't publish yet", False),
    ("can you confirm the deploy finished?", False),
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
    ("dim the bedroom lights to thirty percent", "control"),
    ("what's the latest on the Chiang Mai flood?", "search"),
    ("what did I name the new kanban column?", "recall"),
    ("note down that Kaewta's flight lands Sunday", "remember"),
    ("put the kitchen camera up on the TV", "control"),
    ("jot this down: the gate remote battery is dying", "remember"),
    ("when did we last restart the frigate container?", "recall"),
    ("is it going to rain in Chiang Mai tomorrow?", "search"),
]
N_TOOL = {"type": "choice",
    "instructions": "Choose the action Ada should take first.",
    "criteria": {"remember": "store the information in long-term memory",
                 "recall": "search memory / past sessions to answer",
                 "control": "act on a smart-home device (switch, scene, media)",
                 "answer": "no tool needed - just speak the answer",
                 "search": "search the web for current information"}}
# doc-pilot chain: doc-embeds-ss1 -> doc-render-ss1 -> doc-vo-ss1 ->
# doc-assemble-ss1 (plus embeds -> assemble skip-edge). Every other
# ordered pair over these blocks is an invalid edge — the v1 corpus had
# only valid edges, a single-class type that measured nothing.
PIPE = [("doc-embeds-ss1", "doc-render-ss1", True),
        ("doc-render-ss1", "doc-vo-ss1", True),
        ("doc-vo-ss1", "doc-assemble-ss1", True),
        ("doc-embeds-ss1", "doc-assemble-ss1", True),
        ("doc-render-ss1", "doc-embeds-ss1", False),
        ("doc-vo-ss1", "doc-embeds-ss1", False),
        ("doc-vo-ss1", "doc-render-ss1", False),
        ("doc-assemble-ss1", "doc-embeds-ss1", False),
        ("doc-assemble-ss1", "doc-render-ss1", False),
        ("doc-assemble-ss1", "doc-vo-ss1", False)]
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
    ("agent: re-ran the same failing pytest 6 times with no code changes between runs", True),
    ("agent: read 12 different source files, no writes yet — still exploring", False),
    ("bench: token usage grows each loop, output file unchanged for 9 iterations", True),
    ("agent: alternating between two failing commands, each error identical", True),
    ("agent: writes progress notes every loop but no artifacts and no new information", True),
    ("agent: 4 attempts at different solutions, each documented with a different failure", False),
    ("agent loop: 3 identical 'git status' calls then 2 new file edits and a commit", False),
]
N_STAG = {"type": "noul",
    "instructions": "Is this agent trajectory semantically stagnant (no real progress, repeating the same action/outcome)?",
    "criteria": {"true": "stagnant - repeated identical actions with no progress",
                 "false": "progressing - distinct actions and new results"}}

def build_corpus():
    out = []
    for i, (turn, exp) in enumerate(CONFIRM):
        out.append({"id": "confirm-%02d" % i, "state": turn,
                    "questions": {"q": N_CONFIRM}, "qtype": "noul",
                    "expected": "true" if exp else "false"})
    for i, (turn, exp) in enumerate(TOOL):
        out.append({"id": "tool-%02d" % i, "state": turn,
                    "questions": {"q": N_TOOL}, "qtype": "choice",
                    "expected": exp})
    for i, (a, b, exp) in enumerate(PIPE):
        out.append({"id": "pipe-%02d" % i,
                    "state": "Block A: %s. Block B: %s." % (a, b),
                    "questions": {"q": N_PIPE}, "qtype": "noul",
                    "expected": "true" if exp else "false"})
    for i, (s, exp) in enumerate(STAG):
        out.append({"id": "stag-%02d" % i, "state": s,
                    "questions": {"q": N_STAG}, "qtype": "noul",
                    "expected": "true" if exp else "false"})
    return out


def corpus_report(corpus):
    """Validation + label stats — the --corpus-only verifier."""
    errs, types, labels = [], {}, {}
    ids = [c["id"] for c in corpus]
    if len(ids) != len(set(ids)):
        errs.append("duplicate case ids")
    for c in corpus:
        q = c["questions"]["q"]
        types[c["id"].split("-")[0]] = types.get(c["id"].split("-")[0], 0) + 1
        labels.setdefault(q["type"], {})
        labels[q["type"]][c["expected"]] = \
            labels[q["type"]].get(c["expected"], 0) + 1
        if c["expected"] not in q["criteria"]:
            errs.append("%s: expected %r not in criteria %s"
                        % (c["id"], c["expected"], sorted(q["criteria"])))
        if not c["state"].strip():
            errs.append("%s: empty state" % c["id"])
    # a type whose labels are all one class discriminates nothing
    for qt, lab in labels.items():
        if len(lab) < 2:
            errs.append("qtype %s is single-class %s" % (qt, lab))
    return {"corpus_version": CORPUS_VERSION, "total": len(corpus),
            "families": types, "labels": labels, "errors": errs}


def run_backend(name, base, corpus, records=None):
    lat, correct, total = [], 0, 0
    per = {}
    for case in corpus:
        answers, ms = ask(base, case["state"], case["questions"])
        lat.append(ms)
        got = parse(answers.get("q"), case["qtype"])
        exp = case["expected"]
        ok = got == exp
        if records is not None:
            records.append({"backend": name, "id": case["id"],
                            "qtype": case["qtype"], "expected": exp,
                            "got": got, "ok": ok, "ms": ms,
                            "err": answers.get("_err")})
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

def ask_laya(agent, state, questions, timeout=180):
    t0 = time.time()
    try:
        r = agent.system_one(state, questions)
        return r.get("answers", {}), round((time.time() - t0) * 1000)
    except Exception as e:
        return {"_err": str(e)[:80]}, round((time.time() - t0) * 1000)


def run_laya(corpus):
    import laya
    agent = laya.load("convaiinnovations/laya")
    lat, correct, total, per = [], 0, 0, {}
    for case in corpus:
        answers, ms = ask_laya(agent, case["state"], case["questions"])
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
    if "--corpus-only" in sys.argv:
        rep = corpus_report(corpus)
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 1 if rep["errors"] else 0
    out_path = None
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        out_path = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    records = []
    backends = []
    ping_q = {"q": {"type": "noul", "instructions": "ping"}}
    for name, base in (("jev-student", STUDENT), ("jevos", JEVOS)):
        # ask() returns _err instead of raising — a backend that can't
        # answer the ping must be skipped, not run for 50 slow timeouts.
        a, _ = ask(base, "ping", ping_q, timeout=15)
        if "_err" in a:
            print(f"{name} down:", a["_err"])
            continue
        backends.append(run_backend(name, base, corpus, records))
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
    if out_path:
        json.dump(records, open(out_path, "w"), indent=1)
        print("wrote per-case records:", out_path)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
