#!/usr/bin/env python3
"""host-ready-check.py — R7 readiness probe across the fleet.

Reads docs/ssot/infrastructure/ssot.host-software.yml, ssh-probes every
declared capability on every host, and reports pass/fail/unreachable.
A capability that was true yesterday and fails today is drift — same
"live state vs declared state" bug R1 kills, one layer below services.

  host-ready-check.py [--host NAME] [--json-out PATH] [--timeout N]

Exit 0 when everything reachable passes; 1 on any failure; 2 on bad args.
Unreachable hosts report 'down' for every capability — informational for
laptops (see manifest note), a defect for declared-always-on hosts.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "docs/ssot/infrastructure/ssot.host-software.yml"
SSH_BASE = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new"]


def probe(host, cmd, timeout):
    r = subprocess.run(SSH_BASE + [host, cmd], capture_output=True,
                       text=True, timeout=timeout + 10)
    if r.returncode == 255:
        return "down", (r.stderr or r.stdout).strip()[:120]
    return ("pass" if r.returncode == 0 else "fail",
            (r.stdout or r.stderr).strip()[-120:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--json-out")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--manifest", default=str(MANIFEST))
    a = ap.parse_args()

    man = yaml.safe_load(Path(a.manifest).read_text())
    caps = man.get("capabilities") or {}
    hosts = {a.host: man["hosts"][a.host]} if a.host else (man.get("hosts") or {})
    if a.host and a.host not in man.get("hosts", {}):
        print(f"host {a.host} not in manifest", file=sys.stderr)
        return 2

    results = {}
    fails = 0
    for host, spec in hosts.items():
        results[host] = {}
        for cap in spec.get("capabilities") or []:
            c = caps.get(cap)
            if not c:
                results[host][cap] = {"status": "undef"}
                continue
            try:
                status, detail = probe(host, c["probe"], a.timeout)
            except subprocess.TimeoutExpired:
                status, detail = "timeout", f">{a.timeout}s"
            ok = status == "pass" or (
                c.get("expect_re") and status == "pass"
                and re.search(c["expect_re"], detail or ""))
            if status == "pass" and c.get("expect_re") \
                    and not re.search(c["expect_re"], detail or ""):
                status, ok = "fail", False
            results[host][cap] = {"status": status, "detail": detail}
            if status in ("fail", "timeout"):
                fails += 1
            print(f"{host:12} {cap:16} {status:8} {detail or ''}",
                  flush=True)

    summary = {"run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "results": results, "fails": fails}
    if a.json_out:
        p = Path(os.path.expanduser(a.json_out))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, indent=2))
        print(f"wrote {p}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
