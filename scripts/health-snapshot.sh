#!/usr/bin/env bash
# Cross-platform Linux health snapshot — records LAN/WiFi and Tailscale IPs.
# Writes: ~/var/chaba/health/<hostname>-snapshot.json

set -euo pipefail

python3 - "$HOME" "$(hostname -s)" <<'PY'
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HOME = sys.argv[1]
HOST = sys.argv[2]

OUT_DIR = os.path.join(HOME, "var", "chaba", "health")
OUT_FILE = os.path.join(OUT_DIR, f"{HOST}-snapshot.json")


def run(cmd, timeout=30):
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return proc.stdout.strip(), proc.stderr.strip(), proc.returncode
    except Exception as e:
        return "", str(e), -1


def get_lan_ip():
    """Default-route interface IPv4 (not Tailscale)."""
    # Try to discover the default gateway interface
    out, _, rc = run("ip -4 route show default 2>/dev/null")
    if rc == 0:
        m = re.search(r"dev\s+(\S+)", out)
        if m:
            ifc = m.group(1)
            if ifc != "tailscale0":
                out2, _, rc2 = run(f"ip -4 addr show {ifc} 2>/dev/null")
                if rc2 == 0:
                    ip = re.search(r"inet\s+(\d+(?:\.\d+){3})", out2)
                    if ip:
                        return ip.group(1)

    # Fallback: first non-loopback, non-Tailscale 100.x, non-docker-looking private IP
    out, _, _ = run("hostname -I 2>/dev/null")
    for ip in out.split():
        if ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("100."):
            continue
        if re.match(r"^(192\.168\.|10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)", ip):
            return ip
    return ""


def get_tailscale_ip():
    out, _, rc = run("tailscale ip -4 2>/dev/null")
    if rc == 0:
        return out.split()[0] if out.strip() else ""
    return ""


def get_wifi_ssid():
    out, _, rc = run("iwgetid -r 2>/dev/null")
    if rc == 0 and out:
        return out
    out, _, _ = run("nmcli -t -f active,ssid dev wifi 2>/dev/null | grep '^yes:' | head -1")
    if out:
        return out.split(":", 1)[-1].strip()
    return ""


def get_disk():
    mounts = ("/", "/data")
    rows = []
    for mp in mounts:
        out, _, rc = run(f"df -h {mp} 2>/dev/null | tail -1")
        if rc != 0 or not out:
            continue
        parts = out.split(None, 5)
        if len(parts) < 6:
            continue
        _, size, used, avail, use_pct, target = parts
        rows.append({
            "mount": target,
            "size": size,
            "used": used,
            "available": avail,
            "use_pct": use_pct,
        })
    return rows


# Basic load / memory
loadavg, _, _ = run("awk '{print $1}' /proc/loadavg")
mem_avail = 0
with open("/proc/meminfo") as f:
    for line in f:
        if line.startswith("MemAvailable:"):
            mem_avail = int(line.split()[1]) // 1024
            break
swap_total, swap_free = 0, 0
with open("/proc/meminfo") as f:
    for line in f:
        if line.startswith("SwapTotal:"):
            swap_total = int(line.split()[1])
        if line.startswith("SwapFree:"):
            swap_free = int(line.split()[1])
swap_pct = 0 if swap_total == 0 else int((swap_total - swap_free) * 100 / swap_total)

snapshot = {
    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    "host": HOST,
    "hostname": run("hostname -f 2>/dev/null")[0],
    "lan_ip": get_lan_ip(),
    "tailscale_ip": get_tailscale_ip(),
    "wifi_ssid": get_wifi_ssid(),
    "loadavg_1m": float(loadavg) if loadavg else None,
    "mem_available_mb": mem_avail,
    "swap_used_pct": swap_pct,
    "disk": get_disk(),
}

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT_FILE, "w") as f:
    json.dump(snapshot, f, indent=2)

print(f"wrote {OUT_FILE}")
PY
