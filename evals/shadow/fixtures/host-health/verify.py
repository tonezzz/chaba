#!/usr/bin/env python3
"""Held-out verifier for host-health. Re-collects host facts and compares
the artifact against reality within tolerance. Never trusts the arm."""
import json
import os
import re
import subprocess
import sys


def _fresh():
    l1 = l5 = l15 = 0.0
    try:
        with open("/proc/loadavg") as f:
            p = f.read().split()
        l1, l5, l15 = float(p[0]), float(p[1]), float(p[2])
    except Exception:
        pass
    mt = ma = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mt = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    ma = int(line.split()[1]) // 1024
    except Exception:
        pass
    try:
        out = subprocess.run(["df", "-P", "/"], capture_output=True,
                             text=True, timeout=15).stdout.splitlines()
        dpct = int(out[-1].split()[4].rstrip("%"))
    except Exception:
        dpct = -1
    return {"host": os.uname().nodename, "cpu": os.cpu_count() or 1,
            "mt": mt, "ma": ma, "dpct": dpct, "l1": l1}


def verify(task_dir):
    path = os.path.join(task_dir, "evals/shadow/task/artifacts/health.json")
    checks = {}
    try:
        with open(path) as f:
            a = json.load(f)
    except Exception as e:
        return {"verdict": "fail", "checks": {"artifact readable": False,
                                              "error": str(e)}}
    fresh = _fresh()
    req = ["host", "collected_at", "uptime_seconds", "load1", "load5",
           "load15", "cpu_count", "mem_total_mb", "mem_available_mb",
           "disk_root_pct", "failed_units", "read_only"]
    checks["required fields present"] = all(k in a for k in req)
    checks["host matches reality"] = a.get("host") == fresh["host"]
    checks["cpu_count matches"] = a.get("cpu_count") == fresh["cpu"]
    checks["loads >= 0"] = all(
        isinstance(a.get(k), (int, float)) and a[k] >= 0
        for k in ("load1", "load5", "load15"))
    checks["uptime >= 0"] = isinstance(
        a.get("uptime_seconds"), (int, float)) and a["uptime_seconds"] >= 0
    checks["mem sane"] = (isinstance(a.get("mem_total_mb"), int)
                          and a["mem_total_mb"] > 0
                          and isinstance(a.get("mem_available_mb"), int)
                          and 0 <= a["mem_available_mb"] <= a["mem_total_mb"])
    checks["mem_total within 5% of fresh"] = (
        fresh["mt"] == 0
        or abs(a.get("mem_total_mb", -1) - fresh["mt"]) / fresh["mt"] <= 0.05)
    checks["disk_root_pct 0..100"] = (
        isinstance(a.get("disk_root_pct"), int)
        and 0 <= a["disk_root_pct"] <= 100)
    checks["disk_root_pct within 3 of fresh"] = (
        fresh["dpct"] < 0 or abs(a.get("disk_root_pct", -100)
                                 - fresh["dpct"]) <= 3)
    checks["failed_units is list"] = isinstance(a.get("failed_units"), list)
    checks["read_only true"] = a.get("read_only") is True
    verdict = "pass" if all(v is True for v in checks.values()) else "fail"
    return {"verdict": verdict, "checks": checks, "artifact": "health.json"}


if __name__ == "__main__":
    td = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(verify(td), indent=1))
