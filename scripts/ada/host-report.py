#!/usr/bin/env python3
"""Host health sweep (L1.5b): per-host ops facts from journald + systemctl.

Same mechanical pattern as journal-report.py but host-scoped instead of
Ada-session-scoped: unit restarts, error-level lines, OOM/kill events,
failed/inactive units and timers, disk pressure. No LLM.

Usage:
  host-report.py --hosts idc01,mn01,tony-dell --since "24 hours ago"
  host-report.py                          # all default hosts
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
DEFAULT_HOSTS = ["idc01", "mn01", "tony-dell", "tony-omen"]
LOCAL_NAMES = {"tony-omen", "localhost", ""}

RX_STARTED = re.compile(r"Started ([\w@.-]+\.service)")
RX_OOM = re.compile(r"oom[-_ ]?kill|Out of memory|Killed process", re.I)
RX_UNIT_FAIL = re.compile(r"([\w@.-]+\.service): (Failed|Main process exited)")
RX_PANIC = re.compile(r"panick|refused by the vector index|"
                      r"vector index loaded", re.I)
RX_OOM_UNIT = re.compile(r"([\w@.-]+\.service): A process of this unit "
                         r"has been killed by the OOM killer", re.I)


def _run(cmd: list[str], timeout: int = 60) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout)
        return out.stdout
    except Exception:
        return ""


def _ssh(host: str, remote: str, timeout: int = 60) -> str:
    if host in LOCAL_NAMES:
        return _run(["bash", "-c", remote], timeout)
    return _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 host, remote], timeout)


def _reachable(host: str) -> bool:
    """Fast probe — tailscale ssh can hang for minutes on the re-auth
    prompt instead of failing under BatchMode."""
    if host in LOCAL_NAMES:
        return True
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
         "true"], capture_output=True, timeout=15)
    return r.returncode == 0


def sweep_host(host: str, since: str) -> dict:
    if not _reachable(host):
        raise RuntimeError("host unreachable (ssh probe failed)")
    # Filter server-side — unfiltered user journals can exceed 200k lines
    # in 48h, which times out over ssh.
    journal = _ssh(
        host,
        "journalctl --user --since '" + since + "' --no-pager -o cat "
        "2>/dev/null | grep -iE 'Started|Stopped|Failed|error|oom|killed"
        "|panic|vector index' | head -20000; "
        "journalctl --since '" + since + "' --no-pager -o cat "
        "2>/dev/null | grep -vE 'pam_|session opened|session closed' | "
        "grep -iE 'Started|Failed|error|oom|killed' | head -4000",
        timeout=180,
    ).splitlines()

    restarts: Counter = Counter()
    errors: Counter = Counter()
    oom = 0
    oom_units: Counter = Counter()
    panics: Counter = Counter()
    index_events = 0
    fails: Counter = Counter()
    restart_counters: dict[str, int] = {}
    for ln in journal:
        # Skip function_call result dumps — transcript/tool-result text can
        # contain phrases like "Out of memory" and inflate signal counts.
        is_dump = "function_call result" in ln
        if (m := RX_STARTED.search(ln)):
            restarts[m.group(1)] += 1
        if (m := re.search(r"([\w@.-]+\.service): Scheduled restart job, "
                           r"restart counter is at (\d+)", ln)):
            restart_counters[m.group(1)] = max(
                restart_counters.get(m.group(1), 0), int(m.group(2)))
        if not is_dump and (" ERROR" in ln or (" error" in ln.lower()
                                              and " 0 error" not in ln)):
            key = ln.strip()[:80]
            errors[key] += 1
        if not is_dump and RX_OOM.search(ln):
            oom += 1
        if not is_dump and (m := RX_OOM_UNIT.search(ln)):
            oom_units[m.group(1)] += 1
        if not is_dump and "vector index loaded" in ln.lower():
            index_events += 1
        elif not is_dump and (m := re.search(
                r'(?:HNSW|vector)[^"]*panic|panic="([^"]+)"', ln, re.I)):
            panics["hnsw"] += 1
        if not is_dump and (m := RX_UNIT_FAIL.search(ln)):
            fails[m.group(1)] += 1

    failed_txt = _ssh(host, "systemctl --user --failed --no-legend "
                            "2>/dev/null | awk '{print $2}'")
    failed_units = [u.strip() for u in failed_txt.splitlines() if u.strip()]

    disk = _ssh(host, "df -h / | tail -1").split()
    disk_use = disk[4] if len(disk) >= 5 else None

    return {
        "host": host, "restarts": dict(restarts),
        "restart_total": sum(restarts.values()),
        "restart_counters": restart_counters,
        "error_lines": sum(errors.values()),
        "top_errors": dict(errors.most_common(5)),
        "oom_kills": oom, "oom_units": dict(oom_units),
        "panics": sum(panics.values()),
        "index_rebuilds": index_events,
        "unit_failures": dict(fails),
        "failed_units": failed_units, "disk_use": disk_use,
    }


def hosts_block(rows: list[dict], since: str) -> str:
    lines = [f"## hosts ({since} — {len(rows)} hosts)"]
    for r in rows:
        flag = ""
        if (r["oom_kills"] or r["failed_units"] or r["unit_failures"]
                or r.get("panics") or r.get("oom_units")):
            flag = " ⚠"
        lines.append(
            f"{r['host']}: restarts {r['restart_total']}, err-lines "
            f"{r['error_lines']}, oom {r['oom_kills']}, failed-units "
            f"{len(r['failed_units'])}, disk {r['disk_use'] or '?'}{flag}")
        if r.get("panics"):
            lines.append(f"  vector-panics x{r['panics']}")
        if r.get("index_rebuilds"):
            lines.append(f"  index-rebuilds x{r['index_rebuilds']}")
        for u, c in sorted(r.get("oom_units", {}).items()):
            lines.append(f"  oom-killed {u} x{c}")
        for u, c in sorted(r["unit_failures"].items(),
                           key=lambda kv: -kv[1])[:6]:
            lines.append(f"  unit-fail {u} x{c}")
        if len(r["unit_failures"]) > 6:
            lines.append(f"  …({len(r['unit_failures']) - 6} more units)")
        for u, c in sorted(r.get("restart_counters", {}).items()):
            if c >= 5:
                lines.append(f"  restart-loop {u} counter={c}")
        for u in r["failed_units"][:4]:
            lines.append(f"  failed: {u}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--hosts", default=",".join(DEFAULT_HOSTS))
    ap.add_argument("--since", default="24 hours ago")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    rows = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=min(4, len(hosts))) as pool:
        futs = {pool.submit(sweep_host, h, args.since): h for h in hosts}
        for fut in as_completed(futs):
            h = futs[fut]
            try:
                rows.append(fut.result())
            except Exception as e:
                print(f"warn: {h}: {e}", file=sys.stderr)
                rows.append({"host": h, "restarts": {}, "restart_total": 0,
                             "error_lines": -1, "top_errors": {},
                             "oom_kills": -1, "unit_failures": {},
                             "failed_units": ["unreachable"],
                             "disk_use": None})
    rows.sort(key=lambda r: hosts.index(r["host"]))

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "host-ops.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} hosts -> {ops}")
    print(hosts_block(rows, args.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
