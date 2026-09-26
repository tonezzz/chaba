#!/usr/bin/env python3
"""API spend/quota digest (L1.5h): rate-limit + quota signals from journald.

No billing API needed — counts 429 / quota / RESOURCE_EXHAUSTED lines and
embedding/LLM call volumes per host+unit. A 429 storm or silent quota
exhaustion shows up here. Personal-tier data.

Usage:
  spend-report.py [--hosts idc01,tony-omen] [--since "24 hours ago"]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

DEFAULT_OUT = Path.home() / ".local/share/ada-review"
DEFAULT_HOSTS = ["idc01", "tony-omen"]
LOCAL_NAMES = {"tony-omen", "localhost", ""}

# journald grep filter — rate limits, quota, billing-ish errors
GREP = ("grep -aiE 'HTTP.{0,6}429|status.{0,4}429|[^0-9]429[^0-9]|"
        "rate.?limit|RESOURCE_EXHAUSTED|quota (exceeded|limit)|billing'")

RX_UNIT = re.compile(r"^([\w@.-]+(?:\.service|\.scope))")
# precise 429 — not inside a hex/uuid token (devin session ids, macs)
RX_429 = re.compile(r"(?<![0-9a-zA-Z])429(?![0-9a-zA-Z])")
RX_RL = re.compile(r"(?<![0-9a-zA-Z])429(?![0-9a-zA-Z])|rate.?limit|"
                   r"RESOURCE_EXHAUSTED|quota (exceeded|limit)", re.I)


def _run(cmd: list[str], timeout: int = 60) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return ""


def _ssh(host: str, remote: str, timeout: int = 60) -> str:
    if host in LOCAL_NAMES:
        return _run(["bash", "-c", remote], timeout)
    return _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 host, remote], timeout)


def sweep(host: str, since: str) -> dict:
    out = _ssh(
        host,
        f"journalctl --user --since '{since}' --no-pager "
        f"-o short-monotonic 2>/dev/null | {GREP} | head -3000; "
        f"journalctl --since '{since}' --no-pager -o short-monotonic "
        f"2>/dev/null | {GREP} | head -2000",
        timeout=120)
    lines = [l for l in out.splitlines() if l.strip()
             and "function_call result" not in l
             and "[RATELIMIT]" not in l]  # tailscaled log-suppression noise
    rl = [l for l in lines if RX_RL.search(l)]
    # attribute to a service when identifiable (mddb wraps its lines in
    # 'time=... level=WARN msg="..."' — no unit prefix; count raw)
    r429 = sum(1 for l in rl if RX_429.search(l))
    quota = sum(1 for l in rl if re.search(
        r"quota (exceeded|limit)|RESOURCE_EXHAUSTED", l, re.I))
    rate = sum(1 for l in rl if re.search(r"rate.?limit", l, re.I))
    tops = Counter(l.strip()[:90] for l in rl)
    return {"host": host, "rl_lines": len(rl), "http_429": r429,
            "quota": quota, "rate_limit": rate,
            "top": dict(tops.most_common(4)),
            "reachable": bool(out.strip()) or host in LOCAL_NAMES}


def spend_block(rows: list[dict], since: str) -> str:
    lines = [f"## spend ({since})"]
    if not rows:
        lines.append("no hosts reachable")
        return "\n".join(lines)
    for r in rows:
        flag = " ⚠" if r["http_429"] or r["quota"] or r["rate_limit"] else ""
        lines.append(
            f"{r['host']}: rate/quota lines {r['rl_lines']} "
            f"(429 {r['http_429']}, quota {r['quota']}, "
            f"ratelimit {r['rate_limit']}){flag}")
        for t, c in list(r["top"].items())[:3]:
            lines.append(f"  x{c} {t}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hosts", default=",".join(DEFAULT_HOSTS))
    ap.add_argument("--since", default="24 hours ago")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = []
    for h in [x.strip() for x in args.hosts.split(",") if x.strip()]:
        try:
            rows.append(sweep(h, args.since))
        except Exception as e:
            print(f"warn: {h}: {e}", file=sys.stderr)

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "spend-ops.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} hosts -> {ops}")
    print(spend_block(rows, args.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
