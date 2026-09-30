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
    "noble-park": "Noble park facilities — swimming pool, tennis court, "
                  "playground, mini mart, guard view (VMS DVR).",
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
}


def http_get(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def mddb_add(key: str, md: str, title: str) -> bool:
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
            return r.status < 300
    except Exception as exc:
        print(f"mddb add {key}: {exc}", file=sys.stderr)
        return False


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
        f"| {c['label']} | {c['key']} | "
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
    return f"""# Wall: {zone}

{ZONE_INFO.get(zone, 'Camera wall zone.')}

![montage]({BASE}/data/{zone}/montage.jpg)

- **Wall URL**: `{BASE}/?zone={zone}` (cast via `cctv_wall zone={zone} screen=N`)
- **Refresh**: {'enabled' if zstate.get('enabled') else 'off (warm thumbs only)'} · interval {s.get('interval', 'default')}s
- **Status**: {len(live)}/{len(man['cams'])} cams live · {len(stale)} stale · {len(dead)} dead · manifest {age}s old
- **Effects**: {', '.join(s.get('effects') or ['none'])}
- **Knobs** (POST /camwall settings or `cctv_wall` settings): interval, jpeg_q, thumb_w, cams_skip, cams_extra, effects (timestamp, grid, yolo:classes@conf)

## Cameras

| camera | key | state |
|---|---|---|
{rows}
{det_block}
## For Ada

- "put the {zone} wall on screen N" → `cctv_wall(zone='{zone}', screen=N)`
  (ask before starting — it is a camera capture)
- status: {len(live)}/{len(man['cams'])} cams returning frames right now
- detection questions ("anyone at …?") are only answerable while the
  yolo effect is on — the window is the detections jsonl span.
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
"""


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
    for zone, m in zones.items():
        ok &= mddb_add(f"wall-{zone}", wall_page(
            zone, m["manifest"], m["state"]), f"Wall: {zone}")
    if zones:
        ok &= mddb_add("cctv-walls", index_page(zones),
                       "CCTV / traffic camera walls")
    print(f"walls: {len(zones)} pages + index {'ok' if ok else 'ERR'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
