#!/usr/bin/env python3
"""zones.yml loader — shared zone metadata for cam-wall-pull/-cms.

zones.yml (same directory) is the single SSOT for zone -> tab
classification and camera membership. Everything here is read-only
lookup over that file; nothing guesses from slug prefixes anymore.

Classification model:
  group: private|public  — the privacy semantic (set per zone / device)
  tab                    — the display label (Security/Traffic/…), looked
                           up in `tabs` by group unless a zone pins an
                           explicit `tab:` key. Unknown zones -> `unsorted`.
  site                   — compound grouping (noble-club, tony-house…)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ZONES_YML = Path(os.environ.get(
    "CAMWALL_ZONES_YML",
    str(Path(__file__).resolve().parent / "zones.yml")))

DEFAULT_TABS = {
    "private":  {"en": "Security", "th": "ความปลอดภัย"},
    "public":   {"en": "Traffic",  "th": "จราจร"},
    "unsorted": {"en": "Unsorted", "th": "ยังไม่จัดหมวด"},
}


def load() -> dict:
    """Parse zones.yml. Missing file -> warn + empty (callers degrade to
    'unsorted', they don't blank the wall); malformed YAML -> raise so a
    broken edit fails loudly on the timer instead of silently
    reclassifying the fleet."""
    import yaml
    try:
        text = ZONES_YML.read_text()
    except FileNotFoundError:
        print(f"zones.yml missing at {ZONES_YML} — all zones 'unsorted'",
              file=sys.stderr)
        return {}
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise ValueError(f"{ZONES_YML}: top-level mapping required")
    return doc


def zones(meta: dict) -> dict:
    return meta.get("zones") or {}


def tabs(meta: dict) -> dict:
    out = dict(DEFAULT_TABS)
    for k, v in (meta.get("tabs") or {}).items():
        out[k] = v if isinstance(v, dict) else {"en": str(v)}
    return out


def tab_label(tab_key: str, meta: dict, lang: str = "en") -> str:
    t = tabs(meta).get(tab_key) or {}
    return t.get(lang) or t.get("en") or tab_key


def zone_entry(zone: str, meta: dict) -> dict:
    return zones(meta).get(zone) or {}


def classify(zone: str, meta: dict) -> dict:
    """zone -> {group, site, tab, tab_key, area{en,th}, info{en,th}}.
    A zone absent from zones.yml classifies as group/tab 'unsorted' —
    the visible bucket, not a guess."""
    zd = zone_entry(zone, meta)
    group = zd.get("group") or "unsorted"
    tab_key = zd.get("tab") or group
    area = zd.get("area") or {}
    return {
        "group": group,
        "site": zd.get("site") or "",
        "tab": tab_label(tab_key, meta),
        "tab_key": tab_key,
        "tab_th": tab_label(tab_key, meta, "th"),
        "area": area.get("en") or zone,
        "area_th": area.get("th") or area.get("en") or zone,
        "info": zd.get("info") or {},
    }


def device_entry(dev: str, meta: dict) -> dict:
    return (meta.get("devices") or {}).get(dev) or {}


def cam_classify(zone: str, cam: dict, meta: dict) -> dict:
    """A camera's canonical class is its DVR device when known, else the
    zone it's classified under. Returns {group, site, tab, area…}."""
    dev = cam.get("dev") or ""
    dd = device_entry(dev, meta)
    if dd:
        zc = classify(zone, meta)
        group = dd.get("group") or zc["group"]
        tab_key = dd.get("tab") or group
        area = dd.get("area") or {}
        return {
            "group": group,
            "site": dd.get("site") or zc["site"],
            "tab": tab_label(tab_key, meta),
            "tab_key": tab_key,
            "tab_th": tab_label(tab_key, meta, "th"),
            "area": area.get("en") or zc["area"],
            "area_th": area.get("th") or zc["area_th"],
            "info": zc["info"],
        }
    return classify(zone, meta)


def labels(meta: dict) -> dict:
    """slug(label) -> display label overrides."""
    return meta.get("labels") or {}


def pull_zones(meta: dict) -> dict:
    """zone -> {interval, warm, cams} for the puller — static cams only;
    registry_group zones are expanded by the puller from cameras.json."""
    out = {}
    for name, zd in zones(meta).items():
        if not isinstance(zd, dict):
            continue
        cams = [tuple(c) for c in (zd.get("cams") or [])]
        out[name] = {
            "interval": int(zd.get("interval") or 120),
            "warm": int(zd.get("warm") or 900),
            "cams": cams,
            "registry_group": zd.get("registry_group") or "",
        }
    return out
