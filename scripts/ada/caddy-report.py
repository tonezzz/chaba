#!/usr/bin/env python3
"""Caddy access-log digest (L1.5i): per-app usage + error rates.

Reads JSON access entries from the web edge (caddy `log app80` into
/data/access.log — enabled 2026-09-26, rotated 10MB x5). Groups by path
prefix (/apps/<name>, first two segments) with status-class and latency.
Personal-tier data — local only.

Usage:
  caddy-report.py [--host tony-dell] [--tail 20000]
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
DEFAULT_HOST = "tony-dell"


def _ssh(host: str, remote: str, timeout: int = 90) -> str:
    try:
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             host, remote],
            capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def app_of(uri: str) -> str:
    m = re.match(r"^/apps/([^/?]+)", uri)
    if m:
        return f"apps/{m.group(1)}"
    m = re.match(r"^(/[^/?]+)", uri)
    return m.group(1) if m else "/"


def sweep(host: str, tail: int) -> dict:
    out = _ssh(host, f"podman exec web tail -{tail} /data/access.log "
                     "2>/dev/null")
    rows = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            e = json.loads(ln)
        except Exception:
            continue
        req = e.get("request") or {}
        rows.append({
            "uri": req.get("uri", ""),
            "status": e.get("status", 0),
            "dur": e.get("duration", 0),
            "client": req.get("client_ip", "?"),
        })
    apps: Counter = Counter()
    errors: Counter = Counter()
    slowest: list[tuple[float, str]] = []
    clients: Counter = Counter()
    for r in rows:
        a = app_of(r["uri"])
        apps[a] += 1
        clients[r["client"]] += 1
        if r["status"] >= 400:
            errors[a] += 1
        slowest.append((r["dur"], r["uri"]))
    slowest.sort(reverse=True)
    return {"host": host, "requests": len(rows),
            "apps": dict(apps.most_common(15)),
            "errors": dict(errors.most_common(8)),
            "slowest": [{"uri": u[:70], "dur": round(d, 2)}
                        for d, u in slowest[:5]],
            "clients": dict(clients.most_common(5))}


def caddy_block(rows: list[dict], since: str) -> str:
    lines = [f"## apps ({since})"]
    for r in rows:
        if not r["requests"]:
            lines.append(f"{r['host']}: no access entries")
            continue
        err_n = sum(r["errors"].values())
        flag = " ⚠" if err_n else ""
        lines.append(f"{r['host']}: {r['requests']} reqs, "
                     f"{err_n} errors{flag}")
        lines.append("  top: " + ", ".join(
            f"{a} x{c}" for a, c in list(r["apps"].items())[:8]))
        if r["errors"]:
            lines.append("  err: " + ", ".join(
                f"{a} x{c}" for a, c in list(r["errors"].items())[:5]))
        for s in r["slowest"][:2]:
            lines.append(f"  slow {s['dur']}s {s['uri']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--tail", type=int, default=20000)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    row = sweep(args.host, args.tail)
    ops = args.out / "apps-ops.jsonl"
    ops.write_text(json.dumps(row, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{row['requests']} requests -> {ops}")
    print(caddy_block([row], f"last {args.tail} reqs"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
