#!/usr/bin/env python3
"""Build a unified HA-devices SSOT and the apps/ha UI YAML from registry files.

Sources:
- docs/ssot/infrastructure/ssot.mac-address-registry.tony.yml
- docs/ssot/infrastructure/ssot.ip-address-registry.yml
- docs/ssot/infrastructure/ssot.mac-address-registry.michael.yml
- docs/ssot/infrastructure/ssot.ip-address-registry.michael.yml

Outputs:
- docs/ssot/infrastructure/ssot.ha-devices.yml (canonical flat list)
- stacks/web/public/apps/ha/ssot.ui.ha.yml (UI-optimized grouped view)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

OUT_SSOT = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.ha-devices.yml"
OUT_UI = REPO_ROOT / "stacks" / "web" / "public" / "apps" / "ha" / "ssot.ui.ha.yml"

REGISTRY = {
    "tony-ha": {
        "mac": REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.mac-address-registry.tony.yml",
        "ip": REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.ip-address-registry.yml",
    },
    "michael-ha": {
        "mac": REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.mac-address-registry.michael.yml",
        "ip": REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.ip-address-registry.michael.yml",
    },
}


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_mac_records(data: dict) -> list[dict]:
    return data.get("config", {}).get("mac_registry", [])


def get_ip_allocations(data: dict) -> list[dict]:
    networks = data.get("config", {}).get("networks", [])
    allocs: list[dict] = []
    for net in networks:
        for a in net.get("allocations", []):
            a = dict(a)
            a.setdefault("network", net)
            allocs.append(a)
    return allocs


def build_instance_rows(ha_instance: str, mac_data: dict, ip_data: dict) -> list[dict]:
    """Join mac and ip records by (device_id, interface_id) and add unmatched ones."""
    rows: list[dict] = []
    mac_records = {r["device_id"]: r for r in get_mac_records(mac_data)}
    allocs = get_ip_allocations(ip_data)

    def is_active(a: dict) -> bool:
        return a.get("network", {}).get("status") == "active"

    def better(a: dict, b: dict) -> bool:
        """Prefer active-network allocations over stale ones."""
        if not a:
            return False
        if not b:
            return True
        return is_active(a) and not is_active(b)

    # Map allocations by (device_id, interface_id) and by device only (for fallback)
    alloc_by_key: dict[tuple[str, str], dict] = {}
    alloc_by_dev: dict[str, list[dict]] = {}
    used_alloc_ids: set[int] = set()
    for idx, alloc in enumerate(allocs):
        did = alloc["device_id"]
        iid = alloc.get("interface_id", "primary")
        a = {**alloc, "_idx": idx}
        existing = alloc_by_key.get((did, iid))
        if not existing or better(a, existing):
            alloc_by_key[(did, iid)] = a
        alloc_by_dev.setdefault(did, []).append(a)

    for did, rec in mac_records.items():
        for iface in rec.get("interfaces", []):
            iid = iface.get("interface_id", "primary")
            # Exact match first
            alloc = alloc_by_key.get((did, iid))
            if not alloc:
                # Fallback to any single unassigned allocation for this device
                candidates = [a for a in alloc_by_dev.get(did, []) if a["_idx"] not in used_alloc_ids]
                # Prefer primary or a known interface not yet used
                non_primary = [a for a in candidates if a.get("interface_id") != "primary"]
                if len(candidates) == 1 or non_primary:
                    alloc = (non_primary or candidates)[0] if candidates else None

            if alloc:
                used_alloc_ids.add(alloc["_idx"])

            rows.append(
                {
                    "ha_instance": ha_instance,
                    "device_id": did,
                    "label": rec.get("label", did),
                    "ip": alloc.get("ip") if alloc else None,
                    "mac": iface.get("mac"),
                    "interface_id": iid,
                    "type": iface.get("type"),
                    "mac_source": iface.get("source"),
                    "ip_source": alloc.get("source") if alloc else None,
                    "network_id": (alloc.get("network") or {}).get("network_id") if alloc else None,
                    "network_status": (alloc.get("network") or {}).get("status") if alloc else None,
                    "status": iface.get("status", "active"),
                    "ip_kind": alloc.get("kind") if alloc else None,
                    "first_seen": (alloc.get("first_seen") if alloc else None) or iface.get("first_seen"),
                    "last_seen": alloc.get("last_seen") if alloc else None,
                }
            )

    # Add IP allocations that have no matching mac interface at all
    for idx, alloc in enumerate(allocs):
        if idx in used_alloc_ids:
            continue
        did = alloc["device_id"]
        rec = mac_records.get(did)
        iid = alloc.get("interface_id", "primary")
        # Skip if a mac interface with the same interface_id already covers this device
        if rec and any(iface.get("interface_id") == iid for iface in rec.get("interfaces", [])):
            continue
        rows.append(
            {
                "ha_instance": ha_instance,
                "device_id": did,
                "label": rec.get("label", did) if rec else did,
                "ip": alloc.get("ip"),
                "mac": None,
                "interface_id": iid,
                "type": "unknown",
                "mac_source": None,
                "ip_source": alloc.get("source"),
                "network_id": (alloc.get("network") or {}).get("network_id"),
                "network_status": (alloc.get("network") or {}).get("status"),
                "status": alloc.get("status", "active"),
                "ip_kind": alloc.get("kind"),
                "first_seen": alloc.get("first_seen"),
                "last_seen": alloc.get("last_seen"),
            }
        )

    return rows


def build_michael_dev_rows() -> list[dict]:
    """Dev instance has no separate network registry; list its HA device registry items."""
    return [
        {
            "ha_instance": "michael-dev",
            "device_id": "5a59c585a4dd35c1af1e93a7398f7090",
            "label": "Sun",
            "ip": None,
            "mac": None,
            "interface_id": "primary",
            "type": "virtual",
            "mac_source": "ha-device-registry",
            "ip_source": "ha-device-registry",
            "network_id": None,
            "network_status": "unknown",
            "status": "active",
            "ip_kind": None,
            "first_seen": None,
        },
        {
            "ha_instance": "michael-dev",
            "device_id": "f0bd32929e81e09e3d830450ba8ca1e6",
            "label": "Backup",
            "ip": None,
            "mac": None,
            "interface_id": "primary",
            "type": "virtual",
            "mac_source": "ha-device-registry",
            "ip_source": "ha-device-registry",
            "network_id": None,
            "network_status": "unknown",
            "status": "active",
            "ip_kind": None,
            "first_seen": None,
        },
        {
            "ha_instance": "michael-dev",
            "device_id": "756b55b96dec5d0d20e83a1f78c571a6",
            "label": "Google Translate en com",
            "ip": None,
            "mac": None,
            "interface_id": "primary",
            "type": "virtual",
            "mac_source": "ha-device-registry",
            "ip_source": "ha-device-registry",
            "network_id": None,
            "network_status": "unknown",
            "status": "active",
            "ip_kind": None,
            "first_seen": None,
        },
        {
            "ha_instance": "michael-dev",
            "device_id": "6572f2976ffb8ffa56a6e87f2cdcfa5c",
            "label": "Forecast",
            "ip": None,
            "mac": None,
            "interface_id": "primary",
            "type": "virtual",
            "mac_source": "ha-device-registry",
            "ip_source": "ha-device-registry",
            "network_id": None,
            "network_status": "unknown",
            "status": "active",
            "ip_kind": None,
            "first_seen": None,
        },
        {
            "ha_instance": "michael-dev",
            "device_id": "02dd55a1519aa0b614e5bdc17f798188",
            "label": "HA-MCP Server",
            "ip": None,
            "mac": None,
            "interface_id": "primary",
            "type": "virtual",
            "mac_source": "ha-device-registry",
            "ip_source": "ha-device-registry",
            "network_id": None,
            "network_status": "unknown",
            "status": "active",
            "ip_kind": None,
            "first_seen": None,
        },
    ]


def network_info(ip_data: dict) -> dict:
    networks = ip_data.get("config", {}).get("networks", [])
    if not networks:
        return {}
    n = networks[0]
    return {
        "network_id": n.get("network_id"),
        "cidr": n.get("cidr"),
        "gateway": n.get("gateway"),
        "ssid": n.get("ssid"),
    }


def main() -> None:
    all_rows: list[dict] = []

    meta = {
        "michael-ha": {"title": "Michael HA", "description": "Michael's home network"},
        "tony-ha": {"title": "Tony HA", "description": "Tony's home network"},
        "michael-dev": {"title": "Michael Dev", "description": "Michael dev HA on tony-dell"},
    }
    ui_instances: dict[str, dict] = {
        name: {
            "title": info["title"],
            "description": info["description"],
            "network": {},
            "devices": [],
        }
        for name, info in meta.items()
    }

    for ha_instance, paths in REGISTRY.items():
        mac_data = load_yaml(paths["mac"])
        ip_data = load_yaml(paths["ip"])
        rows = build_instance_rows(ha_instance, mac_data, ip_data)
        all_rows.extend(rows)
        ui_instances[ha_instance]["network"] = network_info(ip_data)
        ui_instances[ha_instance]["devices"] = [
            {k: v for k, v in row.items() if k not in ("ha_instance",)} for row in rows
        ]

    dev_rows = build_michael_dev_rows()
    all_rows.extend(dev_rows)
    ui_instances["michael-dev"]["devices"] = [
        {k: v for k, v in row.items() if k not in ("ha_instance",)} for row in dev_rows
    ]

    OUT_SSOT.parent.mkdir(parents=True, exist_ok=True)
    OUT_UI.parent.mkdir(parents=True, exist_ok=True)

    ssot_doc = {
        "title": "Home Assistant Device Registry",
        "subtitle": "Per-HA instance network devices with MAC and IP",
        "icon": "🏠",
        "ideas": [
            "Flat, per-HA-instance device list derived from the MAC and IP address registries.",
            "device_id is the stable key; MAC and IP are attributes that can change.",
            "Keeps network and HA-instance context in one file for apps and automations.",
        ],
        "config": {
            "version": 1,
            "last_updated": "2026-09-04",
            "maintainer": "tony",
            "status": "active",
            "source_files": [
                "docs/ssot/infrastructure/ssot.mac-address-registry.tony.yml",
                "docs/ssot/infrastructure/ssot.ip-address-registry.yml",
                "docs/ssot/infrastructure/ssot.mac-address-registry.michael.yml",
                "docs/ssot/infrastructure/ssot.ip-address-registry.michael.yml",
            ],
        },
        "schema": {
            "device_record": {
                "required": ["ha_instance", "device_id", "label"],
                "fields": {
                    "ha_instance": "Home Assistant instance slug (e.g. tony-ha, michael-ha, michael-dev)",
                    "device_id": "Stable device slug",
                    "label": "Human-readable name",
                    "ip": "IPv4 address or null",
                    "mac": "IEEE 48-bit address or null",
                    "interface_id": "eth0/wlan0/primary/etc.",
                    "type": "ethernet/wifi/bluetooth/unknown/etc.",
                    "mac_source": "Where the MAC/interface was sourced from",
                    "ip_source": "Where the IP allocation was sourced from",
                    "network_id": "Network slug the IP belongs to (null if none)",
                    "network_status": "active/stale/unknown of the IP's network",
                    "status": "active/stale/unknown",
                    "ip_kind": "static/reservation/dhcp/discovered/manual",
                    "first_seen": "ISO-8601 date this row was first observed",
                    "last_seen": "ISO-8601 date this row was last observed (updated by scanner)",
                },
            }
        },
        "devices": all_rows,
    }

    ui_doc = {
        "title": "HA Devices UI",
        "subtitle": "UI SSOT for the apps/ha mini apps",
        "icon": "🏠",
        "config": {
            "version": 1,
            "last_updated": "2026-09-04",
            "maintainer": "tony",
            "status": "active",
            "source": "docs/ssot/infrastructure/ssot.ha-devices.yml",
        },
        "instances": ui_instances,
    }

    with OUT_SSOT.open("w", encoding="utf-8") as f:
        yaml.safe_dump(ssot_doc, f, sort_keys=False, allow_unicode=True, width=120)

    with OUT_UI.open("w", encoding="utf-8") as f:
        yaml.safe_dump(ui_doc, f, sort_keys=False, allow_unicode=True, width=120)

    print(f"Wrote {OUT_SSOT} ({len(all_rows)} rows)")
    print(f"Wrote {OUT_UI} ({len(ui_instances)} instances)")


if __name__ == "__main__":
    main()
