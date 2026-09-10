#!/usr/bin/env python3
"""Regenerate the Dossier 'Devices' view from SSOT and push to HA.

Sources:
- docs/ssot/infrastructure/ssot.ha-devices.yml

Targets:
- tony-ha:  /home/tony/.config/home-assistant/lovelace-dossier.yaml + live push
- michael-ha: live push only (no local config file)

Usage:
    python3 scripts/build-dossier-devices.py [tony-ha|michael-ha|all]

Tokens are read from:
- tony-ha:  ~/.config/secrets/home-assistant-token.env (HA_LONG_LIVED_TOKEN)
- michael-ha: ~/.local/share/home-assistant-michael/ha-token
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import websockets
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SSOT_PATH = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.ha-devices.yml"

INSTANCES = {
    "tony-ha": {
        "ha_url": "ws://tony-dell:8123/api/websocket",
        "token_file": Path.home() / ".config" / "secrets" / "home-assistant-token.env",
        "token_kind": "env",
    },
    "michael-ha": {
        "ha_url": "ws://michael-ha:8123/api/websocket",
        "token_file": Path.home() / ".local" / "share" / "home-assistant-michael" / "ha-token",
        "token_kind": "raw",
    },
}


def load_token(path: Path, kind: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Token file not found: {path}")
    text = path.read_text().strip()
    if kind == "env":
        for line in text.splitlines():
            m = re.match(r"^HA_LONG_LIVED_TOKEN=(.+)$", line.strip())
            if m:
                return m.group(1)
        raise ValueError(f"HA_LONG_LIVED_TOKEN not found in {path}")
    return text


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _status_badge(status: str) -> str:
    color = {"active": "#4caf50", "stale": "#f44336"}.get(status, "#ff9800")
    return f'<span style="color:{color};font-weight:600">{status}</span>'


def _type_label(typ: str) -> str:
    color = {"ethernet": "#03a9f4", "wifi": "#8bc34a", "bluetooth": "#9c27b0"}.get(typ, "var(--secondary-text-color)")
    return f'<span style="color:{color}">{typ}</span>'


def _needs_lookup(r: dict) -> bool:
    if not r.get("mac"):
        return False
    typ = r.get("type") or "unknown"
    did = r.get("device_id") or ""
    label = r.get("label") or ""
    return typ == "unknown" or did.startswith("discovered") or label.lower().startswith("unknown")


def _mac_cell(r: dict) -> str:
    mac = r.get("mac")
    if not mac:
        return "—"
    if _needs_lookup(r):
        return f'<a href="https://macvendors.com/lookup/{mac}" target="_blank" rel="noopener">{mac}</a>'
    return mac


def _table(rows: list[dict]) -> str:
    trs = []
    for r in rows:
        label = r.get("label") or r.get("device_id", "")
        iface = r.get("interface_id") or ""
        mac = _mac_cell(r)
        raw_ip = r.get("ip")
        ip = f'<a href="http://{raw_ip}" target="_blank" rel="noopener">{raw_ip}</a>' if raw_ip else "—"
        typ = r.get("type") or "unknown"
        status = r.get("status") or "unknown"
        mac_source = r.get("mac_source") or ""
        ip_source = r.get("ip_source") or ""
        source = f"{mac_source} / {ip_source}" if (mac_source and ip_source) else (mac_source or ip_source or "—")
        ip_kind = r.get("ip_kind") or "—"
        seen = r.get("first_seen") or "—"
        trs.append(
            f'<tr><td style="word-break:break-all">{label}</td><td>{iface}</td>'
            f'<td style="word-break:break-all">{mac}</td><td style="word-break:break-all">{ip}</td>'
            f'<td>{_type_label(typ)}</td><td>{_status_badge(status)}</td><td>{source}</td><td>{ip_kind}</td>'
            f'<td style="word-break:break-all">{seen}</td></tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;font-size:0.85em">\n'
        '<thead><tr>\n'
        '<th style="text-align:left;width:24%">Device</th>\n'
        '<th style="text-align:left;width:8%">Iface</th>\n'
        '<th style="text-align:left;width:16%">MAC</th>\n'
        '<th style="text-align:left;width:12%">IP</th>\n'
        '<th style="text-align:left;width:8%">Type</th>\n'
        '<th style="text-align:left;width:8%">Status</th>\n'
        '<th style="text-align:left;width:8%">Source</th>\n'
        '<th style="text-align:left;width:8%">IP kind</th>\n'
        '<th style="text-align:left;width:8%">Seen</th>\n'
        '</tr></thead>\n'
        '<tbody>\n' + '\n'.join(trs) + '\n</tbody></table>'
    )


def _section(title: str, rows: list[dict]) -> str:
    active = sum(1 for r in rows if r.get("status") == "active")
    stale = sum(1 for r in rows if r.get("status") == "stale")
    unknown = sum(1 for r in rows if r.get("status") == "unknown")
    no_mac = sum(1 for r in rows if not r.get("mac"))
    no_ip = sum(1 for r in rows if not r.get("ip"))
    return (
        f"### {title}\n\n"
        f"**{len(rows)} interfaces** — {active} active, {stale} stale, {unknown} unknown "
        f"· {no_mac} without MAC, {no_ip} without IP\n\n"
        + _table(rows)
    )


def build_table_content(rows: list[dict], last_updated: str, instance: str) -> str:
    if not rows:
        return f"No devices found. Last updated: {last_updated}\n\n"

    def is_active(r: dict) -> bool:
        return r.get("status") == "active" and r.get("network_status") != "stale"

    active_rows = [r for r in rows if is_active(r)]
    legacy_rows = [r for r in rows if not is_active(r)]

    parts = [f"**Last updated:** {last_updated} · Sources: [{instance} SSOT](/local/ha/ssot.{instance}.yml)\n\n"]
    if active_rows:
        parts.append(_section("Active devices", active_rows))
    if legacy_rows:
        parts.append(_section("Stale / Legacy devices", legacy_rows))
    return "\n\n".join(parts)


def devices_view_for_instance(instance: str, ssot: dict) -> dict:
    rows = [d for d in ssot.get("devices", []) if d.get("ha_instance") == instance]
    last_updated = ssot.get("config", {}).get("last_updated", "—")
    content = build_table_content(rows, last_updated, instance)
    return {
        "title": "Devices",
        "path": "devices",
        "icon": "mdi:devices",
        "type": "panel",
        "cards": [
            {
                "type": "markdown",
                "title": f"{instance.replace('-', ' ').title()} Devices",
                "content": content,
            }
        ],
    }


async def build_and_push(instance: str) -> None:
    if instance not in INSTANCES:
        raise ValueError(f"Unknown instance: {instance}")

    spec = INSTANCES[instance]
    token = load_token(spec["token_file"], spec["token_kind"])
    ssot = load_yaml(SSOT_PATH)
    view = devices_view_for_instance(instance, ssot)

    async with websockets.connect(spec["ha_url"]) as ws:
        async def cmd(payload: dict) -> dict:
            cmd.i = getattr(cmd, "i", 1) + 1
            payload["id"] = cmd.i
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == cmd.i:
                    return r

        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA auth failed: {auth}")

        resp = await cmd({"type": "lovelace/config", "url_path": "dossier"})
        config = resp.get("result") or {"title": "Dossier", "views": []}

    for i, v in enumerate(config.get("views", [])):
        if v.get("path") == "devices":
            config["views"][i] = view
            break
    else:
        config.setdefault("views", []).insert(0, view)

    async with websockets.connect(spec["ha_url"]) as ws:
        async def cmd(payload: dict) -> dict:
            cmd.i = getattr(cmd, "i", 1) + 1
            payload["id"] = cmd.i
            await ws.send(json.dumps(payload))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == cmd.i:
                    return r

        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"HA auth failed: {auth}")

        resp = await cmd({"type": "lovelace/config/save", "url_path": "dossier", "config": config})
        if not resp.get("success"):
            raise RuntimeError(f"Save failed: {resp.get('error')}")

    print(f"Pushed {instance} Devices view ({len(ssot.get('devices', []))} total rows in SSOT)")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target not in ("all", *INSTANCES.keys()):
        print(f"Usage: {sys.argv[0]} [all|tony-ha|michael-ha]")
        sys.exit(1)

    targets = list(INSTANCES.keys()) if target == "all" else [target]
    for inst in targets:
        asyncio.run(build_and_push(inst))


if __name__ == "__main__":
    main()
