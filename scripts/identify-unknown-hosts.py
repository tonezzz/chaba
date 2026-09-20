#!/usr/bin/env python3
"""Look up vendors for unknown MACs discovered by the network scan.

Reads data/network-scan/tony-ha-scan.json and the known MAC registry, then
queries the macvendors.com API for the manufacturer. It writes a suggestion
file to data/network-scan/tony-ha-identified.json.

Usage:
    python3 scripts/identify-unknown-hosts.py
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_FILE = REPO_ROOT / "data" / "network-scan" / "tony-ha-scan.json"
MAC_REGISTRY = (
    REPO_ROOT
    / "docs"
    / "ssot"
    / "infrastructure"
    / "ssot.mac-address-registry.tony.yml"
)
OUT_FILE = REPO_ROOT / "data" / "network-scan" / "tony-ha-identified.json"

MACVENDORS_URL = "https://api.macvendors.com/{mac}"


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def known_macs() -> set[str]:
    data = load_yaml(MAC_REGISTRY)
    known: set[str] = set()
    for rec in data.get("config", {}).get("mac_registry", []):
        for iface in rec.get("interfaces", []):
            mac = iface.get("mac")
            if mac:
                known.add(mac.lower())
    return known


def is_local_mac(mac: str) -> bool:
    """Second-least-significant bit of first octet set means locally administered."""
    try:
        first = int(mac.split(":")[0], 16)
        return bool(first & 0b00000010)
    except ValueError:
        return False


def lookup_vendor(mac: str) -> str | None:
    try:
        resp = urllib.request.urlopen(
            MACVENDORS_URL.format(mac=mac),
            timeout=15,
        )
        text = resp.read().decode("utf-8").strip()
        if not text:
            return None
        if text.startswith("{"):
            # API returned error JSON
            return None
        return text
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        return f"lookup error {e.code}"
    except Exception as e:
        return f"lookup error {e}"


def main() -> int:
    if not SCAN_FILE.exists():
        print(f"Scan file not found: {SCAN_FILE}", file=sys.stderr)
        return 1
    scan = json.loads(SCAN_FILE.read_text(encoding="utf-8"))
    known = known_macs()
    results = []
    print("Unknown / new hosts from the latest scan")
    print("=" * 60)
    for i, host in enumerate(scan.get("hosts", [])):
        ip = host.get("ip")
        mac = (host.get("mac") or "").lower()
        if not mac:
            continue
        if mac in known:
            continue
        local = is_local_mac(mac)
        if i > 0:
            time.sleep(1.5)
        vendor = lookup_vendor(mac) if not local else None
        suggestion = {
            "ip": ip,
            "mac": mac,
            "vendor": vendor,
            "local_administered": local,
        }
        results.append(suggestion)
        status = f"local-admin ({vendor or 'n/a'})" if local else (vendor or "unknown vendor")
        print(f"{ip or 'no-ip':<15}  {mac:<17}  {status}")
    print("=" * 60)
    print(f"Total new hosts: {len(results)}")
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
