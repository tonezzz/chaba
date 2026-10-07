#!/usr/bin/env python3
"""ops-digest — deterministic ops digest for the OpenClaw nightly cron.

No LLM involved: pulls ada-ha ops events for the last 24h straight from
MDDB (/v1/search, kind=ops-event), counts by type, lists flagged ones,
prints <=14 lines on stdout. The cron job announces stdout to Telegram.

Env overrides: MDDB_BASE_URL, ADA_OPS_COLLECTION, OPS_WINDOW_H.
Exit 0 always — a fetch failure still prints an honest line.
"""
import collections
import datetime
import glob
import json
import os
import re
import subprocess
import urllib.request

SNAP_LOG = os.environ.get(
    "MCP_HEALTH_SNAP_LOG",
    "/home/tony/CascadeProjects/chaba-tony-dell/logs/mcp-health-snapshot.log")
LINT = "/home/tony/CascadeProjects/chaba/scripts/monitor-coverage-lint.py"

MDDB_URL = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1"
).rstrip("/")
COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
WINDOW_H = int(os.environ.get("OPS_WINDOW_H", "24"))
FLAGGED = {"tool_storm", "actuation_cap", "confirm_strip", "voiceprint_drift",
           "embed_queue_saturated", "embed_queue_drops"}


def fetch() -> list[dict]:
    payload = json.dumps({
        "collection": COLLECTION,
        "filterMeta": {"kind": ["ops-event"]},
        "limit": 100,
    }).encode()
    req = urllib.request.Request(
        f"{MDDB_URL}/search", data=payload,
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        docs = json.loads(resp.read())
    return docs if isinstance(docs, list) else []


def main() -> int:
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=WINDOW_H)
    health = health_section(now)
    try:
        docs = fetch()
    except Exception as exc:
        print(f"Chaba digest {now:%Y-%m-%d}: mddb unreachable — {exc}")
        for line in health:
            print(line)
        return 0

    counts: collections.Counter = collections.Counter()
    tools: collections.Counter = collections.Counter()
    flagged: list[str] = []
    for d in docs:
        meta = d.get("meta") or {}
        ts = (meta.get("ts") or [""])[0]
        try:
            dt = datetime.datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if dt < cutoff:
                continue
        except ValueError:
            pass
        ev = (meta.get("type") or ["?"])[0]
        tool = (meta.get("tool") or [""])[0]
        counts[ev] += 1
        if tool:
            tools[tool] += 1
        if ev in FLAGGED:
            line = f"{ts[:16].replace('T',' ')} {ev}"
            if tool:
                line += f" [{tool}]"
            flagged.append(line)

    total = sum(counts.values())
    if not total:
        print(f"Chaba digest {now:%Y-%m-%d}: all quiet — no ops events in {WINDOW_H}h.")
    else:
        print(f"Chaba digest {now:%Y-%m-%d} — {total} ops events, {len(flagged)} flagged")
        print("counts: " + ", ".join(f"{k} x{v}" for k, v in counts.most_common(6)))
        if tools:
            print("tools: " + ", ".join(f"{k} x{v}" for k, v in tools.most_common(5)))
        for line in flagged[:8]:
            print(f"- {line}")
    for line in health:
        print(line)
    return 0


def health_section(now) -> list[str]:
    """Merge host-health signal: latest snapshot summary + staleness +
    coverage-lint gap count. Deterministic, local reads only."""
    out = []
    # probe staleness self-check first — a dead monitor is the worst miss
    try:
        age_min = (now.timestamp() - os.path.getmtime(SNAP_LOG)) / 60
        if age_min > 30:
            out.append(f"⚠ health probe STALE — last snapshot {age_min:.0f}min ago")
    except OSError:
        out.append("⚠ health probe missing — no snapshot log")
    else:
        try:
            tail = open(SNAP_LOG).readlines()[-200:]
            summ = next((l for l in reversed(tail) if "summary total=" in l), "")
            fail = next((l for l in reversed(tail) if "failing services:" in l), "")
            if summ:
                m = re.search(
                    r"total=(\d+) healthy=(\d+) degraded=(\d+) error=(\d+) unknown=(\d+)",
                    summ)
                if m:
                    t, h, d, e, u = map(int, m.groups())
                    line = f"health: {h}/{t} green"
                    if e or u:
                        line += f" — {e} error, {u} unknown"
                        names = fail.split("failing services:", 1)[-1].strip()
                        if names:
                            line += f" ({names[:120]})"
                    out.append(line)
        except OSError:
            pass
    try:
        r = subprocess.run(
            ["python3", LINT], capture_output=True, text=True, timeout=60)
        m = re.search(r"uncovered: (\d+)", r.stdout)
        if m and int(m.group(1)):
            out.append(f"coverage: {m.group(1)} live services with no check")
    except Exception:
        pass
    return out


if __name__ == "__main__":
    raise SystemExit(main())
