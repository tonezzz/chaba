#!/usr/bin/env python3
"""code-decision — Jev decision door for code changes (OPS-0825).

Answers one question shape for an agent about to apply a code change:

    state = {task, code, constraints[], candidates{name: construct/template/library}}
    questions = Choice(which candidate) + Noul(semantics preserved,
                convention match, minimality)  — the three gates, scoped
                to the winning candidate in a second call.

Wire shape is /v1/systemone (same as decision-arena.py / jev-student /
the real Jev API at api.typesafe.ai).

Backend routing (first healthy wins, per question type):
  choice:  $JEV_API_URL+$JEV_API_KEY (real Jev) -> $JEVOS_URL -> student
           (student's choice head is a stub — detected via confidence==0
           and reported as degraded, never silently trusted)
  noul:    $JEV_API_URL+$JEV_API_KEY -> $JEV_STUDENT_URL -> $JEVOS_URL

Honest degradation is a feature: the response always names which backend
answered each question type and lists `degraded` reasons. A stub choice
is reported, not hidden — the caller (agent skill) falls back to its own
judgment and records the verdict for the eval pack.

Usage:
  code-decision.py --task "..." --code-file f.py \
      --candidates candidates.json [--constraints a,b]
  echo '{"task":..., "code":..., "candidates":{...}}' | code-decision.py
  code-decision.py --serve --port 8890        # stdlib HTTP door
  code-decision.py --selftest                  # payload build, no backends
"""
import argparse, json, os, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- backend endpoints -------------------------------------------------
JEV_API_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai")
JEV_API_KEY = os.environ.get("JEV_API_KEY", "")
JEVOS_URL = os.environ.get("JEVOS_URL", "http://127.0.0.1:8017")
STUDENT_URL = os.environ.get("JEV_STUDENT_URL", "http://100.75.102.88:8780")
NOUL_THR = float(os.environ.get("JEV_NOUL_THR", "0.5"))
TIMEOUT = float(os.environ.get("JEV_TIMEOUT_S", "60"))

CHOICE_Q = "construct"
GATE_QS = ("semantics", "convention", "minimality")


def _post(base, state, questions, timeout=TIMEOUT, api_key=""):
    """POST {model,state,questions} to <base>/v1/systemone -> (answers, ms, err)."""
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(base.rstrip("/") + "/v1/systemone",
                                 data=json.dumps(payload).encode(),
                                 headers=headers)
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return r.get("answers", {}), round((time.time() - t0) * 1000), None
    except Exception as e:
        return {}, round((time.time() - t0) * 1000), str(e)[:160]


def _healthy(base, timeout=8):
    try:
        urllib.request.urlopen(base.rstrip("/") + "/health", timeout=timeout)
        return True
    except Exception:
        return False


# --- question builders --------------------------------------------------
def _state(ctx, extra=None):
    s = {"task": ctx["task"], "code": ctx["code"],
         "constraints": ctx.get("constraints") or []}
    if extra:
        s.update(extra)
    return s


def build_choice_question(candidates):
    """Choice over candidate names; criteria carry the caller's rubric."""
    criteria = {name: (desc if isinstance(desc, str) else json.dumps(desc))
                for name, desc in candidates.items()}
    return {"type": "choice",
            "instructions": "Which candidate construct/template/library best "
                            "satisfies the task under the stated constraints? "
                            "Pick exactly one candidate key.",
            "criteria": criteria}


def build_gate_questions(ctx, winner):
    """The three Noul gates, scoped to the winning candidate."""
    cand_desc = str(ctx["candidates"][winner])[:800]
    return {
        "semantics": {"type": "noul",
            "instructions": "Task: %s\nOriginal code:\n%s\nChosen candidate "
                            "'%s': %s\n\nDoes the chosen construct preserve "
                            "the original code's observable semantics (same "
                            "result, same side effects, same failure "
                            "behavior)?" % (ctx["task"][:300], ctx["code"][:1500],
                                           winner, cand_desc),
            "criteria": {"true": "semantics preserved",
                         "false": "semantics changed or unclear"}},
        "convention": {"type": "noul",
            "instructions": "Task: %s\nRepo conventions to match: %s\nChosen "
                            "candidate '%s': %s\n\nDoes the chosen construct "
                            "match this repository's established style and "
                            "conventions?" % (ctx["task"][:300],
                                             "; ".join(ctx.get("constraints") or [])[:400] or "(none stated)",
                                             winner, cand_desc),
            "criteria": {"true": "matches repo conventions",
                         "false": "foreign or unconventional for this repo"}},
        "minimality": {"type": "noul",
            "instructions": "Task: %s\nOriginal code:\n%s\nChosen candidate "
                            "'%s': %s\n\nIs the chosen construct the minimal "
                            "change that satisfies the task (no gratuitous "
                            "refactor, no unneeded abstraction)?"
                            % (ctx["task"][:300], ctx["code"][:1500],
                               winner, cand_desc),
            "criteria": {"true": "minimal and sufficient",
                         "false": "over- or under-scoped"}},
    }


def _choice_backends():
    """Ordered (name, base, api_key) for choice-capable backends."""
    out = []
    if JEV_API_KEY:
        out.append(("jev-api", JEV_API_URL, JEV_API_KEY))
    out += [("jevos", JEVOS_URL, ""), ("jev-student", STUDENT_URL, "")]
    return out


def _noul_backends():
    out = []
    if JEV_API_KEY:
        out.append(("jev-api", JEV_API_URL, JEV_API_KEY))
    out += [("jev-student", STUDENT_URL, ""), ("jevos", JEVOS_URL, "")]
    return out


def _is_choice_stub(ans):
    """jev-student/gemma-head return choice='answer', confidence=0.0."""
    return (isinstance(ans, dict) and ans.get("confidence") == 0.0
            and ans.get("choice") == "answer")


def _pick_choice(ctx, candidates):
    """Try choice backends in order; return dict with winner/backend/degraded."""
    degraded = []
    q = {CHOICE_Q: build_choice_question(candidates)}
    state = _state(ctx, {"candidates": {k: str(v)[:500]
                                        for k, v in candidates.items()}})
    last_err = None
    ms_total = 0
    for name, base, key in _choice_backends():
        answers, ms, err = _post(base, state, q, api_key=key)
        ms_total += ms
        if err:
            last_err = "%s: %s" % (name, err)
            continue
        a = answers.get(CHOICE_Q) or {}
        if _is_choice_stub(a):
            degraded.append("%s: choice head is a stub (confidence=0)" % name)
            continue
        choice = a.get("choice")
        if choice in candidates:
            return {"winner": choice, "confidence": a.get("confidence"),
                    "backend": name, "ms": ms_total, "degraded": degraded}
        degraded.append("%s: choice %r not in candidates" % (name, choice))
    return {"winner": None, "confidence": None, "backend": None,
            "ms": ms_total,
            "degraded": degraded + ([last_err] if last_err else [])}


def _pick_nouls(ctx, questions):
    """Try noul backends in order; return (answers, backend, degraded[], ms)."""
    degraded = []
    state = _state(ctx)
    last_err = None
    ms_total = 0
    for name, base, key in _noul_backends():
        answers, ms, err = _post(base, state, questions, api_key=key)
        ms_total += ms
        if err:
            last_err = "%s: %s" % (name, err)
            continue
        if all(isinstance(answers.get(q), dict) and "noul" in answers[q]
               for q in GATE_QS):
            return answers, name, degraded, ms_total
        degraded.append("%s: incomplete noul answers" % name)
    return {}, None, degraded + ([last_err] if last_err else []), ms_total


def decide(task, code, candidates, constraints=None, assume_winner=None):
    """Run the full decision. Returns a verdict dict; never raises on
    backend failure — degradation is data.

    assume_winner: caller's own pick (agent fallback). Used for the noul
    gates when no choice backend answers, so the gates still run in
    degraded mode; verdict is then 'gated-unverified-choice'."""
    if not candidates:
        return {"ok": False, "error": "no candidates", "degraded": []}
    if assume_winner is not None and assume_winner not in candidates:
        return {"ok": False, "error": "assume_winner not in candidates",
                "degraded": []}
    ctx = {"task": task, "code": code, "candidates": candidates,
           "constraints": constraints or []}

    ch = _pick_choice(ctx, candidates)
    degraded = list(ch["degraded"])

    result = {"ok": True, "task": task[:200],
              "candidates": sorted(candidates),
              "choice": {"winner": ch["winner"],
                         "confidence": ch["confidence"],
                         "backend": ch["backend"], "ms": ch["ms"]},
              "gates": {}, "backends": {"choice": ch["backend"]},
              "degraded": degraded, "noul_threshold": NOUL_THR}

    winner = ch["winner"]
    choice_degraded = winner is None
    if choice_degraded:
        if assume_winner is None:
            result["verdict"] = "no-choice-backend"
            result["degraded"].append(
                "no choice-capable backend answered — real Jev API key "
                "(KNB-0822) or a live jevos required for Choice")
            return result
        winner = assume_winner
        result["choice"]["winner"] = winner
        result["choice"]["assumed"] = True
        result["degraded"].append(
            "choice backend unavailable — gates ran on caller's "
            "assume_winner=%r" % winner)

    gqs = build_gate_questions(ctx, winner)
    answers, nb_name, nb_deg, noul_ms = _pick_nouls(ctx, gqs)
    degraded += nb_deg
    result["backends"]["noul"] = nb_name
    result["noul_ms"] = noul_ms

    for q in GATE_QS:
        a = answers.get(q) or {}
        p = a.get("noul")
        result["gates"][q] = {"p": p,
                              "pass": (p >= NOUL_THR)
                              if isinstance(p, (int, float)) else None}

    ps = [g["p"] for g in result["gates"].values()
          if isinstance(g["p"], (int, float))]
    # OOD-collapse detector: jev-student's noul head ignores question text
    # and scores the state only — out-of-domain inputs return the same
    # near-zero p for every gate (observed 2026-11-24: 0.0047 x3 on a
    # comprehension choice). Uniform low p is a backend failure, not a
    # verdict — flag it so callers don't rubber-stamp 're-propose'.
    if len(ps) == len(GATE_QS) and max(ps) - min(ps) < 0.01 and max(ps) < 0.1:
        result["gates"]["_ood_suspect"] = True
        result["degraded"].append(
            "noul answers collapsed (all gates p≈%.4g) — backend likely "
            "out-of-domain; treat gates as unanswered" % max(ps))

    if nb_name is None:
        result["verdict"] = "choice-only"
        result["degraded"].append("no noul backend answered — gates skipped")
    elif result["gates"].get("_ood_suspect"):
        result["verdict"] = "gates-ood-suspect"
    elif not all(g["pass"] for g in result["gates"].values()):
        result["verdict"] = "re-propose"   # a gate failed — agent re-proposes
    elif choice_degraded:
        result["verdict"] = "gated-unverified-choice"
    else:
        result["verdict"] = "accept"
    return result


# --- CLI -----------------------------------------------------------------
def _load_candidates(path):
    if not path:
        return None
    if path == "-":
        return json.load(sys.stdin)
    return json.load(open(os.path.expanduser(path)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Jev code-decision door")
    ap.add_argument("--task")
    ap.add_argument("--code", help="code snippet; or --code-file -")
    ap.add_argument("--code-file")
    ap.add_argument("--candidates",
                    help="JSON file {name: desc/snippet}, '-' = stdin")
    ap.add_argument("--constraints", help="comma-separated constraints")
    ap.add_argument("--assume-winner",
                    help="caller pick used for noul gates when choice is down")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8890)  # 8790 is taken on tony-omen
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        cands = {"for-loop": "for x in items: f(x)",
                 "comprehension": "[f(x) for x in items]",
                 "while": "i=0\nwhile i<len(items): f(items[i]); i+=1"}
        ctx = {"task": "t", "code": "c", "candidates": cands, "constraints": []}
        print(json.dumps(build_choice_question(cands), indent=1))
        print(json.dumps(build_gate_questions(ctx, "comprehension"), indent=1))
        return 0

    if args.serve:
        return _serve(args.host, args.port)

    # stdin JSON mode: {task, code, candidates, constraints?}
    body = None
    if not args.task and not sys.stdin.isatty():
        try:
            body = json.load(sys.stdin)
        except Exception:
            body = None
    if body:
        task = body.get("task", "")
        code = body.get("code", "")
        cands = body.get("candidates") or {}
        cons = body.get("constraints") or []
        assume = body.get("assume_winner")
    else:
        task = args.task or ""
        code = args.code or ""
        if args.code_file:
            code = open(os.path.expanduser(args.code_file)).read()
        cands = _load_candidates(args.candidates) or {}
        cons = [c.strip() for c in (args.constraints or "").split(",")
                if c.strip()]
        assume = args.assume_winner

    if not task:
        ap.error("need --task or JSON {task,...} on stdin")

    out = decide(task, code, cands, cons, assume_winner=assume)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out.get("ok") else 1


def _serve(host, port):
    class H(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"ok": True, "svc": "code-decision",
                                 "student": _healthy(STUDENT_URL),
                                 "jevos": _healthy(JEVOS_URL),
                                 "jev_api": bool(JEV_API_KEY)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path not in ("/decide", "/v1/decide"):
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                out = decide(body.get("task", ""), body.get("code", ""),
                             body.get("candidates") or {},
                             body.get("constraints") or [],
                             assume_winner=body.get("assume_winner"))
                self._json(200, out)
            except Exception as e:
                self._json(400, {"ok": False, "error": str(e)[:200]})

        def log_message(self, *a):
            pass

    print("code-decision serving on http://%s:%d  (POST /decide)"
          % (host, port), file=sys.stderr)
    ThreadingHTTPServer((host, port), H).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
