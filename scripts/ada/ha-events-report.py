#!/usr/bin/env python3
"""HA logbook digest (L1.5g): what actually happened at home.

Reads the Home Assistant logbook REST API per instance (no ssh needed) —
aggregates entries by domain + entity so the digest answers "what ran /
changed" instead of ha-report.py's "what errored". Personal-tier data.

Usage:
  ha-events-report.py [--hours 24]
Env per instance: HA_<NAME>_URL, HA_<NAME>_TOKEN — or token env files
  listed in TOKENS below. Missing/unreachable instances are skipped.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

DEFAULT_OUT = Path.home() / ".local/share/ada-review"

# instance -> (base url, env vars tried in order, token env file)
INSTANCES = {
    "tony-ha": ("https://tony-dell.taila0626a.ts.net:8123",
                ("HASS_TOKEN", "HA_LONG_LIVED_TOKEN"),
                "~/.config/secrets/home-assistant-token.env"),
    "michael-dev": ("https://tony-dell.taila0626a.ts.net:8124",
                    ("HASS_TOKEN", "HA_LONG_LIVED_TOKEN"),
                    "~/.config/secrets/ha-michael-dev.env"),
    "michael-ha": ("http://100.80.105.88:8123",
                   ("HASS_TOKEN", "HA_LONG_LIVED_TOKEN"),
                   "~/.local/share/home-assistant-michael/ha-token"),
}

# domains worth surfacing in the digest; the rest collapse into "other"
WATCH_DOMAINS = {"automation", "script", "person", "binary_sensor",
                 "lock", "alarm_control_panel", "device_tracker",
                 "media_player", "climate"}


def _token(env_vars: tuple, env_file: str) -> str | None:
    for v in env_vars:
        if os.environ.get(v):
            return os.environ[v]
    p = Path(env_file).expanduser()
    if not p.exists():
        return None
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        for v in env_vars:
            if ln.startswith(v + "="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    t = p.read_text().strip()  # bare-token file (ha-token)
    return t if t and "=" not in t else None


def fetch_logbook(url: str, token: str | None, hours: int) -> list[dict]:
    if not token:
        print(f"warn: {url}: no token", file=sys.stderr)
        return []
    start = (datetime.datetime.now() - datetime.timedelta(hours=hours)
             ).strftime("%Y-%m-%dT%H:%M:%S")
    req = urllib.request.Request(
        f"{url}/api/logbook/{urllib.parse.quote(start)}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        import ssl
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            docs = json.loads(resp.read())
    except Exception as e:
        print(f"warn: {url}: {e}", file=sys.stderr)
        return []
    return docs if isinstance(docs, list) else []


def summarize(entries: list[dict]) -> dict:
    domains: Counter = Counter()
    entities: Counter = Counter()
    for e in entries:
        dom = e.get("domain") or "?"
        if dom not in WATCH_DOMAINS:
            dom = "other"
        domains[dom] += 1
        entities[(e.get("name") or e.get("entity_id") or "?")[:40]] += 1
    return {"total": len(entries), "domains": dict(domains.most_common()),
            "top_entities": dict(entities.most_common(8))}


def ha_events_block(rows: list[dict], since: str) -> str:
    if not rows:
        return f"## ha-events ({since})\nno instances reachable"
    lines = [f"## ha-events ({since})"]
    for r in rows:
        lines.append(f"{r['instance']}: {r['total']} logbook entries — "
                     + ", ".join(f"{k} {v}" for k, v in
                                 list(r["domains"].items())[:6]))
        for name, c in list(r["top_entities"].items())[:4]:
            lines.append(f"  {name} x{c}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = []
    for inst, (url, env_var, env_file) in INSTANCES.items():
        entries = fetch_logbook(url, _token(env_var, env_file), args.hours)
        if entries:
            rows.append({"instance": inst, **summarize(entries)})

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "ha-events-ops.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} instances -> {ops}")
    print(ha_events_block(rows, f"{args.hours}h"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
