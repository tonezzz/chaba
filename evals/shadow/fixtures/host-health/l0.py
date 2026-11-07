#!/usr/bin/env python3
"""L0 deterministic solver for the host-health fixture.

Reads only /proc, df, systemctl list-units --failed. Writes the artifact
into evals/shadow/task/artifacts/health.json inside the task dir passed
as argv[1] (default: cwd)."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


def _loadavg():
    try:
        with open("/proc/loadavg") as f:
            p = f.read().split()
        return float(p[0]), float(p[1]), float(p[2])
    except Exception:
        out = os.getloadavg()
        return out[0], out[1], out[2]


def _meminfo():
    total = avail = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
    except Exception:
        pass
    return total, avail


def _disk_root_pct():
    try:
        out = subprocess.run(["df", "-P", "/"], capture_output=True,
                             text=True, timeout=15).stdout.splitlines()
        use = out[-1].split()[4]
        return int(use.rstrip("%"))
    except Exception:
        st = os.statvfs("/")
        return int(round(100 * (st.f_blocks - st.f_bfree) / st.f_blocks))


def _failed_units():
    units = set()
    for args in (["systemctl", "--user", "list-units", "--failed",
                  "--no-legend", "--no-pager"],
                 ["systemctl", "list-units", "--failed",
                  "--no-legend", "--no-pager"]):
        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               timeout=15)
            for line in r.stdout.splitlines():
                m = re.match(r"\s*([^\s]+\.service|[^\s]+\.timer|[^\s]+\.\w+)",
                             line)
                if m and m.group(1).endswith(
                        (".service", ".timer", ".socket", ".mount",
                         ".target", ".path", ".scope")):
                    units.add(m.group(1))
        except Exception:
            continue
    return sorted(units)


def main():
    task_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    l1, l5, l15 = _loadavg()
    mt, ma = _meminfo()
    art = {
        "host": os.uname().nodename,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": float(open("/proc/uptime").read().split()[0])
        if os.path.exists("/proc/uptime") else 0.0,
        "load1": l1, "load5": l5, "load15": l15,
        "cpu_count": os.cpu_count() or 1,
        "mem_total_mb": mt, "mem_available_mb": ma,
        "disk_root_pct": _disk_root_pct(),
        "failed_units": _failed_units(),
        "read_only": True,
    }
    out = os.path.join(task_dir, "evals/shadow/task/artifacts")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "health.json"), "w") as f:
        json.dump(art, f, indent=1)
    print(json.dumps({"wrote": out + "/health.json"}))


if __name__ == "__main__":
    main()
