#!/usr/bin/env python3
"""L1.5c — Home Assistant log report.

The journal layer (journal-report.py) sees what Ada's runtime did; the host
layer (host-report.py) sees systemd health. This layer sees the HOME:
per-integration error counts, entity-unavailable events, and automation
failures from the HA container logs — the signals behind user-visible
"X is unavailable" complaints that never reach a transcript.

Mechanical pass over `podman logs <container>`, no LLM.

Usage:
  ha-report.py --since "48 hours ago"          # all HA hosts
  ha-report.py --hosts tony-dell               # subset
"""
import argparse
import json
import re
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

REVIEW_DIR = Path.home() / ".local/share/ada-review"
OUT = REVIEW_DIR / "ha-ops.jsonl"

# host -> podman containers holding a HA instance
HA_HOSTS = {
    "tony-dell": ["tony-ha", "michael-dev"],
}

RX_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})")
# 2026-09-25 08:12:33.123 ERROR (MainThread) [homeassistant.components.zha] msg
RX_LEVEL = re.compile(
    r"\b(ERROR|WARNING) \(.*?\) \[([^\]]+)\] (.*)")
RX_LOGGER = re.compile(
    r"(?:homeassistant\.components|custom_components)\.([a-z0-9_]+)")
RX_UNAVAIL = re.compile(r"became unavailable|is unavailable|unavailable", re.I)
RX_AUTOMATION = re.compile(
    r"automation\.[a-z0-9_]+.*(?:error|failed|traceback)", re.I)
RX_ENTITY = re.compile(
    r"\b((?:sensor|binary_sensor|switch|light|climate|media_player|cover|"
    r"lock|fan|number|select|input_\w+|automation|script|device_tracker|"
    r"person|zone|weather|update|sun)\.[a-z0-9_]+)\b")


# host -> (container, config dir holding home-assistant.log[.1])
HA_HOSTS = {
    "tony-dell": [
        ("tony-ha", "~/.config/home-assistant"),
        ("michael-dev", "~/.config/michael-dev"),
    ],
}


def _cutoff(since: str) -> str | None:
    """"48 hours ago" -> 'YYYY-MM-DD HH:MM' cutoff for line filtering."""
    import datetime
    m = re.match(r"(\d+)\s+(hour|day|minute)s?\s+ago", since)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)[0]
    delta = {"h": 3600, "d": 86400, "m": 60}[unit] * n
    return (datetime.datetime.now()
            - datetime.timedelta(seconds=delta)).strftime("%Y-%m-%d %H:%M")


def fetch(host: str, cfgdir: str, since: str) -> tuple[list[str], bool]:
    """Read the persistent log files over ssh (survives container restarts),
    keep only lines at/after the --since cutoff (rotation boundaries included
    so an un-timestamped continuation line isn't dropped)."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             host,
             f"cat {cfgdir}/home-assistant.log.1 "
             f"{cfgdir}/home-assistant.log 2>/dev/null"],
            capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return [], False
    if r.returncode != 0:
        return [], False
    lines = r.stdout.splitlines()
    cutoff = _cutoff(since)
    if cutoff:
        lines = [ln for ln in lines
                 if not RX_TS.match(ln) or RX_TS.match(ln).group(1) >= cutoff]
    return lines, True


def parse(lines: list[str]) -> dict:
    errors = defaultdict(int)      # integration -> count
    warnings = defaultdict(int)
    unavail = defaultdict(int)     # entity -> count
    automation_fails = defaultdict(int)
    first = last = None
    total_err = total_warn = 0
    for ln in lines:
        ts = RX_TS.match(ln)
        if ts:
            t = ts.group(1)
            first = t if first is None or t < first else first
            last = t if last is None or t > last else last
        m = RX_LEVEL.search(ln)
        if m:
            level, logger, msg = m.groups()
            integ = (RX_LOGGER.search(logger) or RX_LOGGER.search(msg))
            name = integ.group(1) if integ else logger.split(".")[0][:40]
            if level == "ERROR":
                errors[name] += 1
                total_err += 1
            else:
                warnings[name] += 1
                total_warn += 1
        if RX_UNAVAIL.search(ln):
            em = RX_ENTITY.search(ln)
            unavail[em.group(1) if em else "(unknown)"] += 1
        if RX_AUTOMATION.search(ln):
            am = re.search(r"automation\.[a-z0-9_]+", ln)
            if am:
                automation_fails[am.group(0)] += 1
    return {
        "first": first, "last": last,
        "errors": dict(sorted(errors.items(), key=lambda x: -x[1])),
        "warnings": dict(sorted(warnings.items(), key=lambda x: -x[1])),
        "unavailable": dict(sorted(unavail.items(), key=lambda x: -x[1])),
        "automation_fails": dict(sorted(automation_fails.items(),
                                        key=lambda x: -x[1])),
        "total_errors": total_err, "total_warnings": total_warn,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="48 hours ago")
    ap.add_argument("--hosts", default=",".join(HA_HOSTS))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for host in args.hosts.split(","):
        for cont, cfgdir in HA_HOSTS.get(host, []):
            lines, ok = fetch(host, cfgdir, args.since)
            if not ok:
                rows.append({"host": host, "container": cont,
                             "reachable": False})
                print(f"{host}/{cont}: unreachable")
                continue
            p = parse(lines)
            row = {"host": host, "container": cont, "reachable": True,
                   "lines": len(lines), **p}
            rows.append(row)
            top = ", ".join(f"{k}={v}" for k, v in
                            list(p["errors"].items())[:4]) or "-"
            print(f"{host}/{cont}: {len(lines)} lines, "
                  f"err={p['total_errors']} warn={p['total_warnings']} "
                  f"unavail={sum(p['unavailable'].values())} | top: {top}")

    # JSONL: drop today's rows for the same host/container, append fresh
    keep = []
    if Path(args.out).exists():
        keep = [json.loads(l) for l in
                Path(args.out).read_text().splitlines() if l.strip()]
    live = {(r["host"], r["container"]) for r in rows}
    keep = [r for r in keep
            if (r.get("host"), r.get("container")) not in live]
    Path(args.out).write_text(
        "".join(json.dumps(r) + "\n" for r in keep + rows))
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


def ha_block(rows: list[dict], since: str) -> str:
    lines = [f"## ha ({since} — {len(rows)} instances)"]
    for r in rows:
        if not r.get("reachable"):
            lines.append(f"{r['host']}/{r['container']}: unreachable")
            continue
        flag = " ⚠" if r["total_errors"] > 50 else ""
        lines.append(
            f"{r['host']}/{r['container']}: {r.get('lines', 0)} lines, "
            f"err {r['total_errors']}, warn {r['total_warnings']}, "
            f"unavail {sum(r['unavailable'].values())}{flag}")
        for k, v in list(r["errors"].items())[:5]:
            lines.append(f"  err {k} x{v}")
        for k, v in list(r["unavailable"].items())[:4]:
            lines.append(f"  unavail {k} x{v}")
        for k, v in list(r["automation_fails"].items())[:4]:
            lines.append(f"  automation-fail {k} x{v}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
