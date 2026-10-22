#!/usr/bin/env bash
# ada-nest-lastseen — fleet-side reader for member-device heartbeats.
# Prints each beating host, last-seen age, tailnet IP, and key health fields.
# Usage: ada-nest-lastseen.sh [--json]
set -euo pipefail
MDDB_URL="${MDDB_URL:-http://100.102.134.91:11026/v1}"
curl -s -m 15 -X POST "$MDDB_URL/search" -H "content-type: application/json" \
  -d '{"collection":"ada-nest-heartbeats","query":"","limit":100}' \
| python3 -c '
import json,sys,datetime
docs = json.load(sys.stdin)
now = datetime.datetime.now(datetime.timezone.utc)
for d in docs or []:
    try:
        b = json.loads(d.get("contentMd","{}"))
    except Exception:
        continue
    ts = b.get("ts","")
    try:
        age = int((now - datetime.datetime.fromisoformat(
            ts.replace("Z","+00:00"))).total_seconds())
        ago = f"{age//60}m{age%60:02d}s"
        stale = "STALE" if age > 900 else "live"
    except Exception:
        ago, stale = "?", "?"
    print(f"{b.get(\"host\",\"?\"):12} {stale:5} last-seen {ago:>7} | ts {ts} | "
          f"tail {b.get(\"tailnet_ip\") or \"-\":16} lan {b.get(\"lan_ip\") or \"-\":15} | "
          f"ollama={b.get(\"ollama_ok\")} jobs={b.get(\"tmux_jobs\") or \"-\"} "
          f"disk={b.get(\"disk_free_gb\")}G")
'
