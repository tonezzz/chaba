#!/usr/bin/env python3
"""Run nmap/arp-scan on the tony-dell host and produce tony-ha-scan.json.

Meant to be the tony-ha counterpart to the michael-ha Advanced SSH & Web Terminal
scan. It runs on the tony-dell host (not inside the tony-ha container) because
the container cannot do raw ARP captures.

Usage:
    python3 scripts/tony-ha-network-scan.py [--no-push]
"""

from __future__ import annotations

import argparse
import json
import ipaddress
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = REPO_ROOT / "data" / "network-scan" / "tony-ha-scan.json"


def run(cmd: str, timeout: int = 120) -> str:
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout + result.stderr


def get_private_subnets() -> list[tuple[str, str]]:
    """Return (iface, network) for every global-scope local interface with a private prefix."""
    out = run("ip -4 -o addr show")
    ifaces: dict[str, list[str]] = {}
    for line in out.splitlines():
        # e.g. 2: enp0s31f6    inet 192.168.2.67/24 brd ... scope global noprefixroute enp0s31f6
        m = re.match(r"\d+:\s+(\S+)\s+inet\s+(\S+).*scope\s+(\S+)", line)
        if not m:
            continue
        iface, cidr, scope = m.group(1), m.group(2), m.group(3)
        if scope != "global" or iface == "lo":
            continue
        try:
            net = ipaddress.IPv4Network(cidr, strict=False)
        except ValueError:
            continue
        if net.is_private and not net.is_loopback and not str(net).startswith("169.254."):
            ifaces.setdefault(iface, []).append(str(net))
    return [(iface, nets[0]) for iface, nets in ifaces.items() if nets]


def parse_arp_scan(text: str) -> dict[str, dict]:
    hosts: dict[str, dict] = {}
    for line in text.splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:]{17})(?:\s+\(.*\))?", line)
        if not m:
            continue
        ip = m.group(1)
        mac = m.group(2).lower()
        if not mac or mac == "00:00:00:00:00:00":
            continue
        hosts[ip] = {"ip": ip, "mac": mac, "source": "arp"}
    return hosts


def parse_nmap_og(text: str) -> dict[str, dict]:
    hosts: dict[str, dict] = {}
    ip = None
    for line in text.splitlines():
        if line.startswith("Host:"):
            m = re.match(r"Host:\s+(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                ip = m.group(1)
            mac_match = re.search(r"MAC Address:\s+([0-9A-F:]{17})", line)
            if mac_match:
                mac = mac_match.group(1).lower()
                hosts[ip] = {"ip": ip, "mac": mac, "source": "arp"}
            elif ip and ip not in hosts:
                hosts[ip] = {"ip": ip, "mac": None, "source": "nmap"}
    return hosts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-push", action="store_true", help="Do not push dashboard.")
    args = parser.parse_args()

    subnets = get_private_subnets()
    if not subnets:
        print("No private /24 subnets found.", file=sys.stderr)
        return 1

    combined: dict[str, dict] = {}
    tool_parts = []

    # arp-scan per interface (sudo required for raw ARP)
    for iface, _net in subnets:
        text = run(f"sudo -n arp-scan -I {iface} -l 2>&1", timeout=60)
        hosts = parse_arp_scan(text)
        for ip, h in hosts.items():
            if ip not in combined:
                combined[ip] = h
            elif h.get("mac") and not combined[ip].get("mac"):
                combined[ip] = h
        if hosts:
            tool_parts.append(f"arp-scan-{iface}")

    # nmap ping sweep for hosts arp-scan may miss
    for _iface, net in subnets:
        text = run(f"sudo -n nmap -sn -n -T4 {net} -oG - 2>&1", timeout=240)
        hosts = parse_nmap_og(text)
        for ip, h in hosts.items():
            if ip not in combined:
                combined[ip] = h
            elif h.get("mac") and not combined[ip].get("mac"):
                combined[ip] = h
        if hosts:
            tool_parts.append(f"nmap-{net}")

    hosts = sorted(combined.values(), key=lambda h: ipaddress.IPv4Address(h["ip"]))
    result = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "network": ", ".join(n for _i, n in subnets),
        "tool": " + ".join(tool_parts) or "nmap/arp-scan",
        "host_count": len(hosts),
        "hosts": hosts,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_FILE} with {len(hosts)} hosts")

    if not args.no_push:
        build_ui = REPO_ROOT / "scripts" / "build-ha-devices-ui.py"
        build_dossier = REPO_ROOT / "scripts" / "build-dossier-devices.py"
        if build_ui.exists():
            print("Regenerating ssot.ha-devices.yml ...")
            run(f"python3 {build_ui}", timeout=60)
        if build_dossier.exists():
            print("Pushing tony-ha devices view ...")
            run(f"python3 {build_dossier} tony-ha", timeout=60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
