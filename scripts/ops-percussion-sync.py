#!/usr/bin/env python3
"""ops-percussion-sync — state feed for /apps/percussion (Nest sonify).

Writes stacks/web/public/apps/percussion/state.json from the live ops
artifacts on tony-dell (runs there via ops-percussion.timer):

  reports/host-loads/host-loads.yml   per-host load/mem/disk (30s fresh)
  ~/var/chaba/health/*-mcp-health.json  service scores per host

Mapping contract (the page obeys this):
  bpm    = 60 + min(total_load1m*4 + failing_services*2, 70)  → 60-130
  hosts  = role by fleet weight + state from live metrics
  alerts = failing service names + unreachable hosts
Deterministic only — no LLM, no API keys. Degrades to a quiet groove.
"""
import json
import time
from pathlib import Path

import yaml

REPO = Path("/home/tony/CascadeProjects/chaba-tony-dell")
LOADS = REPO / "reports/host-loads/host-loads.yml"
HEALTH_GLOB = "/home/tony/var/chaba/health/*-mcp-health.json"
OUT = [REPO / "stacks/web/public/apps/percussion/state.json"]

# host → drum voice (heavier host = heavier drum)
HOST_ROLES = {"idc03": "kick", "idc01": "kick", "idc02": "kick",
              "tony_dell": "snare", "tony-dell": "snare",
              "tony_omen": "tom", "tony-omen": "tom",
              "mn01": "hat", "michael_ha": "shaker", "michael-ha": "shaker",
              "tony_ha": "shaker", "macbook": "shaker", "kk_ipad": "shaker"}


def host_state(h):
    """live metrics → healthy|degraded|error|unknown."""
    if h.get("unreachable"):
        return "unknown"
    load = float((h.get("load") or {}).get("1m") or 0)
    disk = int(h.get("disk_pct") or 0)
    mem_t = int(h.get("mem_total_mb") or 0)
    mem_a = int(h.get("mem_avail_mb") or 0)
    mem_low = mem_t > 0 and mem_a / mem_t < 0.08
    if load > 12 or disk > 92 or mem_low:
        return "error"
    if load > 5 or disk > 85:
        return "degraded"
    return "healthy"


def main():
    try:
        loads = yaml.safe_load(open(LOADS)) or {}
    except OSError:
        loads = {}
    raw_hosts = loads.get("hosts") or []

    failing = []
    import glob
    for f in glob.glob(HEALTH_GLOB):
        try:
            d = json.load(open(f))
            for s in d.get("service_scores") or []:
                if s.get("status") not in (None, "healthy"):
                    failing.append(s.get("service") or "?")
        except Exception:
            continue

    hosts, total_load = {}, 0.0
    for h in raw_hosts:
        name = str(h.get("host") or "").strip()
        if not name:
            continue
        role = HOST_ROLES.get(name) or HOST_ROLES.get(
            name.replace("-", "_")) or "shaker"
        st = host_state(h)
        total_load += float((h.get("load") or {}).get("1m") or 0)
        hosts[name.replace("-", "_")] = {
            "role": role, "state": st,
            "load": round(float((h.get("load") or {}).get("1m") or 0), 2),
            "disk": h.get("disk_pct")}

    unreachable = [n for n, h in hosts.items() if h["state"] == "unknown"]
    alerts = failing + [f"{n} unreachable" for n in unreachable]
    bpm = int(60 + min(total_load * 3 + len(failing) * 2, 70))

    state = {"ts": int(time.time()), "bpm": bpm,
             "failing_services": len(failing),
             "summary": {"hosts": len(hosts),
                         "reachable": len(hosts) - len(unreachable),
                         "unreachable": len(unreachable)},
             "hosts": hosts, "alerts": alerts[:12]}
    for p in OUT:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(state))
        except OSError:
            pass
    print(f"percussion state: bpm={bpm} alerts={len(alerts)} "
          f"hosts={len(hosts)}")


if __name__ == "__main__":
    main()
