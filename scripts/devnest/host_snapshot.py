#!/usr/bin/env python3
"""host_snapshot.py — single-call read-only host health probe
(card ops-manual-command-api-mcp-efficiency-audit, AUD-1033).

Collapses the ~10-command micro-probe storm (hostname, date, uptime,
nproc, free, df, systemctl x2 — plus the date-arithmetic retries agents
insert between them) into ONE bounded call that emits exactly the
ops-readonly lane contract
(evals/opencode-lane/profiles/ops-readonly/fixture/task.yaml
#contract.required_fields). Local proc/sysfs reads plus two systemctl
list-units calls; no network, no writes, stdlib only — safe for profile
bash allowlists the way mddb_probe.py is for the mddb-sequence lane.

    host_snapshot.py            # compact JSON on stdout
    host_snapshot.py --pretty   # indented JSON
    host_snapshot.py --timeout 5   # per-probe subprocess ceiling (s)

Degradation contract: a failed collector yields null/-1 fields and a
"errors" list naming the probe — callers must check errors before
trusting the snapshot; the process still exits 0 so one bad probe
never aborts the report.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from datetime import datetime, timezone


def _read(path: str) -> str:
    with open(path, errors="replace") as f:
        return f.read()


def _run(cmd: list, timeout: float) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"rc={r.returncode}")
    return r.stdout


def uptime_seconds() -> float:
    return float(_read("/proc/uptime").split()[0])


def loadavg() -> tuple:
    p = _read("/proc/loadavg").split()
    return float(p[0]), float(p[1]), float(p[2])


def mem_mb() -> tuple:
    vals = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, rest = line.partition(":")
        vals[k.strip()] = int(rest.strip().split()[0])  # kB
    total = vals.get("MemTotal", 0) // 1024
    avail = vals.get("MemAvailable", vals.get("MemFree", 0)) // 1024
    return total, avail


def disk_root_pct() -> int:
    st = os.statvfs("/")
    if not st.f_blocks:
        return -1
    return round(100 * (1 - st.f_bavail / st.f_blocks))


def failed_units(user: bool, timeout: float) -> list:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["list-units", "--failed", "--no-legend", "--plain"]
    out = _run(cmd, timeout)
    return [ln.split()[0] for ln in out.splitlines() if ln.strip()]


def collect(timeout: float = 5.0) -> dict:
    """Assemble the snapshot; each collector degrades independently."""
    snap = {"read_only": True, "errors": []}
    probes = {
        "host": lambda: platform.node() or "unknown",
        "collected_at": lambda: datetime.now(timezone.utc)
        .isoformat(timespec="seconds"),
        "uptime_seconds": uptime_seconds,
        "loadavg": loadavg,
        "cpu_count": lambda: os.cpu_count() or 1,
        "mem_mb": mem_mb,
        "disk_root_pct": disk_root_pct,
        "failed_system": lambda: failed_units(False, timeout),
        "failed_user": lambda: failed_units(True, timeout),
    }
    vals = {}
    for name, fn in probes.items():
        try:
            vals[name] = fn()
        except Exception as e:
            vals[name] = None
            snap["errors"].append(f"{name}: {e}")
    l1, l5, l15 = vals["loadavg"] or (-1.0, -1.0, -1.0)
    mem_t, mem_a = vals["mem_mb"] or (-1, -1)
    snap.update({
        "host": vals["host"],
        "collected_at": vals["collected_at"],
        "uptime_seconds": vals["uptime_seconds"]
        if vals["uptime_seconds"] is not None else -1.0,
        "load1": l1, "load5": l5, "load15": l15,
        "cpu_count": vals["cpu_count"] or 0,
        "mem_total_mb": mem_t, "mem_available_mb": mem_a,
        "disk_root_pct": (vals["disk_root_pct"]
                          if vals["disk_root_pct"] is not None else -1),
        "failed_units": sorted(
            (vals["failed_system"] or []) + (vals["failed_user"] or [])),
    })
    if not snap["errors"]:
        snap.pop("errors")
    return snap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--timeout", type=float, default=5.0,
                    help="per-probe subprocess ceiling, seconds")
    a = ap.parse_args()
    snap = collect(timeout=a.timeout)
    print(json.dumps(snap, indent=2 if a.pretty else None,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
