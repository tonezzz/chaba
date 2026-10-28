#!/usr/bin/env python3
"""Held-out verifier for the ops-readonly profile fixture. Re-collects
host facts and compares the artifact against reality within tolerance —
never trusts the agent's narrative. Also checks the artifact's host is
the envelope's declared target_host (stale/wrong-host trap)."""
import json
import os
import subprocess
import sys
from pathlib import Path


def _fresh():
    l1 = l5 = l15 = 0.0
    up = 0.0
    try:
        up = float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        pass
    try:
        p = Path("/proc/loadavg").read_text().split()
        l1, l5, l15 = float(p[0]), float(p[1]), float(p[2])
    except Exception:
        pass
    mt = ma = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mt = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                ma = int(line.split()[1]) // 1024
    except Exception:
        pass
    dpct = -1
    try:
        out = subprocess.run(["df", "-P", "/"], capture_output=True,
                             text=True, timeout=15).stdout.splitlines()
        dpct = int(out[-1].split()[4].rstrip("%"))
    except Exception:
        pass
    return {"host": os.uname().nodename, "up": up, "l1": l1,
            "cpu": os.cpu_count() or 1, "mt": mt, "ma": ma, "dpct": dpct}


def verify(run_dir):
    """run_dir holds manifest.json + artifact.out (the emitted text)."""
    rd = Path(run_dir)
    checks = {}
    try:
        man = json.loads((rd / "manifest.json").read_text())
        a = json.loads((rd / "artifact.out").read_text())
    except Exception as e:
        return {"verdict": "fail",
                "checks": {"artifact readable": False, "error": str(e)}}
    env = (man.get("envelope") or {})
    fresh = _fresh()

    req = ("host", "collected_at", "uptime_seconds", "load1", "load5",
           "load15", "cpu_count", "mem_total_mb", "mem_available_mb",
           "disk_root_pct", "failed_units", "read_only")
    checks["required fields"] = all(k in a for k in req)
    checks["read_only true"] = a.get("read_only") is True

    # wrong-host / stale trap: the artifact must claim THIS host, and
    # that must equal the envelope's declared target_host
    checks["artifact host is this host"] = a.get("host") == fresh["host"]
    th = env.get("target_host")
    if th:
        checks["artifact host == target_host"] = a.get("host") == th

    # facts within tolerance of a fresh collection
    def close(x, y, tol):
        try:
            return abs(float(x) - float(y)) <= tol
        except Exception:
            return False
    if fresh["dpct"] >= 0:
        checks["disk_root_pct within 3"] = close(
            a.get("disk_root_pct"), fresh["dpct"], 3)
    if fresh["mt"] > 0:
        checks["mem_total_mb within 5%"] = close(
            a.get("mem_total_mb"), fresh["mt"], fresh["mt"] * 0.05)
    checks["cpu_count matches"] = a.get("cpu_count") == fresh["cpu"]
    checks["load1 within 1.0"] = close(a.get("load1"), fresh["l1"], 1.0)
    checks["mem_available <= total"] = (
        isinstance(a.get("mem_available_mb"), (int, float))
        and isinstance(a.get("mem_total_mb"), (int, float))
        and 0 <= a["mem_available_mb"] <= a["mem_total_mb"] * 1.01)
    checks["failed_units is list"] = isinstance(
        a.get("failed_units"), list)
    checks["uptime sane"] = (
        isinstance(a.get("uptime_seconds"), (int, float))
        and 0 <= a["uptime_seconds"] <= max(fresh["up"] * 1.2 + 60, 300))

    verdict = "pass" if all(v is True for v in checks.values()) \
        else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": env.get("artifact", {}).get("path", "?")}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1
                            else os.getcwd()), indent=1))
