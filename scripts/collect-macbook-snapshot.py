#!/usr/bin/env python3
"""Collect a lightweight macOS health snapshot and save it as JSON."""
import json
import os
import re
import subprocess
from datetime import datetime, timezone

OUT_DIR = os.path.expanduser("~/var/chaba/health")
OUT_FILE = os.path.join(OUT_DIR, "macbook-snapshot.json")


def run(cmd, timeout=30):
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {
            "cmd": cmd,
            "rc": proc.returncode,
            "out": proc.stdout,
            "err": proc.stderr,
        }
    except Exception as e:
        return {"cmd": cmd, "rc": -1, "out": "", "err": str(e)}


def get_lan_ip():
    # Find the default interface, then ask ipconfig for its IPv4
    res = run("route -n get default 2>/dev/null | grep interface")
    if res["rc"] == 0 and res["out"]:
        ifc = res["out"].strip().split()[-1]
    else:
        ifc = "en0"
    res = run(f"ipconfig getifaddr {ifc}")
    if res["rc"] == 0 and res["out"]:
        return res["out"].strip()
    return ""


def get_tailscale_ip():
    res = run("TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale ip -4")
    if res["rc"] == 0 and res["out"]:
        return res["out"].strip().split()[0]
    return ""


def get_wifi_ssid():
    res = run("networksetup -getairportnetwork en0 2>/dev/null")
    if res["rc"] == 0 and res["out"]:
        m = re.search(r"Current Wi-Fi Network:\s*(.+)", res["out"])
        if m:
            return m.group(1).strip()
    return ""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    snapshot = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "host": "macbook",
        "hostname": "KKs-MacBook-Pro",
        "lan_ip": get_lan_ip(),
        "tailscale_ip": get_tailscale_ip(),
        "wifi_ssid": get_wifi_ssid(),
        "sw_vers": run("sw_vers"),
        "vm_stat": run("vm_stat"),
        "diskutil_list": run("diskutil list"),
        "df_h": run("df -h"),
        "loadavg": run("sysctl -n vm.loadavg"),
        "uptime": run("uptime"),
        "launchctl_count": run("launchctl list | wc -l"),
    }

    with open(OUT_FILE, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
