#!/usr/bin/env python3
"""devin-usage.py — fleet dispatch-token/cost monitor.

Scans ~/.local/share/devin-dispatch/tasks/*/transcript.json on each runner
host (local + ssh), aggregates per-day per-model token metrics, and
estimates $ where the model has a known price. Free-tier models are
reported but costed at $0 — "Free" in `devin models list` means included
in the plan, NOT unlimited; monthly allowance limits still apply and are
not visible here.

Usage:
  devin-usage.py                     # local host only, last 7 days
  devin-usage.py --fleet             # all dispatch-capable hosts
  devin-usage.py --days 30 --json
"""
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

TASKS_DIR = os.path.expanduser("~/.local/share/devin-dispatch/tasks")

# Dispatch-capable runner hosts (ssh names). mn01 excluded — no Devin CLI.
FLEET = ["tony-dell", "tony-omen", "idc01", "idc02", "idc03"]

# Pricing per 1M tokens: (input, cached_input, output) USD.
# From `devin models list` 2026-10-08. Free-tier models -> None (report
# tokens but no $ estimate — cost is plan-allowance, not invoiced).
PRICES = {
    "swe-2-medium": None,
    "swe-2-high": None,
    "swe-2-max": None,
    "adaptive": (0.5, 0.1, 2.0),
    "gpt-6-luna-none": (0.1, 0.01, 0.5),
    "gpt-6-luna-low": (0.1, 0.01, 0.5),
    "gemini-3.8-flash-low": (0.75, 0.08, 3.75),
    "glm-5.2": (1.4, 0.26, 4.4),
}
FREE = {m for m, p in PRICES.items() if p is None}

REMOTE_SNIPPET = r"""
import json, os, glob
for f in sorted(glob.glob(os.path.expanduser(
        "~/.local/share/devin-dispatch/tasks/*/transcript.json"))):
    d = os.path.dirname(f)
    try:
        t = json.load(open(f))
        m = json.load(open(os.path.join(d, "meta.json")))
    except Exception:
        continue
    fm = t.get("final_metrics") or {}
    print(json.dumps({
        "task": os.path.basename(d),
        "session": t.get("session_id"),
        "model": (t.get("agent") or {}).get("model_name"),
        "prompt": fm.get("total_prompt_tokens", 0),
        "cached": fm.get("total_cached_tokens", 0),
        "completion": fm.get("total_completion_tokens", 0),
        "steps": fm.get("total_steps", 0),
        "result": m.get("result"),
        "finished_at": m.get("finished_at") or m.get("started_at"),
    }))
"""


def norm_model(name):
    """'SWE-2 High' -> 'swe-2-high' (transcript uses display name)."""
    return (name or "unknown").lower().replace(" ", "-")


def scan_local():
    out = []
    for d in sorted(os.listdir(TASKS_DIR)) if os.path.isdir(TASKS_DIR) else []:
        tj = os.path.join(TASKS_DIR, d, "transcript.json")
        if not os.path.isfile(tj):
            continue
        try:
            t = json.load(open(tj))
            m = json.load(open(os.path.join(TASKS_DIR, d, "meta.json")))
        except Exception:
            continue
        fm = t.get("final_metrics") or {}
        out.append({
            "task": d, "session": t.get("session_id"),
            "model": (t.get("agent") or {}).get("model_name"),
            "prompt": fm.get("total_prompt_tokens", 0),
            "cached": fm.get("total_cached_tokens", 0),
            "completion": fm.get("total_completion_tokens", 0),
            "steps": fm.get("total_steps", 0),
            "result": m.get("result"),
            "finished_at": m.get("finished_at") or m.get("started_at"),
        })
    return out


def scan_host(host):
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host,
             "python3 -"], input=REMOTE_SNIPPET,
            capture_output=True, text=True, timeout=60)
    except Exception as e:
        return host, [], str(e)
    if r.returncode != 0:
        return host, [], (r.stderr or "ssh failed").strip()[:120]
    rows = []
    for line in r.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return host, rows, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fleet", action="store_true",
                    help="scan all dispatch-capable hosts over ssh")
    ap.add_argument("--hosts", default="",
                    help="comma list override (default FLEET with --fleet)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    per_host = {}
    if a.fleet or a.hosts:
        hosts = a.hosts.split(",") if a.hosts else FLEET
        for h in hosts:
            h, rows, err = scan_host(h)
            per_host[h] = rows
            if err:
                print(f"# {h}: {err}", file=sys.stderr)
    else:
        per_host[os.uname().nodename] = scan_local()

    rows = []
    for h, rs in per_host.items():
        for r in rs:
            r["host"] = h
            try:
                r["when"] = datetime.fromisoformat(
                    (r["finished_at"] or "").replace("Z", "+00:00"))
            except Exception:
                r["when"] = None
            if r["when"] and r["when"] < cutoff:
                continue
            r["model_id"] = norm_model(r["model"])
            uncached = max(0, r["prompt"] - r["cached"])
            r["uncached"] = uncached
            p = PRICES.get(r["model_id"])
            r["est_cost"] = (uncached * p[0] + r["cached"] * p[1]
                             + r["completion"] * p[2]) / 1e6 if p else None
            rows.append(r)

    if a.json:
        print(json.dumps(rows, indent=1, default=str))
        return

    # day x model aggregates
    agg = defaultdict(lambda: [0, 0, 0, 0, 0.0])
    for r in rows:
        key = (r["when"].strftime("%Y-%m-%d") if r["when"] else "?",
               r["model_id"], "free" if r["model_id"] in FREE
               else ("paid" if r["est_cost"] is not None else "unknown"))
        v = agg[key]
        v[0] += 1
        v[1] += r["prompt"]
        v[2] += r["cached"]
        v[3] += r["completion"]
        v[4] += r["est_cost"] or 0

    print(f"{'date':<11}{'model':<22}{'tier':<8}{'sess':>5}"
          f"{'prompt':>12}{'cached':>12}{'completion':>12}{'est $':>8}")
    for (day, model, tier), v in sorted(agg.items()):
        print(f"{day:<11}{model:<22}{tier:<8}{v[0]:>5}"
              f"{v[1]:>12,}{v[2]:>12,}{v[3]:>12,}"
              f"{v[4]:>8.2f}" if tier == "paid" else
              f"{day:<11}{model:<22}{tier:<8}{v[0]:>5}"
              f"{v[1]:>12,}{v[2]:>12,}{v[3]:>12,}{'-':>8}")

    tot_s = len(rows)
    tot_p = sum(r["prompt"] for r in rows)
    tot_c = sum(r["cached"] for r in rows)
    tot_o = sum(r["completion"] for r in rows)
    tot_cost = sum(r["est_cost"] or 0 for r in rows)
    unk = sorted({r["model_id"] for r in rows
                  if r["model_id"] not in PRICES})
    print("-" * 82)
    print(f"{tot_s} sessions | prompt {tot_p:,} | cached {tot_c:,} "
          f"({100*tot_c/tot_p:.0f}%)" if tot_p else f"{tot_s} sessions")
    print(f"completion {tot_o:,} | est. paid spend ${tot_cost:.2f} "
          f"(free-tier sessions excluded — allowance-bound, not invoiced)")
    if unk:
        print(f"# unknown models (no price data): {', '.join(unk)}")
    print("# est $ = uncached*in + cached*cached + out*out per 1M;"
          " authoritative billing = devin /usage or app.devin.ai")


if __name__ == "__main__":
    main()
