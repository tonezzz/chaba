#!/usr/bin/env python3
"""cam-wall roster audit — keeps each zone's cams_skip honest.

Runs on tony-dell (systemd timer, hourly). For every camwall zone:

  dead   — a pulled cam that has been ok=false for >= dead_hours gets
           moved into cams_skip (stops burning pull cycles on a corpse;
           the wall declutters and the CMS page reflects it next regen).
  revive — a cam WE auto-skipped gets its upstream probed (HTTP GET on
           the playlist/still URL); healthy again -> removed from
           cams_skip so it rejoins the wall automatically.
           Manually-skipped cams are left alone unless revive_manual.

Non-probeable kinds (vms/go2rtc/youtube) are never auto-skipped — their
failures are local infra, not upstream churn; dead_skip_kinds gates it.

Knobs live in ada-cms-automation doc 'cctv-roster' so Ada manages this
list herself via the cms_automation tool: enabled / interval_min /
run_now / dead_hours / min_skip_hours / revive_manual / zones /
dead_skip_kinds / max_changes / notify. Every change is logged to the
cctv-roster-audit CMS page, and changes ping Ada's /api/notify.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cam_wall_pull",
    Path(__file__).resolve().parent / "cam-wall-pull.py")
_pull = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pull)
ZONES, slug = _pull.ZONES, _pull.slug  # roster SSOT (registry + static)

BRIDGE = os.environ.get(
    "VCAST_API", "https://tony-dell.taila0626a.ts.net/api/input-bridge")
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1")
DATA = Path(os.environ.get(
    "CAMWALL_DATA",
    str(Path.home() / "CascadeProjects/chaba-tony-dell/stacks/web/public/apps/camwall/data")))
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
REG_KEY = "cctv-roster"
AUDIT_KEY = "cctv-roster-audit"
STATE = DATA / "_roster-audit-state.json"
NOTIFY_URL = os.environ.get(
    "ADA_NOTIFY_URL", "https://idc01.taila0626a.ts.net/api/notify")
NOTIFY_KEY = os.environ.get("ADA_NOTIFY_KEY") or os.environ.get(
    "ADA_API_KEY", "")
PROBEABLE = {"hls", "jpeg"}

DEFAULTS = {
    "enabled": True,
    "interval_min": 0,
    "run_now": False,
    "dead_hours": 24,
    "min_skip_hours": 6,
    "revive_manual": False,
    "zones": [],
    "dead_skip_kinds": ["hls", "jpeg"],
    "max_changes": 12,
    "notify": True,
}


def http_json(url: str, payload: dict | None = None,
              timeout: float = 15) -> dict:
    req = urllib.request.Request(
        url, headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def load_registry() -> dict:
    try:
        docs = http_json(f"{MDDB}/search",
                         {"collection": REGISTRY, "query": "", "limit": 500})
        for d in docs:
            if d.get("key") == REG_KEY:
                cfg = json.loads(d.get("contentMd") or "{}")
                return cfg if isinstance(cfg, dict) else {}
        return {}
    except Exception as exc:
        print(f"registry read failed ({exc}) — running on defaults",
              file=sys.stderr)
        return {}


def save_registry(cfg: dict) -> None:
    meta = {
        "kind": ["automation-config"], "bank": ["cms"], "scope": ["tony"],
        "status": ["active"], "source": ["api"], "slug": [REG_KEY],
        "subject": [REG_KEY], "attribute": ["automation"],
        "written_by": ["cam-wall-roster-audit"],
        "title": [f"CMS automation: {REG_KEY}"], "format": ["json"],
        "lang": ["en"],
        "updated": [datetime.now(timezone.utc).isoformat(timespec="seconds")],
    }
    try:
        http_json(f"{MDDB}/add", {"collection": REGISTRY, "key": REG_KEY,
                                  "lang": "en",
                                  "contentMd": json.dumps(
                                      cfg, ensure_ascii=False, indent=2),
                                  "meta": meta})
    except Exception as exc:
        print(f"registry write-back failed: {exc}", file=sys.stderr)


def gated(cfg: dict, force: bool) -> str | None:
    if not cfg.get("enabled", True):
        return "disabled"
    if force or cfg.get("run_now"):
        return None
    interval = int(cfg.get("interval_min") or 0)
    last = cfg.get("last_run")
    if interval and last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < \
                    last_dt + timedelta(minutes=interval):
                return f"interval (last run {last})"
        except ValueError:
            pass
    return None


def probe(urls: list[str], timeout: float = 8) -> bool:
    """Healthy = any URL answers 200 with bytes. For .m3u8 the playlist
    GET alone is meaningful — the observed upstream failure is a 404 on
    exactly this request."""
    for u in urls:
        try:
            req = urllib.request.Request(u, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status < 400 and r.read(64):
                    return True
        except Exception:
            continue
    return False


def roster_index(zone: str, extra_cams: list | None) -> dict[str, dict]:
    """cam key -> {label, kind, urls[]} for everything the zone COULD pull
    (skip-list applied nowhere — this is the full possible roster)."""
    out: dict[str, dict] = {}
    for c in (ZONES.get(zone) or {}).get("cams") or []:
        label, kind, url = c[0], c[1], c[2]
        alts = [u for u in c[3:] if isinstance(u, str)]
        out[slug(label)] = {"label": label, "kind": kind,
                            "urls": [url, *alts]}
    for e in extra_cams or []:
        label = e.get("label") or "cam"
        kind = e.get("kind") or "jpeg"
        out[slug(label)] = {"label": label, "kind": kind,
                            "urls": [e.get("url") or ""]}
    return out


def notify_ada(text: str) -> None:
    if not NOTIFY_KEY:
        return
    try:
        urllib.request.urlopen(urllib.request.Request(
            NOTIFY_URL, data=json.dumps(
                {"text": text[:400], "urgent": "0"}).encode(),
            headers={"Content-Type": "application/json",
                     "x-api-key": NOTIFY_KEY}), timeout=15).read()
    except Exception as exc:
        print(f"notify failed: {exc}", file=sys.stderr)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="ignore interval_min gating (still honors enabled)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg = {**DEFAULTS, **load_registry()}

    why = gated(cfg, args.force)
    if why:
        print(f"skipped ({why})")
        return 0

    started = time.monotonic()
    changes: list[str] = []
    errors = 0

    try:
        relay = http_json(f"{BRIDGE}/camwall")
    except Exception as exc:
        print(f"relay unreachable: {exc}", file=sys.stderr)
        return 2
    zones_state = relay.get("zones") or {}

    try:
        state = json.loads(STATE.read_text())
    except Exception:
        state = {}
    cams_state: dict = state.setdefault("cams", {})

    only = set(cfg.get("zones") or [])
    dead_kinds = set(cfg.get("dead_skip_kinds") or [])
    max_changes = int(cfg.get("max_changes") or 12)
    dead_s = float(cfg.get("dead_hours") or 24) * 3600
    min_skip_s = float(cfg.get("min_skip_hours") or 6) * 3600
    dirty_zones: dict[str, dict] = {}

    for zone in sorted(ZONES):
        if only and zone not in only:
            continue
        zstate = zones_state.get(zone) or {}
        zsettings = dict(zstate.get("settings") or {})
        skip = list(zsettings.get("cams_skip") or [])
        idx = roster_index(zone, zsettings.get("cams_extra"))
        try:
            man = json.loads(
                (DATA / zone / f"manifest-{zone}.json").read_text())
        except Exception:
            man = {"cams": []}
        pulled = {c["key"]: c for c in man.get("cams") or []}

        for key, cam in pulled.items():
            cs = cams_state.setdefault(f"{zone}/{key}", {})
            cs["label"] = cam.get("label")
            if cam.get("ok"):
                cs.pop("first_fail", None)
                continue
            cs.setdefault("first_fail", now_iso)
            info = idx.get(key) or {}
            if key in skip or info.get("kind") not in dead_kinds:
                continue
            try:
                ff = datetime.fromisoformat(
                    cs["first_fail"]).timestamp()
            except ValueError:
                ff = now
            if now - ff >= dead_s and len(changes) < max_changes:
                skip.append(key)
                cs.update(auto=True, skip_since=now_iso)
                changes.append(
                    f"skip {zone}/{key} ({cam.get('label')}) — dead "
                    f"{(now - ff) / 3600:.0f}h: "
                    f"{(cam.get('err') or '')[:80]}")
                dirty_zones[zone] = zsettings

        for key in list(skip):
            cs = cams_state.setdefault(f"{zone}/{key}", {})
            if not cs.get("auto") and not cfg.get("revive_manual"):
                continue  # hand-curated skip — not ours to touch
            try:
                ss = datetime.fromisoformat(
                    cs.get("skip_since") or "1970-01-01T00:00:00+00:00"
                ).timestamp()
            except ValueError:
                ss = 0
            if now - ss < min_skip_s:
                continue
            info = idx.get(key)
            if not info or info["kind"] not in PROBEABLE:
                continue
            if len(changes) >= max_changes:
                break
            if probe([u for u in info["urls"] if u]):
                skip.remove(key)
                cs.clear()
                cs["label"] = info["label"]
                changes.append(
                    f"revive {zone}/{key} ({info['label']}) — upstream "
                    f"answers again")
                dirty_zones[zone] = zsettings
            else:
                cs["last_probe"] = now_iso

        if zone in dirty_zones:
            zsettings["cams_skip"] = skip

    for zone, zsettings in dirty_zones.items():
        if args.dry_run:
            continue
        try:
            http_json(f"{BRIDGE}/camwall",
                      {"zone": zone, "settings": zsettings})
        except Exception as exc:
            errors += 1
            print(f"settings write {zone} failed: {exc}", file=sys.stderr)

    try:
        STATE.write_text(json.dumps(state))
    except Exception as exc:
        print(f"state write failed: {exc}", file=sys.stderr)

    # audit trail on the CMS page — a rolling timeline of every change
    if changes:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
        entry = "\n".join(f"- {c}" for c in changes)
        note = (f"## {stamp}\n\n{entry}\n\n")
        try:
            docs = http_json(f"{MDDB}/search", {
                "collection": COLLECTION, "query": "", "limit": 500})
            body = next((d.get("contentMd") or ""
                         for d in docs if d.get("key") == AUDIT_KEY), "")
        except Exception:
            body = ""
        if not body:
            body = ("# CCTV roster audit\n\n"
                    "cam-wall-roster-audit maintains each zone's "
                    "`cams_skip`: dead cams get skipped after "
                    "`dead_hours`, auto-skipped cams are probed and "
                    "rejoin the wall when upstream recovers. Knobs: "
                    "ada-cms-automation/`cctv-roster`.\n")
        body = body.rstrip() + "\n\n" + note
        # keep the page bounded — last ~60 change lines
        lines = body.splitlines()
        change_lines = [i for i, l in enumerate(lines)
                        if l.startswith("- ")]
        if len(change_lines) > 60:
            body = "\n".join(lines[:change_lines[-60]]) + "\n"
        if not args.dry_run:
            try:
                http_json(f"{MDDB}/add", {
                    "collection": COLLECTION, "key": AUDIT_KEY,
                    "lang": "en", "contentMd": body,
                    "meta": {
                        "kind": ["page"], "attribute": ["page"],
                        "bank": ["cms"], "slug": [AUDIT_KEY],
                        "subject": [AUDIT_KEY],
                        "title": ["CCTV roster audit"],
                        "format": ["markdown"], "lang": ["en"],
                        "domain": ["cctv"], "scope": ["tony"],
                        "status": ["active"], "source": ["api"],
                        "generated_by": ["cam-wall-roster-audit"],
                        "updated": [now_iso], "parent": ["cctv-walls"],
                        "summary": [
                            "Automated cams_skip hygiene — dead cams "
                            "skipped after dead_hours, revived when "
                            "upstream recovers. Change log."]}})
            except Exception as exc:
                errors += 1
                print(f"audit page write failed: {exc}", file=sys.stderr)
        if cfg.get("notify"):
            notify_ada("camwall roster: " + "; ".join(changes[:3]))

    for c in changes:
        print(c)
    if not changes:
        print("no changes")

    st = dict(cfg)
    st.update({"run_now": False, "last_run": now_iso,
               "last_status": "error" if errors else "ok",
               "last_count": len(changes),
               "last_duration_s": round(time.monotonic() - started, 1)})
    if errors:
        st["last_error"] = "see stderr — relay/mddb write failure"
    else:
        st.pop("last_error", None)
    if not args.dry_run:
        save_registry(st)
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
