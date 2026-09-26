#!/usr/bin/env python3
"""Ada ops-event digest (L1.5f): containment events from MDDB.

Ada emits kind=ops-event docs (tool_storm, actuation_cap, confirm_strip,
remember_block) into the ada-ha-events collection — this aggregates them
into counts per type/day. Same query shape as render-report-feed.py;
network read with hard timeout — returns empty when MDDB is down so the
digest still renders. Personal-tier data.

Usage:
  ops-report.py [--hours 72]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

MDDB_URL = os.environ.get("MDDB_BASE_URL",
                          "http://100.74.146.0:11023/v1").rstrip("/")
OPS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
DEFAULT_OUT = Path.home() / ".local/share/ada-review"

SEVERE = {"tool_storm", "actuation_cap", "confirm_strip"}


def fetch_events(hours: int, limit: int = 200) -> list[dict]:
    payload = json.dumps({
        "collection": OPS_COLLECTION,
        "filterMeta": {"kind": ["ops-event"]},
        "limit": limit,
    }).encode()
    try:
        req = urllib.request.Request(
            f"{MDDB_URL}/search", data=payload,
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            docs = json.loads(resp.read())
    except Exception as e:
        print(f"warn: mddb unreachable: {e}", file=sys.stderr)
        return []
    if not isinstance(docs, list):
        return []
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours))
    out = []
    for d in docs:
        meta = d.get("meta") or {}
        ts = (meta.get("ts") or [""])[0]
        try:
            dt = datetime.datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            if dt < cutoff:
                continue
        except Exception:
            pass
        out.append({"ts": ts,
                    "type": (meta.get("type") or ["?"])[0],
                    "tool": (meta.get("tool") or [""])[0],
                    "text": (d.get("contentMd") or "").splitlines()[:1]})
    return out


def ops_events_block(rows: list[dict], since: str) -> str:
    if not rows:
        return f"## ada-ops ({since})\nno containment events"
    counts = Counter(r["type"] for r in rows)
    tools = Counter(r["tool"] for r in rows if r["tool"])
    flagged = sum(counts[t] for t in SEVERE)
    lines = [f"## ada-ops ({since} — {len(rows)} events"
             + (f", {flagged} flagged ⚠" if flagged else "") + ")"]
    lines.append("counts: " + ", ".join(
        f"{t} x{c}" for t, c in counts.most_common()))
    if tools:
        lines.append("tools: " + ", ".join(
            f"{t} x{c}" for t, c in tools.most_common(5)))
    for r in sorted(rows, key=lambda r: r["ts"])[-8:]:
        lines.append(f"- {r['ts'][:16]} {r['type']}"
                     + (f" [{r['tool']}]" if r["tool"] else "")
                     + (f" — {r['text'][0][:90]}" if r["text"] else ""))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = fetch_events(args.hours)
    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "ada-ops-events.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} events -> {ops}")
    print(ops_events_block(rows, f"{args.hours}h"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
