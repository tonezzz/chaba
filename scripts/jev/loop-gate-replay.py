#!/usr/bin/env python3
"""loop-gate-replay — replay real bench trajectories through the
stagnation gate (card jev-stagnation-gate-...-a70f74, BEN-0824).

Feeds recorded per-task outcomes to loop-gate.gate() at every prefix
length and reports where the gate first says HALT — i.e. how early it
would have stopped the 4.4h colibri-bench stall (2026-10-24, omen
nest-worker: 13 edu-manage tasks x ~930s of identical HTTP 429 /
timeout, zero artifacts, ~3.4h bench + ~1h prep).

Trajectories are transcribed from the real run logs:

  stall    reports colibri-bench-out.md per-task lines +
           ~/CascadeProjects/archive/colibri-bench.log (omen)
  healthy  clawbot rep 1 of reports/bench-edu-manage-2026-10-24-
           clawbot-baseline-reps3.md (13/13 completed, lat 1-32s)

Usage:
  loop-gate-replay.py                 # both trajectories, all prefixes
  loop-gate-replay.py --strikes 2     # simulate N consecutive halts
  loop-gate-replay.py --out r.json    # also write per-checkpoint records

Backend order is loop-gate's env contract (JEV_GATE_NOUL_ORDER /
JEV_GATE_CHOICE_ORDER / JEV_*_URL). Run on a host that reaches the
backend you want to measure — jevos is idc03-localhost only.
"""
import argparse, json, os, sys, time
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
lg = SourceFileLoader("loop_gate", str(HERE / "loop-gate.py")).load_module()

# (task_id, completed, latency_s, err, notes) — colibri-bench rep 1,
# local-qwen3-6-colibri lane, 2026-10-24 (all 13 failed).
STALL = [
    ("t1-create-bbr-cubic", False, 930, "HTTP 429", ""),
    ("t2-skip-commands", False, 930, "HTTP 429", ""),
    ("t3-update-tailscale", False, 930, "TimeoutError: timed out", ""),
    ("t4-mixed-cap-private", False, 930, "TimeoutError: timed out", ""),
    ("t5-thai-quantization", False, 930, "HTTP 429", ""),
    ("t6-hub-ada-nest-heartbeat", False, 930, "HTTP 429", ""),
    ("t7-ephemeral", False, 930, "HTTP 429", ""),
    ("o1-mark-learned", False, 930, "TimeoutError: timed out", "checks 0/1"),
    ("o2-push-review", False, 930, "HTTP 429", "checks 0/1"),
    ("o3-due-list", False, 930, "HTTP 429", "checks 2/3"),
    ("r1-recall-spaced", False, 930, "HTTP 429", "answer=''"),
    ("r2-recall-tailscale", False, 930, "TimeoutError: timed out", "answer=''"),
    ("r3-recall-none", False, 930, "TimeoutError: timed out", "answer=''"),
]

# clawbot rep 1, 2026-10-24 baseline — 13/13 completed, lat 1-32s.
HEALTHY = [
    ("t1-create-bbr-cubic", True, 32, "", "filed 'TCP BBR vs CUBIC'"),
    ("t2-skip-commands", True, 1, "", ""),
    ("t3-update-tailscale", True, 15, "", "filed 'tailscale acl basics'"),
    ("t4-mixed-cap-private", True, 20, "", "filed 'CAP theorem'"),
    ("t5-thai-quantization", True, 12, "", "filed 'LLM quantization'"),
    ("t6-hub-ada-nest-heartbeat", True, 20, "", "filed 'ada-nest-map'"),
    ("t7-ephemeral", True, 9, "", ""),
    ("o1-mark-learned", True, 13, "", "filed 'spaced repetition'"),
    ("o2-push-review", True, 6, "", "filed 'tailscale acl basics'"),
    ("o3-due-list", True, 8, "", ""),
    ("r1-recall-spaced", True, 21, "", ""),
    ("r2-recall-tailscale", True, 12, "", ""),
    ("r3-recall-none", True, 8, "", ""),
]

# A second stall flavor: agent-loop style repeated identical tool
# failures (the runner-job shape, not the bench-task shape).
AGENT_STALL = [
    ("step-01", False, 95, "HTTP 429", "tool=chat"),
    ("step-02", False, 95, "HTTP 429", "tool=chat"),
    ("step-03", False, 95, "HTTP 429", "tool=chat"),
    ("step-04", False, 120, "TimeoutError", "tool=chat"),
    ("step-05", False, 120, "TimeoutError", "tool=chat"),
    ("step-06", False, 95, "HTTP 429", "tool=chat"),
    ("step-07", False, 95, "HTTP 429", "tool=chat"),
    ("step-08", False, 120, "TimeoutError", "tool=chat"),
]


def traj_state(name, model, rows, rep=1):
    """Same shape bench-edu-manage.bench_loop_state emits."""
    recent, fails = [], 0
    for tid, ok, lat, err, note in rows:
        line = f"{tid} ok={ok} lat={lat:.0f}s" + (f" err={err}" if err else "")
        if note:
            line += f" {note}"
        recent.append(line)
        fails = fails + 1 if not ok else 0
    return lg.normalize_state({
        "loop": "bench" if name != "agent-stall" else "agent",
        "task": f"replay {name} lane model={model} rep {rep}",
        "iterations": len(rows),
        "elapsed_s": round(sum(r[2] for r in rows), 1),
        "heartbeat_age_s": 0,
        "recent": recent[-12:],
        "signals": {"consecutive_failures": fails,
                    "completed": sum(1 for r in rows if r[1]),
                    "lane": name}})


def replay(name, model, rows, min_k=3, strikes=2, halt_p=None,
           warn_p=None, records=None):
    """Probe every prefix len>=min_k; simulate the strikes rule.
    Returns summary dict."""
    checks = []
    streak = 0
    stop_at = None
    for k in range(min_k, len(rows) + 1):
        st = traj_state(name, model, rows[:k])
        t0 = time.time()
        try:
            v = lg.gate(st, halt_p=halt_p, warn_p=warn_p)
        except Exception as e:
            v = {"verdict": "error", "error": str(e)[:160]}
        ms = round((time.time() - t0) * 1000)
        verdict = v.get("verdict") or "unknown"
        if verdict == "halt":
            streak += 1
        else:
            streak = 0
        rec = {"k": k, "at": rows[k - 1][0], "verdict": verdict,
               "noul_p": (v.get("noul") or {}).get("p"),
               "noul_backend": (v.get("noul") or {}).get("backend"),
               "choice": (v.get("choice") or {}).get("action"),
               "choice_backend": (v.get("choice") or {}).get("backend"),
               "backends": v.get("backends"), "degraded": v.get("degraded"),
               "ms": ms}
        checks.append(rec)
        if records is not None:
            records.append({"traj": name, **rec})
        if stop_at is None and streak >= strikes and verdict == "halt":
            stop_at = {"k": k, "at": rows[k - 1][0],
                       "streak": streak}
    first_halt = next((c["k"] for c in checks
                       if c["verdict"] == "halt"), None)
    return {"traj": name, "model": model, "n": len(rows),
            "checks": checks, "first_halt_k": first_halt,
            "stop_at": stop_at,
            "any_non_continue": [c["k"] for c in checks
                                 if c["verdict"] != "continue"]}


def main():
    ap = argparse.ArgumentParser(description="loop-gate trajectory replay")
    ap.add_argument("--strikes", type=int, default=2,
                    help="consecutive halt verdicts to count as stop "
                         "(default 2 — the runner default)")
    ap.add_argument("--min-k", type=int, default=3,
                    help="first prefix length to probe (default 3)")
    ap.add_argument("--halt-p", type=float, default=None)
    ap.add_argument("--warn-p", type=float, default=None)
    ap.add_argument("--traj", choices=["stall", "healthy", "agent-stall",
                                       "all"], default="all")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    runs = []
    if args.traj in ("stall", "all"):
        runs.append(("stall", "qwen3.6-colibri", STALL))
    if args.traj in ("healthy", "all"):
        runs.append(("healthy", "openrouter/free", HEALTHY))
    if args.traj in ("agent-stall", "all"):
        runs.append(("agent-stall", "local-agent", AGENT_STALL))

    records = []
    print("== loop-gate replay ==  strikes=%d min_k=%d" %
          (args.strikes, args.min_k))
    print("%-11s %4s %6s %8s %-8s %-7s %-7s %6s %s" %
          ("traj", "k", "verdict", "noul_p", "choice", "noul_be", "ch_be",
           "ms", "at"))
    summaries = []
    for name, model, rows in runs:
        s = replay(name, model, rows, min_k=args.min_k,
                   strikes=args.strikes, halt_p=args.halt_p,
                   warn_p=args.warn_p, records=records)
        summaries.append(s)
        for c in s["checks"]:
            print("%-11s %4d %-8s %8s %-7s %-7s %-7s %6d %s" % (
                name, c["k"], c["verdict"],
                "" if c["noul_p"] is None else "%.3f" % c["noul_p"],
                c["choice"] or "-",
                c["noul_backend"] or "-",
                c["choice_backend"] or "-",
                c["ms"], c["at"]))
        stop = s["stop_at"]
        if stop:
            saved = (len(rows) - stop["k"]) * 930
            print("  -> first halt k=%s; strikes-stop at k=%d (%s) — "
                  "would skip %d tasks (~%.1fh saved of %.1fh bench)"
                  % (s["first_halt_k"], stop["k"], stop["at"],
                     len(rows) - stop["k"], saved / 3600,
                     sum(r[2] for r in rows) / 3600))
        else:
            print("  -> never halted (first_halt_k=%s)"
                  % s["first_halt_k"])
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"strikes": args.strikes, "min_k": args.min_k,
             "summaries": [{k: v for k, v in s.items() if k != "checks"}
                           for s in summaries],
             "records": records}, indent=1, ensure_ascii=False))
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
