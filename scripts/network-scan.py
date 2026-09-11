#!/usr/bin/env python3
"""Scan Tony's active home network and emit runtime scan results.

Reads the active CIDR from docs/ssot/infrastructure/ssot.ip-address-registry.yml,
runs nmap -sn against it, merges with the kernel ARP table, and writes
data/network-scan/tony-ha-scan.json. build-ha-devices-ui.py then merges
the per-host `last_seen` timestamps into the generated device rows.

Usage:
    python3 scripts/network-scan.py
    python3 scripts/network-scan.py --push   # also rebuild and push dashboard
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
IP_REGISTRY = (
    REPO_ROOT
    / "docs"
    / "ssot"
    / "infrastructure"
    / "ssot.ip-address-registry.yml"
)
SCAN_FILE = REPO_ROOT / "data" / "network-scan" / "tony-ha-scan.json"
HA_SCAN_FILE = Path.home() / ".config" / "home-assistant" / "www" / "ha" / "network-scan-latest.json"


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def active_cidr() -> str:
    data = load_yaml(IP_REGISTRY)
    for net in data.get("config", {}).get("networks", []):
        if net.get("status") == "active":
            return net.get("cidr", "192.168.2.0/24")
    return "192.168.2.0/24"


def parse_proc_net_arp() -> dict[str, str]:
    """Return {ip: mac} from the kernel ARP table (reachable entries only)."""
    table: dict[str, str] = {}
    proc = Path("/proc/net/arp")
    if not proc.exists():
        return table
    for line in proc.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, _, flags, mac, mask, _device = parts
        if flags == "0x0":
            continue
        if mac.lower() == "00:00:00:00:00:00":
            continue
        if not re.fullmatch(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
            continue
        table[ip] = mac.lower()
    return table


def run_nmap(cidr: str) -> dict[str, str]:
    """Return {ip: mac} discovered by nmap -sn."""
    hosts: dict[str, str] = {}
    if not shutil.which("nmap"):
        print("nmap not found, skipping nmap scan")
        return hosts
    cmd = ["nmap", "-oX", "-", "-sn", cidr]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("nmap scan timed out")
        return hosts
    if result.returncode != 0:
        print(f"nmap failed: {result.stderr[:200]}")
        return hosts
    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError as e:
        print(f"nmap XML parse error: {e}")
        return hosts
    for host in root.findall("host"):
        ip = mac = None
        for addr in host.findall("address"):
            atype = addr.get("addrtype")
            if atype == "ipv4":
                ip = addr.get("addr")
            elif atype == "mac":
                mac = (addr.get("addr") or "").lower()
        if ip:
            hosts[ip] = mac or ""
    return hosts


def merge_hosts(nmap_hosts: dict[str, str], arp_hosts: dict[str, str]) -> dict[str, str]:
    """Prefer nmap MAC, but keep ARP hosts nmap missed."""
    merged = dict(arp_hosts)
    for ip, mac in nmap_hosts.items():
        if mac:
            merged[ip] = mac
        elif ip not in merged:
            merged[ip] = ""
    return merged


def main() -> int:
    SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    cidr = active_cidr()
    print(f"Scanning {cidr} ...")
    nmap_hosts = run_nmap(cidr)
    arp_hosts = parse_proc_net_arp()
    hosts = merge_hosts(nmap_hosts, arp_hosts)
    now = datetime.now(timezone.utc).isoformat()
    scan_doc = {
        "discovered_at": now,
        "network": cidr,
        "tool": "nmap -sn + /proc/net/arp",
        "host_count": len(hosts),
        "hosts": [
            {"ip": ip, "mac": mac or None, "source": "arp" if ip in arp_hosts else "nmap"}
            for ip, mac in sorted(hosts.items(), key=lambda x: tuple(int(p) for p in x[0].split(".")))
        ],
    }
    SCAN_FILE.write_text(json.dumps(scan_doc, indent=2), encoding="utf-8")
    print(f"Wrote {SCAN_FILE} ({len(hosts)} hosts)")
    try:
        HA_SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        HA_SCAN_FILE.write_text(json.dumps(scan_doc, indent=2), encoding="utf-8")
        print(f"Wrote {HA_SCAN_FILE}")
    except OSError as e:
        print(f"Could not write HA copy: {e}")
    if "--push" in sys.argv:
        print("Rebuilding device registry and pushing dashboard...")
        build = REPO_ROOT / "scripts" / "build-ha-devices-ui.py"
        push = REPO_ROOT / "scripts" / "build-dossier-devices.py"
        subprocess.run([sys.executable, str(build)], check=True)
        subprocess.run([sys.executable, str(push), "tony-ha"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
