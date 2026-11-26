#!/usr/bin/env python3
"""loop-gate — Jev stagnation probe for agent/bench loops (BEN-0824).

Watches a running loop's trajectory and answers one supervisor
question: CONTINUE / WARN / REPLAN / HALT. Built for the 4.4h
colibri-bench stall (2026-10-24 — 13 tasks x ~930s of identical
429/timeout, zero artifacts): a semantic judge over loop state catches
what a timeout cannot — the loop is *working*, just not *progressing*.

Two Jev questions per sample (wire shape /v1/systemone, same as
decision-arena.py / code-decision.py):

  stagnant (noul)  "is this trajectory semantically stagnant?" -> p
  action   (choice) CONTINUE | WARN | REPLAN | HALT

Verdict = the more severe of the two signals (levels
continue<warn<replan<halt). With no choice backend the noul p alone
decides: p >= halt_p -> halt, p >= warn_p -> warn, else continue.
No backend answering -> verdict "unknown" (callers must treat as
continue — a gate never kills on missing data).

Backends (first healthy wins per question type; degradation is data,
never silent — see code-decision.py for the same contract):

  noul:    $JEV_API_URL+$JEV_API_KEY -> order in JEV_GATE_NOUL_ORDER
           (default jev-api,jevos,jev-student — jevos measured 0.917
           vs student 0.417 on stagnation in arena v2; spec order
           jev-api,jev-student,jevos via env)
  choice:  $JEV_API_URL+$JEV_API_KEY -> $JEVOS_URL -> jev-student
           (student's choice head is a detected stub — skipped, not
           trusted; real Jev API needs KNB-0822 key)

Env: JEV_API_URL/JEV_API_KEY, JEV_STUDENT_URL, JEVOS_URL,
     JEV_GATE_NOUL_ORDER, JEV_GATE_TIMEOUT_S,
     JEV_GATE_HALT_P (default 0.7), JEV_GATE_WARN_P (default 0.5).

Usage:
  loop-gate.py --state loop.json          # full state dict on stdin/--state -
  loop-gate.py --taskdir ~/.local/share/devin-dispatch/tasks/<tid>
  loop-gate.py --selftest                 # build sample state+questions
  loop-gate.py --health                   # probe backends, no verdict
"""
import argparse, json, os, sys, time, urllib.request
from pathlib import Path

JEV_API_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai")
JEV_API_KEY = os.environ.get("JEV_API_KEY", "")
JEVOS_URL = os.environ.get("JEVOS_URL", "http://127.0.0.1:8017")
STUDENT_URL = os.environ.get("JEV_STUDENT_URL", "http://100.75.102.88:8780")
TIMEOUT = float(os.environ.get("JEV_GATE_TIMEOUT_S", "30"))
HALT_P = float(os.environ.get("JEV_GATE_HALT_P", "0.7"))
WARN_P = float(os.environ.get("JEV_GATE_WARN_P", "0.5"))

VERDICTS = ("continue", "warn", "replan", "halt")
LEVEL = {"continue": 0, "warn": 1, "replan": 2, "halt": 3, "unknown": -1}
LEVEL_NAME = {v: k for k, v in LEVEL.items()}

# Backend order (first healthy wins). Card spec asked for
# "jev-student noul (proven)" — that proof was the confirm-gate
# (arena 1.000). For THIS question the same arena v2 measured
# jev-student stag 0.417 (under-detects: p≈0.005 on a real stall
# trajectory, verified 2026-11-24 replay) vs jevos 0.917; jevos is
# also the only working choice head. Defaults therefore put jevos
# first; jev-student stays as the fleet fallback (it is the only
# tailscale-reachable noul backend — jevos binds 127.0.0.1 on idc03).
# JEV_GATE_NOUL_ORDER / JEV_GATE_CHOICE_ORDER override.
NOUL_ORDER = [s.strip() for s in os.environ.get(
    "JEV_GATE_NOUL_ORDER", "jev-api,jevos,jev-student").split(",")
    if s.strip()]
CHOICE_ORDER = [s.strip() for s in os.environ.get(
    "JEV_GATE_CHOICE_ORDER", "jev-api,jevos,jev-student").split(",")
    if s.strip()]

MAX_RECENT = 20
MAX_LINE = 200


# --- state normalization -------------------------------------------------

def normalize_state(raw):
    """Accept a caller's loop-state dict; fill defaults. Unknown keys
    pass through into the Jev state untouched."""
    if not isinstance(raw, dict):
        return {}
    st = dict(raw)
    st.setdefault("loop", "agent")
    st.setdefault("task", "")
    st.setdefault("iterations", 0)
    st.setdefault("elapsed_s", 0)
    st.setdefault("heartbeat_age_s", None)
    recent = st.get("recent") or []
    if isinstance(recent, str):
        recent = [recent]
    st["recent"] = [str(x)[:MAX_LINE] for x in list(recent)[-MAX_RECENT:]]
    sig = st.get("signals") or {}
    st["signals"] = sig if isinstance(sig, dict) else {}
    return st


def _tail_lines(path, n=MAX_RECENT, size=20000):
    try:
        data = Path(path).read_bytes()[-size:]
    except OSError:
        return []
    lines = [l.strip() for l in data.decode("utf-8", "replace")
             .splitlines() if l.strip()]
    return lines[-n:]


def state_from_taskdir(taskdir, task="", now=None):
    """Build loop state from a devin-dispatch task dir
    (~/.local/share/devin-dispatch/tasks/<tid>): heartbeat = freshest
    mtime among the live artifacts, recent = tail of the newest
    run.*.log (falling back to events.jsonl), iterations = event/step
    counts when present."""
    td = Path(taskdir).expanduser()
    if not td.is_dir():
        return None
    now = now or time.time()
    try:
        meta = json.loads((td / "meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        meta = {}
    if not task:
        task = str(meta.get("card") or meta.get("task_id")
                   or td.name)

    def _mtime(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0
    logs = sorted(td.glob("run.*.log"), key=_mtime)
    events = td / "events.jsonl"
    transcript = td / "transcript.json"
    watched = list(logs) + [events, transcript, td / "exit_code",
                            td / "needs-input.txt", td / "answers.jsonl"]
    if not any(p.exists() for p in watched):
        return None   # no live artifacts yet — caller falls back

    # heartbeat: freshest write among the live artifacts
    beats = []
    for p in watched:
        try:
            beats.append(p.stat().st_mtime)
        except OSError:
            pass
    heartbeat_age = round(now - max(beats), 1) if beats else None

    # iterations: transcript steps (final) else events.jsonl rows else
    # run-log line count (a narration line ~ one agent action)
    iterations = 0
    if transcript.is_file():
        try:
            t = json.loads(transcript.read_text())
            iterations = len(t.get("steps") or [])
        except (OSError, json.JSONDecodeError):
            pass
    if not iterations and events.is_file():
        try:
            iterations = sum(1 for _ in events.open(errors="replace"))
        except OSError:
            pass
    recent = []
    if logs:
        recent = _tail_lines(logs[-1])
    if not recent and events.is_file():
        recent = _tail_lines(events)

    started = meta.get("started_at") or ""
    elapsed = 0
    if started:
        try:
            from datetime import datetime, timezone
            t0 = datetime.fromisoformat(started.replace("Z", "+00:00"))
            elapsed = round(now - t0.timestamp(), 1)
        except (ValueError, AttributeError):
            pass
    if not elapsed and beats:
        elapsed = round(now - min(beats), 1)

    signals = {"log_lines": len(recent) if logs else 0,
               "events": iterations if events.is_file() else 0,
               "transcript_steps": iterations if transcript.is_file() else 0,
               "exit_code": (td / "exit_code").is_file()}
    return normalize_state({
        "loop": "agent", "task": task,
        "iterations": iterations, "elapsed_s": elapsed,
        "heartbeat_age_s": heartbeat_age,
        "recent": recent, "signals": signals,
        "taskdir": str(td)})


# --- questions -----------------------------------------------------------

def build_questions():
    return {
        "stagnant": {
            "type": "noul",
            "instructions": (
                "You are supervising an autonomous agent or benchmark "
                "loop. Below is its current trajectory: the task, how "
                "long it has run, its heartbeat age, iteration count, "
                "and the most recent actions/outputs.\n\n"
                "Is this trajectory semantically stagnant — the loop is "
                "repeating the same action or the same failure with no "
                "new information, artifacts, or progress toward the "
                "task? A loop that is slow but producing distinct "
                "results is NOT stagnant; a loop that is 'working' "
                "(i.e. calls are in flight) but returning identical "
                "errors with no forward motion IS stagnant."),
            "criteria": {
                "true": "stagnant — repeated identical actions/failures, "
                        "no progress toward the task",
                "false": "progressing — distinct actions and/or new "
                         "results, or too little data to judge"}},
        "action": {
            "type": "choice",
            "instructions": (
                "Given this supervised loop's trajectory, what should "
                "the supervisor do? Pick exactly one."),
            "criteria": {
                "continue": "healthy progress — let it run",
                "warn": "slow or noisy but progressing — log a warning, "
                        "keep watching",
                "replan": "stuck on the current approach — intervene "
                          "with a different plan; do not kill yet",
                "halt": "semantically stagnant — kill the loop now; "
                        "it will not recover on its own"}},
    }


# --- backends ------------------------------------------------------------

def _post(base, state, questions, timeout=TIMEOUT, api_key=""):
    payload = {"model": "jev-latest", "state": state,
               "questions": questions}
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


def _backends(order):
    """Resolve backend names -> (name, base, api_key) in order."""
    table = {"jev-api": (JEV_API_URL, JEV_API_KEY),
             "jev-student": (STUDENT_URL, ""),
             "jevos": (JEVOS_URL, "")}
    out = []
    for name in order:
        if name == "jev-api" and not JEV_API_KEY:
            continue
        if name in table:
            base, key = table[name]
            out.append((name, base, key))
    return out


def _is_choice_stub(ans):
    """jev-student/gemma-head return choice='answer', confidence=0.0."""
    return (isinstance(ans, dict) and ans.get("confidence") == 0.0
            and ans.get("choice") == "answer")


def _ask_noul(state, questions, degraded):
    """First healthy noul backend -> (p, backend, ms). `questions` is
    the single-question dict {"stagnant": ...}."""
    ms_total = 0
    last_err = None
    for name, base, key in _backends(NOUL_ORDER):
        answers, ms, err = _post(base, state, questions,
                                 timeout=TIMEOUT, api_key=key)
        ms_total += ms
        if err:
            last_err = "%s: %s" % (name, err)
            continue
        a = answers.get("stagnant") or {}
        p = a.get("noul")
        if isinstance(p, (int, float)):
            return p, name, ms_total
        degraded.append("%s: no noul probability in answer" % name)
    if last_err:
        degraded.append("noul: all backends failed — " + last_err)
    return None, None, ms_total


def _ask_choice(state, questions, degraded):
    """First healthy choice backend -> (action, confidence, backend, ms).
    `questions` is the single-question dict {"action": ...}."""
    ms_total = 0
    last_err = None
    for name, base, key in _backends(CHOICE_ORDER):
        answers, ms, err = _post(base, state, questions,
                                 timeout=TIMEOUT, api_key=key)
        ms_total += ms
        if err:
            last_err = "%s: %s" % (name, err)
            continue
        a = answers.get("action") or {}
        if _is_choice_stub(a):
            degraded.append("%s: choice head is a stub "
                            "(confidence=0)" % name)
            continue
        act = a.get("choice")
        if act in VERDICTS:
            return act, a.get("confidence"), name, ms_total
        degraded.append("%s: choice %r not a verdict" % (name, act))
    if last_err:
        degraded.append("choice: all backends failed — " + last_err)
    return None, None, None, ms_total


# --- verdict -------------------------------------------------------------

def _noul_level(p, halt_p=HALT_P, warn_p=WARN_P):
    if p is None:
        return None
    if p >= halt_p:
        return LEVEL["halt"]
    if p >= warn_p:
        return LEVEL["warn"]
    return LEVEL["continue"]


def gate(state, halt_p=None, warn_p=None):
    """Run the probe on a normalized loop state -> verdict dict.
    Never raises on backend failure — degradation is data."""
    state = normalize_state(state)
    halt_p = HALT_P if halt_p is None else halt_p
    warn_p = WARN_P if warn_p is None else warn_p
    questions = build_questions()
    degraded = []

    p, nb, _ = _ask_noul(state, {"stagnant": questions["stagnant"]},
                         degraded)
    act, conf, cb, _ = _ask_choice(state, {"action": questions["action"]},
                                   degraded)

    nlevel = _noul_level(p, halt_p, warn_p)
    levels = [lv for lv in (nlevel,
                            LEVEL.get(act) if act else None)
              if lv is not None]
    verdict = LEVEL_NAME[max(levels)] if levels else "unknown"

    return {"ok": True, "verdict": verdict,
            "noul": {"p": p, "level": LEVEL_NAME.get(nlevel),
                     "backend": nb},
            "choice": {"action": act, "confidence": conf,
                       "backend": cb},
            "backends": {"noul": nb, "choice": cb},
            "degraded": degraded,
            "thresholds": {"halt_p": halt_p, "warn_p": warn_p},
            "state": {k: state.get(k) for k in
                      ("loop", "task", "iterations", "elapsed_s",
                       "heartbeat_age_s")}}


# --- health / CLI ---------------------------------------------------------

def health(timeout=8):
    out = {}
    for name, base, key in _backends(NOUL_ORDER + CHOICE_ORDER):
        if name in out:
            continue
        try:
            req = urllib.request.Request(
                base.rstrip("/") + "/health",
                headers=({"Authorization": "Bearer " + key}
                         if key else {}))
            urllib.request.urlopen(req, timeout=timeout)
            out[name] = True
        except Exception:
            out[name] = False
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Jev stagnation gate for agent/bench loops")
    ap.add_argument("--state", help="loop-state JSON file ('-' = stdin)")
    ap.add_argument("--taskdir",
                    help="devin-dispatch task dir to sample")
    ap.add_argument("--task", default="", help="goal line for --taskdir")
    ap.add_argument("--halt-p", type=float, default=None)
    ap.add_argument("--warn-p", type=float, default=None)
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        sample = normalize_state({
            "task": "bench lane: edu-manage corpus on local model",
            "loop": "bench", "iterations": 9, "elapsed_s": 8400,
            "heartbeat_age_s": 12,
            "recent": ["t4-mixed-cap-private ok=False lat=930s "
                       "err=HTTP 429",
                       "t5-thai-quantization ok=False lat=930s "
                       "err=HTTP 429",
                       "t6-hub-ada-nest-heartbeat ok=False lat=930s "
                       "err=TimeoutError"],
            "signals": {"consecutive_failures": 9}})
        print(json.dumps({"state": sample,
                          "questions": build_questions()},
                         indent=1, ensure_ascii=False))
        return 0

    if args.health:
        print(json.dumps({"backends": health()}, indent=1))
        return 0

    if args.taskdir:
        st = state_from_taskdir(args.taskdir, task=args.task)
        if st is None:
            print(json.dumps({"ok": False,
                              "error": "taskdir not found"}))
            return 1
    elif args.state:
        raw = sys.stdin.read() if args.state == "-" \
            else Path(args.state).read_text()
        try:
            st = normalize_state(json.loads(raw))
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
    else:
        if not sys.stdin.isatty():
            try:
                st = normalize_state(json.load(sys.stdin))
            except json.JSONDecodeError as e:
                print(json.dumps({"ok": False, "error": str(e)}))
                return 1
        else:
            ap.error("need --state, --taskdir, or JSON on stdin")

    out = gate(st, halt_p=args.halt_p, warn_p=args.warn_p)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
