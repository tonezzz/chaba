#!/usr/bin/env python3
"""cam-wall CMS generator — one 'wall-<zone>' page per camera wall plus a
'cctv-walls' index, written into the ada-cms-pages MDDB collection.

Runs on tony-dell (systemd timer ~15min, or on demand). Sources:
  - relay /camwall          -> enabled flag + live settings knobs
  - data/<zone>/manifest-*  -> cam roster, ok/err, freshness, detections
  - data/<zone>/detections-*-> rolling detection window (yolo effect on)
  - data/<zone>/montage.jpg -> composite tile for the index page

The pages are what Ada reads when asked about a wall — so they carry
plain-language coverage notes, the roster, live health, the knobs that
exist (and the cctv_wall call to change them), and recent detections.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BRIDGE = os.environ.get(
    "VCAST_API", "https://tony-dell.taila0626a.ts.net/api/input-bridge")
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1")
DATA = Path(os.environ.get(
    "CAMWALL_DATA",
    str(Path.home() / "CascadeProjects/chaba-tony-dell/stacks/web/public/apps/camwall/data")))
BASE = "https://tony-dell.taila0626a.ts.net/apps/camwall"
COLLECTION = "ada-cms-pages"

# zone -> human coverage note (what Ada should say it watches)
ZONE_INFO = {
    "zone-a": "Noble-A estate perimeter — the roads in/out, walkway, "
              "guard view and road corner (VMS DVR, P2P uplink).",

    "vms-noble-club": "Every channel on the Noble-Club DVR — laundry/"
                      "washing machines, stairway room, mini mart, front "
                      "roads, pool, tennis, playground.",
    "vms-noble-a": "Every channel on the Noble-A DVR — road in, guard "
                   "view, walkway, road corner, CAM01.",
    "tony-house": "Tony's house cams — C100, C201, the coffee-corner "
                  "ip-cam (go2rtc, local).",
    "rama9": "Rama 9 demo traffic wall — Petchaburi Rd and Sukhumvit "
             "Soi 11 YouTube cams plus iTIC Rama 4 / Sathorn stills.",
    "traffic": "DOH Bangkok traffic cams from the camera registry "
               "(frigate/cameras.json) — HLS playlists snapshotted.",
    "burapha": "Bangna–Burapha expressway cams (registry group "
               "ทางพิเศษบูรพาวิถี).",
    "chonburi": "Chonburi corridor cams (registry group ชลบุรี).",
    "dohweb": "DOH national highway cams (กล้องกรมทางหลวง) — Wowza HLS on "
              "the DOH survey-station network (PER_* site codes, same feeds "
              "DOHWeb maps); Bangkok ring + upcountry trunk roads.",
}

# zone -> display area for page titles: "CCTV Wall: <Area>"
AREA = {
    "zone-a": "Noble-A Estate",

    "vms-noble-club": "Noble Club",
    "vms-noble-a": "Noble-A",
    "tony-house": "Tony House",
    "rama9": "Rama 9 Traffic",
    "traffic": "Bangkok Traffic",
    "burapha": "Burapha Expressway",
    "chonburi": "Chonburi Corridor",
    "dohweb": "DOH Highways",
}

# VMS DVR device -> display area (a camera's canonical area is its DVR,
# not whichever wall happens to list it)
DEV_AREA = {"noble-club": "Noble Club", "noble-a": "Noble-A"}


def cam_slug(zone: str, cam: dict) -> str:
    """Canonical cam-page key. VMS cams key on <device>-<camkey> so the
    same physical camera is ONE page even when several walls list it
    (zone-a & vms-noble-a both carry '1. Road In')."""
    dev = cam.get("dev")
    return f"cam-{dev}-{cam['key']}" if dev else f"cam-{zone}-{cam['key']}"


def cam_area(zone: str, cam: dict) -> str:
    return DEV_AREA.get(cam.get("dev") or "", AREA.get(zone, zone))


def http_get(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


# publish dedup: MDDB writes re-embed the doc, so we only POST when the
# rendered markdown actually changed (per-key sha256 of content).
PUB_HASH = DATA / "_cms-pub-hash.json"
try:
    _pub_hash: dict[str, str] = json.loads(PUB_HASH.read_text())
except Exception:
    _pub_hash = {}


def mddb_add(key: str, md: str, title: str) -> bool:
    import hashlib
    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    hkey = f"{key}:en"
    if _pub_hash.get(hkey) == h:
        return True  # unchanged — skip write + re-embedding
    body = json.dumps({
        "collection": COLLECTION, "key": key, "lang": "en",
        "contentMd": md,
        "meta": {"kind": ["page"], "slug": [key], "title": [title],
                 "format": ["markdown"], "lang": ["en"],
                 "updated": [time.strftime(
                     "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())],
                 "instance": ["cam-wall-cms"]},
    }).encode()
    req = urllib.request.Request(
        f"{MDDB}/add", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status < 300:
                _pub_hash[hkey] = h
                try:
                    PUB_HASH.write_text(json.dumps(_pub_hash))
                except Exception:
                    pass
                return True
            return False
    except Exception as exc:
        print(f"mddb add {key}: {exc}", file=sys.stderr)
        return False


def mddb_delete(key: str) -> None:
    """Remove a superseded page (e.g. cam-<zone>-* replaced by the
    canonical cam-<dev>-* key)."""
    body = json.dumps({"collection": COLLECTION, "key": key,
                       "lang": "en"}).encode()
    req = urllib.request.Request(
        f"{MDDB}/delete", data=body,
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        _pub_hash.pop(f"{key}:en", None)
    except Exception as exc:
        print(f"mddb delete {key}: {exc}", file=sys.stderr)


DET_MAX_BYTES = 8 * 1024 * 1024   # ~14d of hourly-ish sweeps


def _det_recs(zone: str) -> list[dict]:
    """Read the rolling detection log; trim it past DET_MAX_BYTES so a
    long-running yolo wall doesn't grow the file unboundedly."""
    f = DATA / zone / f"detections-{zone}.jsonl"
    if not f.exists():
        return []
    try:
        if f.stat().st_size > DET_MAX_BYTES:
            lines = f.read_text().splitlines()
            f.write_text("\n".join(lines[-50_000:]) + "\n")
        return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    except Exception:
        return []


def detections_tail(zone: str, n: int = 24) -> tuple[str, str]:
    """Summarize the rolling detection log — latest window + span."""
    recs = _det_recs(zone)[-n:]
    if not recs:
        return "", ""
    from collections import Counter
    counts: Counter = Counter()
    for r in recs:
        for cams_dets in r.get("cams", {}).values():
            for d in cams_dets:
                counts[d["cls"]] += 1
    span = time.strftime("%H:%M", time.localtime(recs[0]["ts"])) + \
        "–" + time.strftime("%H:%M", time.localtime(recs[-1]["ts"]))
    top = ", ".join(f"{k}×{v}" for k, v in counts.most_common(8))
    return span, top


def detections_timeline(zone: str, hours: int = 24) -> str:
    """Hourly detection counts per cam over the last `hours` — the CMS
    comparison table Tony asked for (2026-09-30)."""
    recs = [r for r in _det_recs(zone)
            if r.get("ts", 0) > time.time() - hours * 3600]
    if not recs:
        return ""
    from collections import Counter, defaultdict
    # hour -> cam -> class counts
    grid: dict[str, dict[str, Counter]] = defaultdict(
        lambda: defaultdict(Counter))
    cams: set[str] = set()
    for r in recs:
        hr = time.strftime("%H:00", time.localtime(r["ts"]))
        for cam_key, dets in (r.get("cams") or {}).items():
            cams.add(cam_key)
            for d in dets:
                grid[hr][cam_key][d["cls"]] += 1
    cam_list = sorted(cams)
    header = "| hour | " + " | ".join(cam_list) + " |"
    sep = "|---|" + "---|" * len(cam_list)
    rows = []
    for hr in sorted(grid, reverse=True):
        cells = []
        for cam in cam_list:
            c = grid[hr].get(cam)
            cells.append(", ".join(f"{k}×{v}" for k, v in
                                   c.most_common(3)) if c else "—")
        rows.append(f"| {hr} | " + " | ".join(cells) + " |")
    return (f"\n## Detection timeline (last {hours}h)\n\n"
            + header + "\n" + sep + "\n" + "\n".join(rows) + "\n")


def wall_page(zone: str, man: dict, zstate: dict) -> str:
    s = zstate.get("settings") or {}
    live = [c for c in man["cams"] if c.get("ok")]
    stale = [c for c in man["cams"] if not c.get("ok") and c.get("ts")]
    dead = [c for c in man["cams"] if not c.get("ok") and not c.get("ts")]
    age = int(time.time() - man.get("updated", 0))
    det_span, det_top = detections_tail(zone)
    rows = "\n".join(
        f"| [{c['label']}](https://idc01.taila0626a.ts.net/cms/#{cam_slug(zone, c)}) | {c['key']} | "
        + ("live" if c.get("ok") else "down")
        + (f" · {int(time.time()-c['ts'])}s old" if c.get("ts") else "")
        + (f" · {c['err']}" if c.get("err") else "")
        + " |"
        for c in man["cams"])
    det_block = ""
    if det_top:
        det_block = (f"\n## Detections (yolo, window {det_span})\n\n"
                     f"latest sweep: {det_top}\n\n"
                     f"Raw log: `data/{zone}/detections-{zone}.jsonl` "
                     "(append-only while the yolo effect is on).\n")
    det_block += detections_timeline(zone)
    return f"""# CCTV Wall: {AREA.get(zone, zone)} (`{zone}`)

{ZONE_INFO.get(zone, 'Camera wall zone.')}

![montage]({BASE}/data/{zone}/montage.jpg)

- **Wall URL**: `{BASE}/?zone={zone}` (cast via `cctv_wall zone={zone} screen=N`)
- **Refresh**: {'enabled' if zstate.get('enabled') else 'off (warm thumbs only)'} · interval {s.get('interval', 'default')}s
- **Status**: {len(live)}/{len(man['cams'])} cams live · {len(stale)} stale · {len(dead)} dead · manifest {age}s old
- **Effects**: {', '.join(s.get('effects') or ['none'])}

Controls, status-card standard and Ada usage → `cctv-walls`
(shared — kept on the index so wall pages carry data only).

## Cameras

| camera | key | state |
|---|---|---|
{rows}
{det_block}
"""


def cam_dets(zone: str, cam_key: str, hours: int = 24) -> tuple[str, str]:
    """Per-cam detection roll-up: 24h class counts + last-seen time."""
    cutoff = time.time() - hours * 3600
    counts: dict[str, int] = {}
    last = 0
    for r in _det_recs(zone):
        if r.get("ts", 0) < cutoff:
            continue
        for d in (r.get("cams") or {}).get(cam_key) or []:
            counts[d["cls"]] = counts.get(d["cls"], 0) + 1
            last = max(last, r["ts"])
    if not counts:
        return "", ""
    top = ", ".join(f"{k}×{v}" for k, v in
                    sorted(counts.items(), key=lambda x: -x[1]))
    return top, time.strftime("%H:%M", time.localtime(last))


def cam_page(slug_key: str, entries: list[tuple[str, dict, dict]]) -> str:
    """One CMS dossier per PHYSICAL camera — `entries` is every
    (zone, cam, manifest) that lists it; the freshest one supplies the
    image/state. Data-only (standard lives on cctv-walls); state uses
    coarse buckets so unchanged cams hash-identical and skip republish."""
    # freshest manifest entry wins for the still/state
    zone, cam, man = max(
        entries, key=lambda e: e[2].get("updated") or 0)
    key = cam["key"]
    ok = cam.get("ok")
    err = cam.get("err") or ""
    ts = cam.get("ts") or 0
    age = int(time.time() - ts) if ts else None
    bucket = time.strftime("%Y-%m-%d %H:%M",
                           time.localtime((man.get("updated") or 0)
                                          // 300 * 300))
    if ok:
        state = "live"
    elif ts:
        state = f"stale — last frame {age}s ago"
    else:
        state = "down — no frame on record"
    det_top, det_last = cam_dets(zone, key)
    det_line = (f"{det_top} (last seen {det_last}, 24h window)"
                if det_top else "none in window")
    walls = ", ".join(f"[{z}]({BASE}/?zone={z})"
                      for z, _, _ in sorted(
                          entries, key=lambda e: e[0]))
    ident = (f"- **Source**: `{cam['dev']}` DVR · channel `{cam['ch']}`\n"
             if cam.get("dev") else "")
    return f"""# CCTV: {cam_area(zone, cam)} — {cam['label']}

![latest]({BASE}/data/{zone}/{key}.jpg)

{ident}- **Walls**: {walls} (`wall-{"`, `wall-".join(
        sorted({z for z, _, _ in entries}))}`)
- **State**: {state} · manifest as of {bucket}
{f"- **Error**: {err}" if err else ""}
- **Detections**: {det_line}

Part of `cctv-walls` — camera dossier for `{slug_key}`.
"""


def index_page(zones: dict[str, dict]) -> str:
    rows = []
    for zone, m in sorted(zones.items()):
        man = m["manifest"]
        live = sum(1 for c in man["cams"] if c.get("ok"))
        age = int(time.time() - man.get("updated", 0))
        st = m["state"]
        eff = (st.get("settings") or {}).get("effects") or []
        rows.append(
            f"| [{zone}]({BASE}/?zone={zone}) | "
            f"![{zone}]({BASE}/data/{zone}/montage.jpg) | "
            f"{live}/{len(man['cams'])} | "
            f"{'on' if st.get('enabled') else 'warm'} · {age}s | "
            f"{', '.join(eff) or '—'} |")
    return f"""# CCTV / traffic camera walls

One wall per area — each is a live grid page plus a CMS dossier page
(`wall-<zone>`). Cast with `cctv_wall`; tune with the ⚙ drawer on the
wall page or `cctv_wall settings`.

| wall | montage | cams live | refresh | effects |
|---|---|---|---|---|
{chr(10).join(rows)}

Detail pages: {', '.join(f'`wall-{z}`' for z in sorted(zones))}

## Controls (shared by every wall)

- **Cast**: `cctv_wall(zone='<zone>', screen=N)` — or open
  `{BASE}/?zone=<zone>` on any browser. Ask before casting: it is a
  camera capture.
- **Knobs** — ⚙ drawer on the wall page, POST /camwall settings, or
  `cctv_wall` settings: `interval`, `jpeg_q`, `thumb_w`, `cams_skip`,
  `cams_extra`, `effects` (timestamp, grid, yolo:classes@conf).
- **Dead cams render status cards**, not broken images: STALE (dimmed
  last-good, <6h) · DELAYED (budget skip) · OFFLINE (no/ancient frame)
  · NO SIGNAL (other). Standard: `docs/ssot/apps/ssot.apps.camwall.yml`.
- **Detections** ("anyone at …?") are answerable only while the yolo
  effect is on — each wall page shows its detections jsonl window.
"""


NOTIFY_URL = os.environ.get(
    "ADA_NOTIFY_URL", "https://idc01.taila0626a.ts.net/api/notify")
NOTIFY_KEY = os.environ.get("ADA_NOTIFY_KEY") or os.environ.get(
    "ADA_API_KEY", "")
NOTIFY_STATE = DATA / "_cms-notify-state.json"


def notify_ada(text: str) -> None:
    """Ping Ada's /api/notify so she relays a wall-state transition to Tony.
    Non-urgent — lands as a deferred note, never hijacks a turn."""
    if not NOTIFY_KEY:
        return
    body = json.dumps({"text": text[:400], "urgent": "0"}).encode()
    req = urllib.request.Request(
        NOTIFY_URL, data=body,
        headers={"Content-Type": "application/json",
                 "x-api-key": NOTIFY_KEY})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as exc:
        print(f"notify failed: {exc}", file=sys.stderr)


def notify_transitions(zones: dict[str, dict]) -> None:
    """Compare live-counts against the last published state and notify Ada
    only on meaningful transitions — zone recovered, zone went all-dead,
    or a wall page published for the first time. Routine churn is silent."""
    try:
        prev = json.loads(NOTIFY_STATE.read_text())
    except Exception:
        prev = {}
    cur: dict[str, int] = {}
    notes = []
    for zone, m in zones.items():
        cams = m["manifest"].get("cams") or []
        live = sum(1 for c in cams if c.get("ok"))
        cur[zone] = live
        if zone not in prev:
            continue  # first sighting — record, don't announce
        was = prev[zone]
        if was == 0 and live > 0:
            notes.append(
                f"camwall {zone} recovered — {live}/{len(cams)} cams live "
                f"again (wall-{zone} updated)")
        elif was > 0 and live == 0:
            notes.append(
                f"camwall {zone} went all-dead — 0/{len(cams)} live "
                f"(wall-{zone} updated)")
    try:
        NOTIFY_STATE.write_text(json.dumps(cur))
    except Exception:
        pass
    for n in notes[:4]:  # cap: a DVR fleet flap can hit every zone at once
        notify_ada(n)


def main() -> int:
    try:
        state = http_get(BRIDGE + "/camwall")
    except Exception as exc:
        print(f"relay unreachable: {exc}", file=sys.stderr)
        state = {"zones": {}}
    zstate = state.get("zones") or {}
    zones: dict[str, dict] = {}
    for zdir in sorted(DATA.iterdir()):
        if not zdir.is_dir():
            continue
        zone = zdir.name
        mf = zdir / f"manifest-{zone}.json"
        if not mf.exists():
            continue
        try:
            man = json.loads(mf.read_text())
        except Exception:
            continue
        zones[zone] = {"manifest": man,
                       "state": zstate.get(zone) or {}}
    ok = True
    # group cams by canonical slug — one dossier per physical camera
    cam_groups: dict[str, list[tuple[str, dict, dict]]] = {}
    for zone, m in zones.items():
        ok &= mddb_add(f"wall-{zone}", wall_page(
            zone, m["manifest"], m["state"]),
            f"CCTV Wall: {AREA.get(zone, zone)}")
        for c in m["manifest"].get("cams") or []:
            cam_groups.setdefault(cam_slug(zone, c), []).append(
                (zone, c, m["manifest"]))
    cam_pages = len(cam_groups)
    for slug_key, entries in sorted(cam_groups.items()):
        _, cam, _ = max(entries, key=lambda e: e[2].get("updated") or 0)
        zone, _cam, _ = entries[0]
        ok &= mddb_add(slug_key, cam_page(slug_key, entries),
                       f"CCTV: {cam_area(zone, cam)} — {cam['label']}")
        # retire the old zone-scoped key the canonical dev-key replaced
        for z, c, _ in entries:
            legacy = f"cam-{z}-{c['key']}"
            if legacy != slug_key:
                mddb_delete(legacy)
    if zones:
        ok &= mddb_add("cctv-walls", index_page(zones),
                       "CCTV Camera Walls")
        notify_transitions(zones)
    print(f"walls: {len(zones)} pages + {cam_pages} cams + index "
          f"{'ok' if ok else 'ERR'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
