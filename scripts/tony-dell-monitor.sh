#!/usr/bin/env bash
# tony-dell 24/7 cross-host monitoring — Phase 1 observe-only.
# Logs one JSON line per check to ~/var/chaba/health/tony-dell-monitor.log.

set -uo pipefail

LOG_DIR="$HOME/var/chaba/health"
LOG_FILE="$LOG_DIR/tony-dell-monitor.log"
TS=$(LC_ALL=C date -u '+%Y-%m-%dT%H:%M:%SZ')

mkdir -p "$LOG_DIR"

# Resolve tony-omen over the tailnet (falls back to a hard IP if tailscale is broken)
TONY_OMEN_IP=$(tailscale ip -4 tony-omen 2>/dev/null || true)
if [[ -z "$TONY_OMEN_IP" ]]; then
    TONY_OMEN_IP="100.75.102.88"
fi

# Local tony-dell Funnel endpoint
TONY_DELL_IP=$(tailscale ip -4 tony-dell 2>/dev/null || true)
if [[ -z "$TONY_DELL_IP" ]]; then
    TONY_DELL_IP="127.0.0.1"
fi

python3 - "$LOG_FILE" "$TS" "$TONY_OMEN_IP" "$TONY_DELL_IP" <<'PY'
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

LOG_FILE, TS, TONY_OMEN_IP, TONY_DELL_IP = sys.argv[1:5]


def curl_check(url, method="GET", expect=200, timeout=5):
    out = {"url": url, "http_code": 0, "response_time_ms": None, "status": "unknown", "detail": ""}
    try:
        proc = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{time_total}", "--max-time", str(timeout), "-X", method, url],
            capture_output=True, text=True, timeout=timeout + 2
        )
        if proc.returncode != 0:
            out["status"] = "error"
            out["detail"] = f"curl exit {proc.returncode}"
            return out
        parts = proc.stdout.strip().split(None, 1)
        code = int(parts[0]) if parts and parts[0].isdigit() else 0
        time_s = float(parts[1]) if len(parts) > 1 and parts[1].replace(".", "", 1).isdigit() else None
        out["http_code"] = code
        out["response_time_ms"] = round(time_s * 1000, 1) if time_s is not None else None
        if code == expect:
            out["status"] = "healthy"
        elif code == 0:
            out["status"] = "error"
            out["detail"] = "no response"
        else:
            out["status"] = "degraded"
            out["detail"] = f"unexpected http {code}"
    except Exception as e:
        out["status"] = "error"
        out["detail"] = str(e)
    return out


def process_check(name, cmd, expected_pattern=None):
    out = {"cmd": " ".join(cmd), "status": "unknown", "detail": ""}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out["rc"] = proc.returncode
        if proc.returncode != 0:
            out["status"] = "error"
            out["detail"] = proc.stderr.strip() or "process check failed"
            return out
        if expected_pattern and not re.search(expected_pattern, proc.stdout):
            out["status"] = "degraded"
            out["detail"] = f"output did not match /{expected_pattern}/"
            return out
        out["status"] = "healthy"
        out["detail"] = proc.stdout.strip()[:120]
    except Exception as e:
        out["status"] = "error"
        out["detail"] = str(e)
    return out


results = []

# tony-omen HTTP endpoints
remote_endpoints = {
    "caddy": f"http://{TONY_OMEN_IP}:8080/",
    "status-api": f"http://{TONY_OMEN_IP}:8080/health",
    "yomi-api": f"http://{TONY_OMEN_IP}:8080/api/yomi/health",
    "mddb-api": f"http://{TONY_OMEN_IP}:11023/health",
    "weaviate": f"http://{TONY_OMEN_IP}:8080/api/weaviate/v1/nodes",
    "llama-server": f"http://{TONY_OMEN_IP}:8008/health",
    "imagen2": f"http://{TONY_OMEN_IP}:8000/health",
    "gpu-queue": f"http://{TONY_OMEN_IP}:3001/health",
    "playlived": f"http://{TONY_OMEN_IP}:9230/sessions",
}

for name, url in remote_endpoints.items():
    res = curl_check(url)
    res["timestamp"] = TS
    res["source"] = "tony-omen"
    res["service"] = name
    res["action"] = "log"
    results.append(res)

# tony-dell local checks
local_http = {
    "funnel-landing": f"http://{TONY_DELL_IP}:8082/",
}
for name, url in local_http.items():
    res = curl_check(url)
    res["timestamp"] = TS
    res["source"] = "tony-dell"
    res["service"] = name
    res["action"] = "log"
    results.append(res)

res = process_check("barrier-client", ["pgrep", "-a", "barrierc"], r"barrierc")
res["timestamp"] = TS
res["source"] = "tony-dell"
res["service"] = "barrier-client"
res["action"] = "log"
res["url"] = ""
results.append(res)

# Write results and rotate to last 10000 lines
lines = []
if os.path.exists(LOG_FILE):
    with open(LOG_FILE) as f:
        lines = [l.rstrip("\n") for l in f if l.strip()][-10000:]

with open(LOG_FILE, "w") as f:
    for l in lines:
        f.write(l + "\n")
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

# Last line to stdout for journal/systemd
print(json.dumps({"timestamp": TS, "checks": len(results), "file": LOG_FILE}, ensure_ascii=False))
PY
