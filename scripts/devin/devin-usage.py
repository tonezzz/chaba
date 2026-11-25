#!/usr/bin/env python3
"""devin-usage.py — fleet dispatch-token/cost monitor.

Scans ~/.local/share/devin-dispatch/tasks/*/transcript.json on each runner
host (local + ssh), aggregates per-day per-model token metrics, and
estimates $ where the model has a known price. Free-tier models are
reported but costed at $0 — "Free" in `devin models list` means included
in the plan, NOT unlimited; the plan-quota remainder is probed separately
(see Allowance below).

Usage:
  devin-usage.py                     # local host only, last 7 days
  devin-usage.py --fleet             # all dispatch-capable hosts
  devin-usage.py --days 30 --json
  devin-usage.py --no-allowance      # skip the plan-quota probe (offline)

Allowance (plan quota) comes from the same Connect RPC the CLI's TUI
/usage view uses: POST {api_server}/exa.seat_management_pb.
SeatManagementService/GetUserStatus with the stored windsurf_api_key —
read-only, no spend. Requires ~/.local/share/devin/credentials.toml on
the host running the script.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

TASKS_DIR = os.path.expanduser("~/.local/share/devin-dispatch/tasks")
CREDS_PATH = os.path.expanduser("~/.local/share/devin/credentials.toml")
USER_STATUS_RPC = ("/exa.seat_management_pb.SeatManagementService/"
                   "GetUserStatus")

# Dispatch-capable runner hosts (ssh names).
FLEET = ["tony-dell", "tony-omen", "idc01", "idc02", "idc03", "mn01"]

# Pricing per 1M tokens: (input, cached_input, output) USD.
# From `devin models list` 2026-10-08. Free-tier models -> None (report
# tokens but no $ estimate — cost is plan-allowance, not invoiced).
PRICES = {
    "swe-2-medium": None,
    "swe-2-high": None,
    "swe-2-max": None,
    # Free SWE-2 Flash family (verified in `devin models list` 2026-11-23:
    # "[... Free]"). Without these, sessions show as "unknown" and drop
    # out of free-tier allowance burn accounting. The *-lightning
    # variants are PAID ($1/$5 per 1M) and are intentionally absent.
    "swe-2-flash-medium": None,
    "swe-2-flash-high": None,
    "swe-2-flash-max": None,
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


def load_credentials(path=CREDS_PATH):
    """Parse ~/.local/share/devin/credentials.toml (flat key = "value")."""
    creds = {}
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'\s*(\w+)\s*=\s*"([^"]*)"', line)
                if m:
                    creds[m.group(1)] = m.group(2)
    except OSError:
        pass
    return creds


def _iso(unix):
    try:
        return datetime.fromtimestamp(int(unix), timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return None


def parse_user_status(data):
    """Normalize a GetUserStatusResponse into allowance fields."""
    us = data.get("userStatus") or {}
    ps = us.get("planStatus") or {}
    pi = ps.get("planInfo") or {}
    out = {
        "plan": pi.get("planName") or data.get("planInfo", {}).get(
            "planName"),
        "billing_strategy": (ps.get("billingStrategy")
                             or pi.get("billingStrategy")),
        "plan_start": ps.get("planStart"),
        "plan_end": ps.get("planEnd"),
        "daily_remaining_pct": ps.get("dailyQuotaRemainingPercent"),
        "weekly_remaining_pct": ps.get("weeklyQuotaRemainingPercent"),
        "daily_reset": _iso(ps.get("dailyQuotaResetAtUnix")),
        "weekly_reset": _iso(ps.get("weeklyQuotaResetAtUnix")),
        "overage_usd": None,
    }
    micros = ps.get("overageBalanceMicros")
    if micros not in (None, ""):
        try:
            out["overage_usd"] = round(int(micros) / 1e6, 2)
        except (TypeError, ValueError):
            pass
    return out


def fetch_allowance(creds_path=CREDS_PATH, timeout=15):
    """Read-only plan-quota probe. Returns (allowance_dict, error_str)."""
    creds = load_credentials(creds_path)
    api_key = creds.get("windsurf_api_key")
    server = (creds.get("api_server_url")
              or "https://server.codeium.com").rstrip("/")
    if not api_key:
        return None, "no windsurf_api_key in credentials.toml"
    # ide_version/extension_version must be semver — the server 500s on
    # free-form strings (verified 2026-11-25).
    meta = {"api_key": api_key, "ide_name": "devin-cli",
            "ide_version": "0.1.0", "extension_name": "devin-cli",
            "extension_version": "0.1.0", "locale": "en-US",
            "os": sys.platform}
    req = urllib.request.Request(
        server + USER_STATUS_RPC,
        data=json.dumps({"metadata": meta}).encode(),
        headers={"Content-Type": "application/json",
                 "Connect-Protocol-Version": "1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except Exception as e:
        return None, str(e)[:120]
    return parse_user_status(data), None


def format_allowance(allowance):
    """One footer line for a parsed allowance dict."""
    bits = []
    if allowance.get("plan"):
        bits.append(str(allowance["plan"]))
    if allowance.get("daily_remaining_pct") is not None:
        bits.append(f"daily {allowance['daily_remaining_pct']}% left"
                    + (f" (reset {allowance['daily_reset']})"
                       if allowance.get("daily_reset") else ""))
    if allowance.get("weekly_remaining_pct") is not None:
        bits.append(f"weekly {allowance['weekly_remaining_pct']}% left"
                    + (f" (reset {allowance['weekly_reset']})"
                       if allowance.get("weekly_reset") else ""))
    if allowance.get("overage_usd") is not None:
        bits.append(f"overage ${allowance['overage_usd']:.2f}")
    if allowance.get("plan_end"):
        bits.append(f"plan ends {allowance['plan_end'][:10]}")
    return ("allowance: " + " | ".join(bits)) if bits else None


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
    ap.add_argument("--no-allowance", action="store_true",
                    help="skip the plan-quota probe (offline / tests)")
    a = ap.parse_args()

    allowance, allowance_err = (None, None)
    if not a.no_allowance:
        allowance, allowance_err = fetch_allowance()

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
        print(json.dumps({"sessions": rows, "allowance": allowance,
                          "allowance_error": allowance_err},
                         indent=1, default=str))
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
    # Free-tier allowance burn (added 2026-11-23, devin-usage-reduction
    # DEV-0044): free = plan-included models (PRICES value None). The burn
    # tracked for reduction purposes is tokens consumed against the plan
    # allowance (prompt + completion; cached tokens ride along in the
    # prompt count) — reported as allowance-bound, never invoiced.
    free_rows = [r for r in rows if r["model_id"] in FREE]
    f_sess = len(free_rows)
    f_p = sum(r["prompt"] for r in free_rows)
    f_o = sum(r["completion"] for r in free_rows)
    f_tok = f_p + f_o
    unk = sorted({r["model_id"] for r in rows
                  if r["model_id"] not in PRICES})
    print("-" * 82)
    print(f"{tot_s} sessions | prompt {tot_p:,} | cached {tot_c:,} "
          f"({100*tot_c/tot_p:.0f}%)" if tot_p else f"{tot_s} sessions")
    print(f"completion {tot_o:,} | est. paid spend ${tot_cost:.2f} "
          f"(free-tier sessions excluded — allowance-bound, not invoiced)")
    print(f"free-tier allowance burn (window): {f_sess} sessions | "
          f"prompt {f_p:,} + completion {f_o:,} = {f_tok:,} tokens "
          f"(allowance-bound, not invoiced)")
    if unk:
        print(f"# unknown models (no price data): {', '.join(unk)}")
    line = format_allowance(allowance) if allowance else None
    if line:
        print(line)
    else:
        why = allowance_err or "skipped (--no-allowance)"
        print(f"allowance remaining: not retrievable ({why}) — "
              "human view: `devin` TUI /usage or app.devin.ai settings")
    print("# est $ = uncached*in + cached*cached + out*out per 1M;"
          " allowance above is the authoritative plan-quota remainder")


if __name__ == "__main__":
    main()
