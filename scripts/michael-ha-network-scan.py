#!/usr/bin/env python3
"""Run nmap + arp-scan on michael-ha's Advanced SSH & Web Terminal add-on and
produce michael-ha-scan.json, then rebuild/push the michael-ha Dossier devices view.

This is the michael-ha counterpart to tony-ha-network-scan.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = REPO_ROOT / "data" / "network-scan" / "michael-ha-scan.json"
SSH_KEY = Path.home() / ".ssh" / "michael-ha"
SSH_TARGET = "-p 2222 root@michael-ha"
SSH_OPTS = (
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
    "-o BatchMode=yes -o ConnectTimeout=10"
)


def ssh(cmd: str, timeout: int = 600) -> str:
    full = f'ssh -i {SSH_KEY} {SSH_OPTS} {SSH_TARGET} "{cmd}"'
    result = subprocess.run(
        full,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout + result.stderr


def parse_arp_scan(text: str) -> dict[str, dict]:
    hosts: dict[str, dict] = {}
    for line in text.splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:]{17})(?:\s+\(?([^)]+)\)?)?", line)
        if not m:
            continue
        ip = m.group(1)
        mac = m.group(2).lower()
        vendor = (m.group(3) or "").strip()
        if not mac or mac == "00:00:00:00:00:00":
            continue
        if "DUP" in line:
            # Prefer first or keep with the same IP and MAC
            pass
        hosts[ip] = {
            "ip": ip,
            "mac": mac,
            "source": "arp",
            "vendor": vendor if vendor and vendor not in ("Unknown", "Unknown: locally administered") else None,
        }
    return hosts


def parse_nmap_xml(text: str) -> dict[str, dict]:
    hosts: dict[str, dict] = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return hosts
    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue
        ip = None
        mac = None
        for addr in host.findall("address"):
            atype = addr.get("addrtype")
            if atype == "ipv4":
                ip = addr.get("addr")
            elif atype == "mac":
                mac = (addr.get("addr") or "").lower()
        if not ip:
            continue

        # Hostname from DNS/mDNS reverse if available
        hostnames = []
        for hn in host.findall("hostnames/hostname"):
            name = hn.get("name")
            if name:
                hostnames.append(name)

        # Service banners
        services = []
        for port in host.findall("ports/port"):
            state = port.find("state")
            if state is None or state.get("state") != "open":
                continue
            portid = port.get("portid")
            proto = port.get("protocol")
            svc = port.find("service")
            if svc is None:
                continue
            name = svc.get("name") or ""
            product = svc.get("product") or ""
            version = svc.get("version") or ""
            extrainfo = svc.get("extrainfo") or ""
            parts = [p for p in [name, product, version, extrainfo] if p]
            if parts:
                services.append(f"{portid}/{proto}: {' '.join(parts)}")

        hosts[ip] = {
            "ip": ip,
            "mac": mac,
            "source": "nmap",
            "hostname": hostnames[0] if hostnames else None,
            "services": "; ".join(services) if services else None,
        }
    return hosts


def main() -> int:
    print("Running arp-scan on michael-ha ...")
    arp_text = ssh("arp-scan -I end0 -l 2>&1", timeout=120)
    arp_hosts = parse_arp_scan(arp_text)
    print(f"  arp-scan found {len(arp_hosts)} hosts")

    print("Running nmap discovery on michael-ha (this may take a few minutes) ...")
    nmap_text = ssh(
        "nmap -sn -T5 -n 192.168.1.0/24 -oX - 2>&1",
        timeout=300,
    )
    nmap_hosts = parse_nmap_xml(nmap_text)
    print(f"  nmap found {len(nmap_hosts)} up hosts")

    # Combine: arp-scan gives the most reliable MAC, nmap gives hostname/services
    combined: dict[str, dict] = {}
    for ip, h in arp_hosts.items():
        combined[ip] = h
    for ip, h in nmap_hosts.items():
        existing = combined.get(ip)
        if existing:
            if h.get("mac") and not existing.get("mac"):
                existing["mac"] = h["mac"]
            if h.get("hostname") and not existing.get("hostname"):
                existing["hostname"] = h["hostname"]
            if h.get("services") and not existing.get("services"):
                existing["services"] = h["services"]
            # Keep the arp source for MAC but nmap for IP if hostname/services came from there
            if h.get("hostname") or h.get("services"):
                existing["source"] = "arp / nmap"
        else:
            combined[ip] = h

    hosts = sorted(combined.values(), key=lambda h: tuple(int(p) for p in h["ip"].split(".")))
    result = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "network": "192.168.1.0/24",
        "tool": "arp-scan + nmap -sV",
        "host_count": len(hosts),
        "hosts": hosts,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_FILE} with {len(hosts)} hosts")

    build_ui = REPO_ROOT / "scripts" / "build-ha-devices-ui.py"
    build_dossier = REPO_ROOT / "scripts" / "build-dossier-devices.py"
    if build_ui.exists():
        print("Regenerating ssot.ha-devices.yml ...")
        subprocess.run(["python3", str(build_ui)], check=False, timeout=120)
    if build_dossier.exists():
        print("Pushing michael-ha devices view ...")
        subprocess.run(["python3", str(build_dossier), "michael-ha"], check=False, timeout=120)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
