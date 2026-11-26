#!/usr/bin/env python3
"""score.py — kk-mac task-class eval scorer (card
kk-mac-extract-brief-class-eval).

Runs the corpus (structured_extract / operator_brief / safe_route cases,
plus a small summary control set) against kk-mac's local ollama and
scored by the PRODUCTION verifier — scripts/devnest/kk_mac_executor.py
verify(): json_parses + expect.required_keys/enums/facts. A case passes
exactly when the lane itself would return verdict=pass, so the pass rate
answers the card's question: can these classes take real inbox work?

The model call is the production shape too — kk_mac_llm.call_remote:
ssh+ollama /api/generate with think=false, temperature 0, and the spec's
format hint. No chat wrapper, no system prompt: the inbox spec's prompt
is all the model ever sees.

Same harness pattern as scripts/bench/card-judgment/score.py +
scripts/bench/vision-qa/score.py: corpus jsonl -> entity -> per-case
verdicts -> metrics + md/json report, with the member-device thermal
gate (pause while the node runs hot).

Entities:
  kkmac        production path — ssh <host> -> loopback /api/generate
  mock-oracle  replays each case's gold response — harness selftest

Usage:
  score.py --entity mock-oracle                      # corpus selftest
  score.py --entity kkmac --model qwen3:8b --host kk-mac \
      --temp-host kk-mac --temp-ssh-user kkkakk --max-temp-c 60
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_DEVNEST = str(Path(__file__).resolve().parents[2] / "devnest")
if _DEVNEST not in sys.path:
    sys.path.insert(0, _DEVNEST)
import kk_mac_executor  # noqa: E402
import kk_mac_llm  # noqa: E402

JSON_CLASSES = kk_mac_executor.JSON_CLASSES
# The bench scores classes whether or not they're currently admitted —
# re-eval is the readmission gate (card kk-mac-admitted-classes-narrow
# holds operator_brief/safe_route while kk_mac_llm.ALLOWED_TASKS is
# narrowed). Gate corpus sanity on verifier-supported classes, not the
# live admission set.
TASK_CLASSES = JSON_CLASSES | {"summary"}
# Classes the lane currently admits — bench rows outside this set are
# HELD (scored for re-eval, never runnable through the lane contract).
ADMITTED_CLASSES = frozenset(kk_mac_llm.ALLOWED_TASKS)


def load_corpus(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]


# ---------------------------------------------------------------- entities
def kkmac_entity_factory(host, model, retries=1):
    """The real lane call: kk_mac_llm.call_remote posts the spec's
    prompt to loopback /api/generate on kk-mac over ssh (think=false,
    temperature 0, format=json when the spec declares it)."""
    def ent(case):
        last = ""
        for attempt in range(retries + 1):
            try:
                res = kk_mac_llm.call_remote(
                    case["prompt"], host=host, model=model,
                    format=case.get("format"), think=False)
                return {"response": res.get("response", ""),
                        "usage": {"eval_count": res.get("eval_count"),
                                  "eval_duration":
                                  res.get("eval_duration"),
                                  "load_duration":
                                  res.get("load_duration")}}
            except Exception as e:
                last = f"ERROR {e}"
                if attempt < retries:
                    time.sleep(2)
        return {"response": "", "usage": None, "error": last[:200]}
    return ent


def mock_oracle_entity(case):
    """Harness selftest — replays the case's gold response; every case
    must pass verify() or the corpus itself is wrong."""
    return {"response": case["gold"], "usage": None}


def entity_from_args(a):
    if a.entity == "mock-oracle":
        return mock_oracle_entity
    return kkmac_entity_factory(a.host, a.model, retries=a.retries)


# ------------------------------------------------------------------ metrics
def score(cases, results):
    """results: [{verdict, checks, latency_s, usage, error}] aligned
    with cases."""
    by_class = {}
    check_fails = {}
    transport_failures = 0
    lat = []
    for c, r in zip(cases, results):
        tc = c["task_class"]
        d = by_class.setdefault(tc, {"n": 0, "pass": 0, "json_ok": 0,
                                     "json_expected": 0})
        d["n"] += 1
        if tc in JSON_CLASSES:
            d["json_expected"] += 1
            if (r.get("checks") or {}).get("json_parses"):
                d["json_ok"] += 1
        if r.get("verdict") == "pass":
            d["pass"] += 1
        if r.get("error"):
            transport_failures += 1
        for k, ok in (r.get("checks") or {}).items():
            if not ok:
                check_fails[k] = check_fails.get(k, 0) + 1
        if r.get("latency_s") is not None:
            lat.append(r["latency_s"])
    n = len(cases)
    per_class = {}
    for tc, d in sorted(by_class.items()):
        per_class[tc] = {
            "n": d["n"],
            "pass_rate": round(d["pass"] / d["n"], 4) if d["n"] else 0,
            "json_parse_rate": (round(d["json_ok"] / d["json_expected"],
                                      4) if d["json_expected"] else None),
        }
    total_pass = sum(d["pass"] for d in by_class.values())
    return {
        "n_cases": n,
        "overall_pass_rate": round(total_pass / n, 4) if n else 0,
        "per_class": per_class,
        "transport_failures": transport_failures,
        "check_failure_histogram": dict(sorted(
            check_fails.items(), key=lambda kv: -kv[1])),
        "latency_s": {"mean": round(sum(lat) / len(lat), 1)
                      if lat else 0,
                      "max": round(max(lat), 1) if lat else 0,
                      "total": round(sum(lat), 1)},
    }


# Provisional "can this class take real inbox work" bar — the lane's own
# verdict is the metric; ~15 cases/class is a smoke, not a gate.
THRESHOLD = {"class_pass_rate": 0.80,
             "json_parse_rate": 0.90,
             "transport_failures": 0}


def report_md(metrics, entity_name, model, per_case):
    th = THRESHOLD
    lines = [
        "# kk-mac task-class eval — lane-verifier run", "",
        f"entity: `{entity_name}` model: `{model or '-'}` "
        f"cases: {metrics['n_cases']} "
        f"latency mean {metrics['latency_s']['mean']}s "
        f"total {metrics['latency_s']['total']}s", "",
        "Scored by the production verifier "
        "(kk_mac_executor.verify): a case passes only when the lane "
        "would return verdict=pass on this exact response.", "",
        "| task_class | n | pass_rate | json_parse | verdict |",
        "|---|---|---|---|---|",
    ]
    for tc, d in metrics["per_class"].items():
        ok = d["pass_rate"] >= th["class_pass_rate"] and (
            d["json_parse_rate"] is None
            or d["json_parse_rate"] >= th["json_parse_rate"])
        jp = "-" if d["json_parse_rate"] is None \
            else d["json_parse_rate"]
        held = " (HELD — not admitted)" if tc not in ADMITTED_CLASSES else ""
        lines.append(f"| {tc}{held} | {d['n']} | {d['pass_rate']} | {jp} | "
                     f"{'READY' if ok else 'not ready'} |")
    lines += [
        f"| **overall** | {metrics['n_cases']} | "
        f"**{metrics['overall_pass_rate']}** | - | - |",
        "",
        f"transport_failures: {metrics['transport_failures']} "
        f"(bar: {th['transport_failures']})",
        "",
        "NOTE: provisional readiness bar — pass_rate >= "
        f"{th['class_pass_rate']} per class, json_parse >= "
        f"{th['json_parse_rate']}. ~15 cases/class is a smoke screen, "
        "not the T3 gate.",
        "",
        "## check-failure histogram (failed check -> count)",
        "```json",
        json.dumps(metrics["check_failure_histogram"], indent=2),
        "```", "",
        "## per-case", "",
        "| case | class | verdict | failed checks | s |",
        "|---|---|---|---|---|",
    ]
    for cid, tc, verdict, failed, s in per_case:
        lines.append(f"| {cid} | {tc} | {verdict} | "
                     f"{' '.join(failed) or '-'} | {s:.1f} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus",
                    default=str(Path(__file__).parent / "corpus.jsonl"))
    ap.add_argument("--entity", default="kkmac",
                    choices=["kkmac", "mock-oracle"])
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--host", default="kk-mac",
                    help="ssh target for the kkmac entity "
                         "(production path)")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--task-class", default="",
                    help="run only one task_class")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--out-md", default="")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--temp-host", default="")
    ap.add_argument("--temp-ssh-user", default="")
    ap.add_argument("--max-temp-c", type=float, default=0.0)
    args = ap.parse_args()

    cases = load_corpus(args.corpus)
    if args.task_class:
        cases = [c for c in cases if c["task_class"] == args.task_class]
    if args.limit:
        cases = cases[:args.limit]
    bad = [c["case_id"] for c in cases
           if c["task_class"] not in TASK_CLASSES
           or len(c.get("prompt", "")) > kk_mac_llm.MAX_PROMPT_CHARS]
    if bad:
        print(f"corpus cases violate the lane contract: {bad}",
              file=sys.stderr)
        return 2
    ent = entity_from_args(args)

    def temp_c():
        if not args.temp_host:
            return None
        target = (f"{args.temp_ssh_user}@" if args.temp_ssh_user
                  else "") + args.temp_host
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 target,
                 "~/.local/bin/smctemp -c 2>/dev/null || "
                 "smctemp -c 2>/dev/null"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return float(r.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return None

    def thermal_pause(case_id):
        """Member-device gate: hold between cases while the node runs
        hot. Unknown temp never blocks (mirrors kk_mac_admission)."""
        while args.max_temp_c > 0:
            t = temp_c()
            if t is None or t <= args.max_temp_c:
                return
            print(f"[{case_id}] thermal gate: {t:.1f}C > "
                  f"{args.max_temp_c:.0f}C — pausing 30s",
                  file=sys.stderr)
            time.sleep(30)

    results, per_case = [], []
    for i, c in enumerate(cases, 1):
        thermal_pause(c["case_id"])
        t0 = time.time()
        out = ent(c)
        s = round(time.time() - t0, 1)
        resp = out.get("response", "")
        v = kk_mac_executor.verify(c["task_class"], resp,
                                   c.get("expect"))
        failed = [k for k, ok in v["checks"].items() if not ok]
        if out.get("error"):
            failed = [out["error"]] + failed
        results.append({"verdict": v["verdict"], "checks": v["checks"],
                        "latency_s": s, "usage": out.get("usage"),
                        "response": resp[:800],
                        "error": out.get("error")})
        per_case.append((c["case_id"], c["task_class"], v["verdict"],
                         failed, s))
        print(f"[{i}/{len(cases)}] {c['case_id']} "
              f"({c['task_class']}): {v['verdict']} "
              f"{s}s"
              + (f" miss={','.join(failed)[:80]}" if failed else ""),
              file=sys.stderr)
        if args.delay:
            time.sleep(args.delay)

    metrics = score(cases, results)
    metrics["entity"] = args.entity
    metrics["model"] = args.model or args.entity
    md = report_md(metrics, args.entity, args.model or args.entity,
                   per_case)
    print(md)
    if args.out_md:
        Path(args.out_md).write_text(md)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(
            {"metrics": metrics,
             "cases": [{"case_id": cid, "task_class": tc,
                        "verdict": v, "failed": f, "latency_s": s}
                       for cid, tc, v, f, s in per_case],
             "results": results}, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
