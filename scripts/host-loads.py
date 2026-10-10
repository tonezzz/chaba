#!/usr/bin/env python3
"""Lightweight fleet load sampler — the 5-minute complement to audit-hosts.

One SSH command per host (loadavg + meminfo + df + uptime), run from
tony-dell-monitor.service (every 5 min). Writes:

  reports/host-loads/host-loads.yml      consolidated snapshot
  reports/host-loads/meta.host-loads.yml L1 meta (registry node: host-loads)

report-system.py prefers this file over the heavier 24h audit-hosts
snapshots when fresh; audit data remains the fallback.
"""
from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

from lib.report import now_iso, write_meta  # noqa: E402

HOSTS_SSOT = REPO / "docs" / "ssot" / "infrastructure" / "ssot.audit.hosts.yml"
OUT_DIR = REPO / "reports" / "host-loads"
OUT_YML = OUT_DIR / "host-loads.yml"
META = OUT_DIR / "meta.host-loads.yml"
STATE = OUT_DIR / ".prev-state.json"
SSH_TIMEOUT = 12

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")


def _ops_event(etype: str, host: str, detail: str) -> None:
    """host_down/host_up line -> ada ops digest (same shape kanban uses)."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        req = urllib.request.Request(
            f"{MDDB}/add",
            data=json.dumps({
                "collection": "ada-ha-events-tony",
                "key": f"ops-host-{etype}-{host}-{now:%Y%m%d%H%M%S}",
                "lang": "en", "contentMd": detail,
                "meta": {"kind": ["ops-event"], "type": [etype],
                         "instance": ["tony"], "host": [host],
                         "ts": [now.isoformat(timespec="seconds")],
                         "written_by": ["host-loads"]}}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"warn: ops event failed: {e}", file=sys.stderr)


def _emit_transitions(rows: list[dict]) -> None:
    """Alert only on reachability flips — a host that stays down is not
    re-alerted every 5 min; its recovery emits host_up once."""
    try:
        prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    except Exception:
        prev = {}
    now_iso_ = now_iso()
    for r in rows:
        h = r["host"]
        was_up = prev.get(h, True)          # default up: don't alert on first run
        up = not r["unreachable"]
        if was_up and not up:
            _ops_event("host_down", h,
                       f"host {h} unreachable at {now_iso_} "
                       f"(ssh probe failed, host-loads sampler)")
        elif up and not was_up:
            _ops_event("host_up", h,
                       f"host {h} reachable again at {now_iso_}")
        prev[h] = up
    try:
        STATE.write_text(json.dumps(prev))
    except Exception as e:
        print(f"warn: state write failed: {e}", file=sys.stderr)

# One probe, both OSes. Emits tagged lines the parser below consumes.
PROBE = """{
if [ -r /proc/loadavg ]; then
    awk '{print "LOAD " $1 " " $2 " " $3}' /proc/loadavg
    grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
    df -P / | tail -1
else
    sysctl -n vm.loadavg | awk '{print "LOAD " $2 " " $3 " " $4}'
    echo "MemTotal: $(( $(sysctl -n hw.memsize) / 1024 )) kB"
    top -l 1 -n 0 2>/dev/null | grep PhysMem | \\
        sed -E 's/.* ([0-9]+)[MG] unused.*/MemAvailable: \\1000000 kB/'
    df -P / | tail -1
fi
uptime | sed 's/^ *//'
} 2>/dev/null"""


def _probe_local() -> tuple[bool, str]:
    r = subprocess.run(["sh", "-c", PROBE], capture_output=True, text=True,
                       timeout=SSH_TIMEOUT)
    return r.returncode == 0, r.stdout


def _probe_ssh(host: str, ip: str | None) -> tuple[bool, str]:
    for target in (host, ip):
        if not target:
            continue
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                 target, PROBE],
                capture_output=True, text=True, timeout=SSH_TIMEOUT)
            if r.returncode == 0 and r.stdout.strip():
                return True, r.stdout
        except (subprocess.TimeoutExpired, OSError):
            continue
    return False, ""


def _parse(out: str) -> dict:
    d: dict = {}
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "LOAD" and len(parts) >= 4:
            d["load"] = {"1m": float(parts[1]), "5m": float(parts[2]),
                         "15m": float(parts[3])}
        elif parts[0] == "MemTotal:":
            d["mem_total_mb"] = int(parts[1]) // 1024
        elif parts[0] == "MemAvailable:":
            d["mem_avail_mb"] = int(parts[1]) // 1024
        elif len(parts) >= 5 and parts[0].startswith("/dev/"):
            d["disk_pct"] = int(parts[4].rstrip("%"))
    return d


def _sample(host: str, ip: str | None) -> dict:
    local = host == socket.gethostname()
    ok, out = _probe_local() if local else _probe_ssh(host, ip)
    row = {"host": host, "ts": now_iso(), "source": "live",
           "unreachable": not ok}
    if ok:
        row.update(_parse(out))
        if "mem_total_mb" in row and "mem_avail_mb" in row:
            row["mem_used_mb"] = row["mem_total_mb"] - row["mem_avail_mb"]
    return row


def main() -> int:
    hosts_doc = yaml.safe_load(HOSTS_SSOT.read_text(encoding="utf-8")) or {}
    hosts = {k: (v or {}).get("tailscale_ip")
             for k, v in (hosts_doc.get("hosts") or {}).items()
             if isinstance(v, dict)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(lambda kv: _sample(*kv), sorted(hosts.items())))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_YML.write_text(yaml.safe_dump(
        {"generated_at": now_iso(), "hosts": rows},
        sort_keys=False, allow_unicode=True), encoding="utf-8")

    ok = sum(1 for r in rows if not r["unreachable"])
    bad = [r["host"] for r in rows if r["unreachable"]]
    _emit_transitions(rows)
    write_meta(
        META, node="host-loads", layer="L1-producer",
        purpose="5-min fleet load/mem/disk sampler (via tony-dell-monitor); "
                "feeds the Host loads section of the system report",
        generated_by="scripts/host-loads.py",
        status="ok" if ok == len(rows) else ("error" if not ok else "delta"),
        summary=f"{ok}/{len(rows)} hosts sampled"
                + (f"; unreachable: {', '.join(bad)}" if bad else ""),
        sources=[str(OUT_YML)], children=[],
        extra={"unreachable_hosts": bad})
    print(f"{ok}/{len(rows)} hosts sampled -> {OUT_YML}"
          + (f" (unreachable: {', '.join(bad)})" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
