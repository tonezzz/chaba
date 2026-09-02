#!/usr/bin/env python3
"""
Nightly ARP inventory scan.

- Discovers live hosts on the default-route subnet(s).
- Compares them against docs/ssot/infrastructure/ssot.mac-address-registry.yml
  and ssot.ip-address-registry.yml.
- Writes a timestamped JSON report in reports/.
- Maintains a runtime last-seen map in reports/network-inventory-last-seen.json.
- Creates a focus-inbox alert only when a *new* or *changed* device/MAC is seen,
  or a duplicate MAC appears in the scan.
- Never rewrites the canonical SSOT files automatically.
"""

import argparse
import datetime
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MAC_SSOT = REPO_ROOT / "docs/ssot/infrastructure/ssot.mac-address-registry.yml"
IP_SSOT = REPO_ROOT / "docs/ssot/infrastructure/ssot.ip-address-registry.yml"
REPORTS_DIR = REPO_ROOT / "reports"
FOCUS_INBOX_DIR = REPO_ROOT / "docs/ssot/focus-inbox"
LAST_SEEN_FILE = REPORTS_DIR / "network-inventory-last-seen.json"


def run(cmd, **kwargs):
    """Run a shell command and return stdout text."""
    return subprocess.run(
        cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kwargs
    )


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def short_mac(mac):
    """Return a filesystem-safe short form of a MAC, or 'nullmac'."""
    if not mac:
        return "nullmac"
    return mac.replace(":", "")


def build_mac_map(mac_data):
    """Return dict mac -> list of (device_id, interface_id, device_label)."""
    mac_map = {}
    for device in mac_data.get("config", {}).get("mac_registry", []):
        device_id = device["device_id"]
        label = device.get("label", device_id)
        for iface in device.get("interfaces", []):
            mac = iface.get("mac")
            if not mac:
                continue
            mac_map.setdefault(mac, []).append(
                {
                    "device_id": device_id,
                    "interface_id": iface.get("interface_id", "primary"),
                    "label": label,
                }
            )
    return mac_map


def build_ip_map(ip_data):
    """Return dict ip -> list of {device_id, interface_id, network_id}."""
    ip_map = {}
    for network in ip_data.get("config", {}).get("networks", []):
        network_id = network["network_id"]
        for alloc in network.get("allocations", []):
            ip = alloc.get("ip")
            if not ip:
                continue
            ip_map.setdefault(ip, []).append(
                {
                    "device_id": alloc.get("device_id"),
                    "interface_id": alloc.get("interface_id", "primary"),
                    "network_id": network_id,
                }
            )
    return ip_map


def get_default_subnets():
    """Find /24 subnets of interfaces with an active default route."""
    # Parse default routes
    route_out = run("ip -4 -o route show default").stdout
    defaults = []
    for line in route_out.splitlines():
        m = re.search(r"dev\s+(\S+).*metric\s+(\d+)", line)
        if not m:
            m = re.search(r"dev\s+(\S+)", line)
            metric = 999
            iface = m.group(1) if m else None
        else:
            iface = m.group(1)
            metric = int(m.group(2))
        if iface:
            defaults.append((metric, iface))

    if not defaults:
        print("No default route found; nothing to scan.", file=sys.stderr)
        return []

    defaults.sort()
    lowest_metric = defaults[0][0]
    default_ifaces = [iface for metric, iface in defaults if metric == lowest_metric]

    # Get CIDRs for those interfaces
    subnets = []
    seen_networks = set()
    for iface in default_ifaces:
        addr_out = run(f"ip -4 -o addr show dev {iface}").stdout
        for line in addr_out.splitlines():
            m = re.search(r"inet\s+(\S+)", line)
            if not m:
                continue
            cidr = m.group(1)
            try:
                network = ipaddress.IPv4Network(cidr, strict=False)
            except ValueError:
                continue
            # Only scan RFC1918 private subnets
            if not network.is_private:
                continue
            if network.network_address not in seen_networks:
                seen_networks.add(network.network_address)
                subnets.append((iface, str(network)))

    return subnets


def ping_sweep(network_str):
    """Ping every address in a /24 and return nothing (ARP table is populated)."""
    network = ipaddress.IPv4Network(network_str, strict=False)
    base = str(network.network_address).rsplit(".", 1)[0]
    # .0 and .255 are network/broadcast; skip them
    start = 1
    end = network.num_addresses - 2
    cmd = f"seq {start} {end} | xargs -P 40 -I{{}} ping -c 1 -W 1 {base}.{{}} >/dev/null 2>&1"
    run(cmd, timeout=120)
    # Give the kernel a moment to finish ARP entries
    run("sleep 2")


def get_arp_table():
    """Return list of {ip, mac, device, state} from ip neigh."""
    out = run("ip -4 -o neigh show").stdout
    entries = []
    for line in out.splitlines():
        # e.g.: 192.168.2.1 dev wlo1 lladdr 98:00:6a:68:f7:c6 REACHABLE
        parts = line.split()
        if len(parts) < 4:
            continue
        ip = parts[0]
        if parts[1] != "dev":
            continue
        iface = parts[2]
        state = parts[-1]
        if state in ("FAILED", "INCOMPLETE"):
            continue
        mac = None
        for i, p in enumerate(parts):
            if p == "lladdr" and i + 1 < len(parts):
                mac = parts[i + 1]
                break
        if not mac:
            continue
        entries.append({"ip": ip, "mac": mac, "device": iface, "state": state})
    return deduplicate_entries(entries)


def deduplicate_entries(entries):
    """Keep one entry per IP, preferring the best ARP state.

    When a host is reachable via two local interfaces (e.g. eno1 + wlo1 on the
    same subnet), the kernel may hold the same IP/MAC pair in the table twice.
    That is not a duplicate MAC.
    """
    state_rank = {"REACHABLE": 3, "STALE": 2, "DELAY": 1}
    by_ip = {}
    for e in entries:
        existing = by_ip.get(e["ip"])
        if existing is None or state_rank.get(e["state"], 0) > state_rank.get(
            existing["state"], 0
        ):
            by_ip[e["ip"]] = e
    return list(by_ip.values())


def build_device_ip_map(ip_map):
    """Return dict device_id -> set of known IPs."""
    device_ips = {}
    for ip, entries in ip_map.items():
        for e in entries:
            device_ips.setdefault(e["device_id"], set()).add(ip)
    return device_ips


def classify_discovery(discovered, mac_map, ip_map, last_seen):
    """Compare discovered hosts against registry and last seen."""
    results = {
        "discovered": [],
        "consistent": [],
        "new_devices": [],
        "new_ip_for_known_device": [],
        "mac_changed": [],
        "conflict": [],
        "duplicate_macs": [],
    }

    device_ip_map = build_device_ip_map(ip_map)

    # Group by MAC within this scan to detect duplicate MACs
    by_mac = {}
    for e in discovered:
        by_mac.setdefault(e["mac"], []).append(e)

    # A MAC that appears for multiple distinct IPs may be a duplicate MAC or a
    # multi-IP known device. Single known device -> covered by new_ip alerts.
    duplicate_macs = {}
    for mac, entries in by_mac.items():
        if len(entries) <= 1:
            continue
        ips = {e["ip"] for e in entries}
        if len(ips) <= 1:
            continue
        known_devices = {m["device_id"] for m in mac_map.get(mac, [])}
        if len(known_devices) == 1:
            # Single known device with multiple IPs; per-entry alerts handle this
            device_id = known_devices.pop()
            continue
        duplicate_macs[mac] = entries

    # Track keys seen this run
    seen_keys = set()

    for e in discovered:
        ip = e["ip"]
        mac = e["mac"]
        mac_entries = mac_map.get(mac, [])
        ip_entries = ip_map.get(ip, [])

        result_entry = {
            "ip": ip,
            "mac": mac,
            "device": e["device"],
            "state": e["state"],
        }
        results["discovered"].append(result_entry)

        if len(mac_entries) > 1:
            # Registry already knows this MAC collides; still surface if observed
            results["conflict"].append(
                {
                    "ip": ip,
                    "mac": mac,
                    "registry_devices": [m["device_id"] for m in mac_entries],
                    "reason": "registry_duplicate_mac",
                }
            )

        if mac_entries and ip_entries:
            mac_device = mac_entries[0]["device_id"]
            # If IP maps to multiple known allocations, flag conflict
            matching = [
                a for a in ip_entries if a["device_id"] == mac_device
            ]
            if matching:
                results["consistent"].append(
                    {
                        **result_entry,
                        "device_id": mac_device,
                        "interface_id": matching[0]["interface_id"],
                        "network_id": matching[0]["network_id"],
                    }
                )
                key = f"{mac_device}/{matching[0]['interface_id']}"
                seen_keys.add(key)
                continue
            else:
                results["conflict"].append(
                    {
                        **result_entry,
                        "mac_device": mac_device,
                        "ip_devices": [a["device_id"] for a in ip_entries],
                        "reason": "mac_and_ip_belong_to_different_known_devices",
                    }
                )
                continue

        if mac_entries and not ip_entries:
            # Known MAC, unknown IP -> new IP for known device
            device = mac_entries[0]
            key = f"{device['device_id']}/{device['interface_id']}"
            is_new = key not in last_seen or last_seen[key].get("ip") != ip
            alert = {
                **result_entry,
                "device_id": device["device_id"],
                "interface_id": device["interface_id"],
                "is_new": is_new,
            }
            results["new_ip_for_known_device"].append(alert)
            seen_keys.add(key)
            continue

        if ip_entries and not mac_entries:
            # Known IP, unknown MAC -> MAC changed or IP reused
            device = ip_entries[0]
            key = f"{device['device_id']}/{device['interface_id']}"
            is_new = key not in last_seen or last_seen[key].get("mac") != mac
            results["mac_changed"].append(
                {
                    **result_entry,
                    "device_id": device["device_id"],
                    "interface_id": device["interface_id"],
                    "network_id": device["network_id"],
                    "is_new": is_new,
                }
            )
            seen_keys.add(key)
            continue

        # Unknown MAC and unknown IP -> brand new device
        key = f"discovered/{ip}"
        is_new = key not in last_seen
        results["new_devices"].append({**result_entry, "is_new": is_new})
        seen_keys.add(key)

    for mac, entries in duplicate_macs.items():
        results["duplicate_macs"].append(
            {
                "mac": mac,
                "ips": [e["ip"] for e in entries],
                "known_devices": [m["device_id"] for m in mac_map.get(mac, [])],
                "reason": "same_mac_multiple_ips_in_scan",
            }
        )

    return results


def update_last_seen(discovered, mac_map, ip_map, last_seen):
    """Update the runtime last-seen map and return it."""
    now = now_iso()
    # Update existing keys and add new ones
    for e in discovered:
        ip = e["ip"]
        mac = e["mac"]
        mac_entries = mac_map.get(mac, [])
        ip_entries = ip_map.get(ip, [])

        if mac_entries:
            device = mac_entries[0]
            key = f"{device['device_id']}/{device['interface_id']}"
            last_seen[key] = {
                "device_id": device["device_id"],
                "interface_id": device["interface_id"],
                "ip": ip,
                "mac": mac,
                "last_seen": now,
                "source": "arp",
            }
        elif ip_entries:
            device = ip_entries[0]
            key = f"{device['device_id']}/{device['interface_id']}"
            last_seen[key] = {
                "device_id": device["device_id"],
                "interface_id": device["interface_id"],
                "ip": ip,
                "mac": mac,
                "last_seen": now,
                "source": "arp",
            }
        else:
            key = f"discovered/{ip}"
            last_seen[key] = {
                "ip": ip,
                "mac": mac,
                "last_seen": now,
                "source": "arp",
            }

    return last_seen


def should_alert(results):
    """Only alert on *new* changes, not stale registry drift."""
    for key in ("new_devices", "new_ip_for_known_device", "mac_changed", "conflict", "duplicate_macs"):
        if results.get(key):
            return True
    return False


def write_focus_inbox(results, ts):
    """Create a focus-inbox YAML for review."""
    FOCUS_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{ts}-arp-inventory-alert.yml"
    path = FOCUS_INBOX_DIR / filename

    subtasks = []
    for item in results.get("new_devices", []):
        subtasks.append(
            {
                "label": f"Identify new device {item['ip']} ({item['mac']})",
                "status": "not_started",
            }
        )
    for item in results.get("new_ip_for_known_device", []):
        subtasks.append(
            {
                "label": f"Add new IP {item['ip']} for {item['device_id']} to IP registry",
                "status": "not_started",
            }
        )
    for item in results.get("mac_changed", []):
        subtasks.append(
            {
                "label": f"Check MAC change for {item['ip']} (was {item.get('device_id','known device')}, now {item['mac']})",
                "status": "not_started",
            }
        )
    for item in results.get("conflict", []):
        subtasks.append(
            {
                "label": f"Resolve MAC/IP conflict: {item.get('ip')} / {item.get('mac')}",
                "status": "not_started",
            }
        )
    for item in results.get("duplicate_macs", []):
        subtasks.append(
            {
                "label": f"Duplicate MAC {item['mac']} on IPs {', '.join(item['ips'])}",
                "status": "not_started",
            }
        )

    priority = "medium" if results.get("duplicate_macs") or results.get("conflict") else "low"

    focus_text = [
        "ARP inventory scan found changes compared to the MAC/IP registries.",
        "",
        f"- New devices: {len(results.get('new_devices', []))}",
        f"- New IP for known device: {len(results.get('new_ip_for_known_device', []))}",
        f"- MAC changed: {len(results.get('mac_changed', []))}",
        f"- Conflicts: {len(results.get('conflict', []))}",
        f"- Duplicate MACs in scan: {len(results.get('duplicate_macs', []))}",
        "",
        f"Report: reports/network-inventory-scan-{ts}.json",
    ]

    doc = {
        "title": "ARP inventory alert",
        "subtitle": f"Network scan changes detected at {ts}",
        "icon": "inbox",
        "focus": {
            "label": "Review ARP inventory scan results",
            "text": "\n".join(focus_text),
            "branch": "chaba",
            "priority": priority,
            "status": "draft",
            "tags": ["network", "arp", "inventory", "mac-registry"],
            "safe_to_parallel": {
                "value": True,
                "reason": "Registry review only; does not change live services.",
            },
            "subtasks": subtasks,
        },
        "ownership": {
            "owner": "tony",
            "session": "",
            "locked": False,
            "lock_reason": "",
        },
        "source": {"session": "", "date": datetime.date.today().isoformat()},
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=1000)
    print(f"Focus inbox alert written: {path}", file=sys.stderr)


def write_report(results, subnets, ts, dry_run=False):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"network-inventory-scan-{ts}.json"
    report = {
        "scanned_at": now_iso(),
        "subnets": subnets,
        "summary": {
            "discovered": len(results["discovered"]),
            "consistent": len(results["consistent"]),
            "new_devices": len(results["new_devices"]),
            "new_ip_for_known_device": len(results["new_ip_for_known_device"]),
            "mac_changed": len(results["mac_changed"]),
            "conflict": len(results["conflict"]),
            "duplicate_macs": len(results["duplicate_macs"]),
        },
        "results": results,
    }
    if dry_run:
        return report_path, report
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    return report_path, report


def main():
    parser = argparse.ArgumentParser(description="ARP inventory scan hook")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files")
    parser.add_argument("--no-ping", action="store_true", help="Use existing ARP table without ping sweep")
    parser.add_argument("--no-focus", action="store_true", help="Do not create focus-inbox alert")
    args = parser.parse_args()

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d-%H%M%S")

    mac_data = load_yaml(MAC_SSOT)
    ip_data = load_yaml(IP_SSOT)
    mac_map = build_mac_map(mac_data)
    ip_map = build_ip_map(ip_data)

    if LAST_SEEN_FILE.exists():
        with open(LAST_SEEN_FILE, "r", encoding="utf-8") as f:
            try:
                last_seen = json.load(f)
            except json.JSONDecodeError:
                last_seen = {}
    else:
        last_seen = {}

    subnets = get_default_subnets()
    if not subnets:
        print("No RFC1918 default subnets to scan.", file=sys.stderr)
        sys.exit(0)

    for iface, network in subnets:
        print(f"Scanning {network} on {iface} ...", file=sys.stderr)
        if not args.no_ping:
            ping_sweep(network)

    discovered = get_arp_table()
    # Restrict to the scanned subnets
    scanned_networks = [ipaddress.IPv4Network(n) for _, n in subnets]
    discovered = [
        e for e in discovered
        if any(ipaddress.IPv4Address(e["ip"]) in net for net in scanned_networks)
    ]

    results = classify_discovery(discovered, mac_map, ip_map, last_seen)

    last_seen = update_last_seen(discovered, mac_map, ip_map, last_seen)

    report_path, report = write_report(results, subnets, ts, dry_run=args.dry_run)

    if not args.dry_run:
        with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(last_seen, f, indent=2, sort_keys=True)
        print(f"Report written: {report_path}", file=sys.stderr)
        print(f"Last-seen map updated: {LAST_SEEN_FILE}", file=sys.stderr)
    else:
        print("DRY RUN — no files written", file=sys.stderr)

    print(json.dumps(report["summary"], indent=2), file=sys.stderr)

    if should_alert(results) and not args.dry_run and not args.no_focus:
        write_focus_inbox(results, ts)

    # Return non-zero only on real conflicts/duplicates so systemd can alert if desired
    if results["duplicate_macs"] or results["conflict"]:
        sys.exit(2)
    if results["new_devices"] or results["new_ip_for_known_device"] or results["mac_changed"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
