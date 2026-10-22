#!/usr/bin/env bash
# ada-nest-lastseen — fleet-side reader for member-device heartbeats.
# Prints each beating host, last-seen age, tailnet IP, and key health fields.
# Usage: ada-nest-lastseen.sh
set -euo pipefail
MDDB_URL="${MDDB_URL:-http://100.102.134.91:11026/v1}" exec python3 - <<'PY'
import json, urllib.request, datetime, os
mddb = os.environ.get("MDDB_URL", "http://100.102.134.91:11026/v1")
req = urllib.request.Request(
    mddb + "/search",
    data=json.dumps({"collection": "ada-nest-heartbeats", "query": "", "limit": 100}).encode(),
    headers={"content-type": "application/json"}, method="POST")
docs = json.loads(urllib.request.urlopen(req, timeout=15).read()) or []
now = datetime.datetime.now(datetime.timezone.utc)
if not docs:
    print("no heartbeat documents in ada-nest-heartbeats")
for d in docs:
    try:
        b = json.loads(d.get("contentMd", "{}"))
    except Exception:
        print(f"{d.get('key','?'):20} UNPARSEABLE contentMd — check heartbeat script")
        continue
    ts = b.get("ts", "")
    try:
        age = int((now - datetime.datetime.fromisoformat(
            ts.replace("Z", "+00:00"))).total_seconds())
        ago = f"{age//60}m{age%60:02d}s"
        stale = "STALE" if age > 900 else "live"
    except Exception:
        ago, stale = "?", "?"
    host = b.get("host", "?")
    tail = b.get("tailnet_ip") or "-"
    lan = b.get("lan_ip") or "-"
    jobs = b.get("tmux_jobs") or "-"
    print(f"{host:20} {stale:5} last-seen {ago:>7} | ts {ts} | "
          f"tail {tail:16} lan {lan:15} | "
          f"ollama={b.get('ollama_ok')} jobs={jobs} "
          f"disk={b.get('disk_free_gb')}G")
PY
