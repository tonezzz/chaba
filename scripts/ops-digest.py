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
import json
import os
import urllib.request

MDDB_URL = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1"
).rstrip("/")
COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
WINDOW_H = int(os.environ.get("OPS_WINDOW_H", "24"))
FLAGGED = {"tool_storm", "actuation_cap", "confirm_strip", "voiceprint_drift"}


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
    try:
        docs = fetch()
    except Exception as exc:
        print(f"Chaba digest {now:%Y-%m-%d}: mddb unreachable — {exc}")
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
        return 0

    print(f"Chaba digest {now:%Y-%m-%d} — {total} ops events, {len(flagged)} flagged")
    print("counts: " + ", ".join(f"{k} x{v}" for k, v in counts.most_common(6)))
    if tools:
        print("tools: " + ", ".join(f"{k} x{v}" for k, v in tools.most_common(5)))
    for line in flagged[:8]:
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
