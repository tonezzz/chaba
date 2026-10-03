#!/usr/bin/env python3
"""cam-wall CMS generator — one 'camwall-<area>' page per camera wall plus
a 'cctv-walls' index, written into the ada-cms-pages MDDB collection.

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
import urllib.error
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
ZONE_INFO_TH = {
    "vms-noble-club": "ทุกช่องกล้องบน DVR โนเบิล คลับ — ห้องซักผ้า "
                      "ห้องบันได มินิมาร์ท ถนนหน้าสองฝั่ง สระว่ายน้ำ "
                      "สนามเทนนิส และสนามเด็กเล่น",
    "vms-noble-a": "ทุกช่องกล้องบน DVR โนเบิล-เอ — ถนนขาเข้า มุมมองยาม "
                   "ทางเดินเข้า หัวมุมถนน และ CAM01",
    "tony-house": "กล้องบ้านโทนี่ — C100, C201 และกล้องมุมกาแฟ "
                  "(go2rtc เครือข่ายภายใน)",
    "rama9": "กำแพงจราจรตัวอย่างพระราม 9 — กล้องยูทูบถนนเพชรบุรีและ"
             "สุขุมวิท 11 บวกภาพนิ่ง iTIC พระราม 4 / สาทร",
    "traffic": "กล้องจราจรกรุงเทพของ DOH จากทะเบียนกล้อง "
               "(frigate/cameras.json) — ดึงเฟรมจาก HLS playlist",
    "burapha": "กล้องทางพิเศษบูรพาวิถี ช่วงบางนา (กลุ่ม "
               "ทางพิเศษบูรพาวิถี ในทะเบียน)",
    "chonburi": "กล้องเส้นทางชลบุรี (กลุ่ม ชลบุรี ในทะเบียน)",
    "dohweb": "กล้องทางหลวงทั่วประเทศของกรมทางหลวง — Wowza HLS บนเครือข่าย"
              "สถานีสำรวจ DOH (รหัส PER_*) เส้นรอบนอกกรุงเทพและทางหลวงสายหลัก"
              "ต่างจังหวัด",
}

# zone -> display area for page titles: "CCTV Wall: <Area>"
AREA = {
    "vms-noble-club": "Noble Club",
    "vms-noble-a": "Noble-A",
    "tony-house": "Tony House",
    "rama9": "Rama 9 Traffic",
    "traffic": "Bangkok Traffic",
    "burapha": "Burapha Expressway",
    "chonburi": "Chonburi Corridor",
    "dohweb": "DOH Highways",
}
AREA_TH = {
    "Noble Club": "โนเบิล คลับ",
    "Noble-A": "โนเบิล-เอ",
    "Tony House": "บ้านโทนี่",
    "Rama 9 Traffic": "จราจรพระราม 9",
    "Bangkok Traffic": "จราจรกรุงเทพ",
    "Burapha Expressway": "ทางพิเศษบูรพาวิถี",
    "Chonburi Corridor": "ชลบุรี",
    "DOH Highways": "ทางหลวง DOH",
}

# VMS DVR device -> display area (a camera's canonical area is its DVR,
# not whichever wall happens to list it)
DEV_AREA = {"noble-club": "Noble Club", "noble-a": "Noble-A"}

# cam label -> Thai (proper nouns / traffic registry names stay as-is)
LABEL_TH = {
    "Washing Machines": "ห้องซักผ้า",
    "Stairway Room": "ห้องบันได",
    "Mini Mart": "มินิมาร์ท",
    "Front Rd Left": "ถนนหน้า ฝั่งซ้าย",
    "Front Rd Right": "ถนนหน้า ฝั่งขวา",
    "Swimming Pool": "สระว่ายน้ำ",
    "Tennis Court": "สนามเทนนิส",
    "Play Ground": "สนามเด็กเล่น",
    "Road In": "ถนนขาเข้า",
    "Guard View": "มุมมองยาม",
    "Walkway In": "ทางเดินเข้า",
    "Walkway": "ทางเดิน",
    "Road Corner": "หัวมุมถนน",
    "C100": "กล้อง C100",
    "C201": "กล้อง C201",
    "Coffee Corner": "มุมกาแฟ",
    "IP65 Low": "กล้อง IP65 มุมต่ำ",
}


def _t(lang: str, en: str, th: str) -> str:
    return th if lang == "th" else en


def _area(area: str, lang: str) -> str:
    return AREA_TH.get(area, area) if lang == "th" else area


def _label(cam: dict, lang: str) -> str:
    return LABEL_TH.get(cam["label"], cam["label"]) if lang == "th" \
        else cam["label"]


def cam_slug(zone: str, cam: dict) -> str:
    """Canonical cam-page key. VMS cams key on <device>-<camkey> so the
    same physical camera is ONE page even when several walls list it
    (a retired wall may share channels with a per-DVR wall)."""
    dev = cam.get("dev")
    return f"cam-{dev}-{cam['key']}" if dev else f"cam-{zone}-{cam['key']}"


def cam_area(zone: str, cam: dict) -> str:
    return DEV_AREA.get(cam.get("dev") or "", AREA.get(zone, zone))


def wall_key(zone: str) -> str:
    """CMS key for a wall page — `camwall-<area>` (the `vms-` prefix is a
    transport detail, not part of the wall name)."""
    return "camwall-" + (zone[4:] if zone.startswith("vms-") else zone)


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


def mddb_add(key: str, md: str, title: str, lang: str = "en",
             summary: str = "", parent: str = "cctv-walls") -> bool:
    import hashlib
    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    hkey = f"{key}:{lang}"
    if _pub_hash.get(hkey) == h:
        return True  # unchanged — skip write + re-embedding
    meta = {
        "kind": ["page"], "attribute": ["page"], "bank": ["cms"],
        "slug": [key], "subject": [key], "title": [title],
        "format": ["markdown"], "lang": [lang],
        "domain": ["cctv"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "generated_by": ["cam-wall-cms"],
        "fresh_for": ["600"],
        "updated": [time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                  time.gmtime())],
        "instance": ["cam-wall-cms"],
    }
    if summary:
        meta["summary"] = [summary]
    if parent:
        meta["parent"] = [parent]
    body = json.dumps({
        "collection": COLLECTION, "key": key, "lang": lang,
        "contentMd": md, "meta": meta,
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
    canonical cam-<dev>-* key). Deletes both lang variants."""
    for lang in ("en", "th"):
        body = json.dumps({"collection": COLLECTION, "key": key,
                           "lang": lang}).encode()
        req = urllib.request.Request(
            f"{MDDB}/delete", data=body,
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except urllib.error.HTTPError as exc:
            # 400 'document not found' is fine — key was never published
            if exc.code != 400:
                print(f"mddb delete {key}/{lang}: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"mddb delete {key}/{lang}: {exc}", file=sys.stderr)
        _pub_hash.pop(f"{key}:{lang}", None)


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


def detections_timeline(zone: str, lang: str = "en",
                        hours: int = 24) -> str:
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
    return (f"\n## {_t(lang, 'Detection timeline', 'ไทม์ไลน์การตรวจจับ')} "
            f"({_t(lang, 'last', 'ล่าสุด')} {hours}{_t(lang, 'h', ' ชม.')})\n\n"
            + header + "\n" + sep + "\n" + "\n".join(rows) + "\n")


def wall_page(zone: str, man: dict, zstate: dict, lang: str = "en") -> str:
    s = zstate.get("settings") or {}
    live = [c for c in man["cams"] if c.get("ok")]
    stale = [c for c in man["cams"] if not c.get("ok") and c.get("ts")]
    dead = [c for c in man["cams"] if not c.get("ok") and not c.get("ts")]
    age = int(time.time() - man.get("updated", 0))
    det_span, det_top = detections_tail(zone)
    state_word = {"live": _t(lang, "live", "ออนไลน์"),
                  "down": _t(lang, "down", "ขัดข้อง")}
    rows = "\n".join(
        f"| [{_label(c, lang)}](https://idc01.taila0626a.ts.net/cms/"
        f"#/{cam_slug(zone, c)}) | {c['key']} | "
        + (state_word["live"] if c.get("ok") else state_word["down"])
        + (f" · {_t(lang, 'frame', 'เฟรมล่าสุด')} {int(time.time()-c['ts'])}s"
           if c.get("ts") else "")
        + (f" · {c['err']}" if c.get("err") else "")
        + " |"
        for c in man["cams"])
    det_block = ""
    if det_top:
        det_block = (
            f"\n## {_t(lang, 'Detections (yolo, window', 'การตรวจจับ (yolo ช่วง')} "
            f"{det_span}{_t(lang, ')', ')')}\n\n"
            f"{_t(lang, 'latest sweep', 'สแกนล่าสุด')}: {det_top}\n\n"
            f"Raw log: `data/{zone}/detections-{zone}.jsonl` "
            f"{_t(lang, '(append-only while the yolo effect is on).',
                 '(บันทึกต่อเนื่องขณะเปิดเอฟเฟกต์ yolo)')}\n")
    det_block += detections_timeline(zone, lang)
    area = AREA.get(zone, zone)
    return f"""# {_t(lang, 'CCTV Wall', 'กำแพงกล้อง')}: {_area(area, lang)} (`{zone}`)

{_t(lang, ZONE_INFO.get(zone, 'Camera wall zone.'),
    ZONE_INFO_TH.get(zone, 'กำแพงกล้องวงจรปิด'))}

![montage]({BASE}/data/{zone}/montage.jpg)

- **{_t(lang, 'Wall URL', 'ลิงก์กำแพง')}**: `{BASE}/?zone={zone}` ({_t(lang, 'cast via', 'ฉายด้วย')} `cctv_wall zone={zone} screen=N`)
- **{_t(lang, 'Refresh', 'การรีเฟรช')}**: {_t(lang, 'enabled' if zstate.get('enabled') else 'off (warm thumbs only)', 'เปิด' if zstate.get('enabled') else 'ปิด (ภาพค้างไว้เท่านั้น)')} · {_t(lang, 'interval', 'ทุก')} {s.get('interval', 'default')}s
- **{_t(lang, 'Status', 'สถานะ')}**: {len(live)}/{len(man['cams'])} {_t(lang, 'cams live', 'กล้องออนไลน์')} · {len(stale)} {_t(lang, 'stale', 'ภาพเก่า')} · {len(dead)} {_t(lang, 'dead', 'ดับ')} · {_t(lang, 'manifest', 'ข้อมูลอายุ')} {age}s
- **{_t(lang, 'Effects', 'เอฟเฟกต์')}**: {', '.join(s.get('effects') or ['none'])}

{_t(lang, 'Controls, status-card standard and Ada usage → `cctv-walls` '
          '(shared — kept on the index so wall pages carry data only).',
        'สวิตช์/มาตรฐานการ์ดสถานะ/การเรียกผ่าน Ada → `cctv-walls` '
        '(ส่วนกลาง — หน้านี้เก็บเฉพาะข้อมูล)')}

## {_t(lang, 'Cameras', 'รายการกล้อง')}

| {_t(lang, 'camera', 'กล้อง')} | key | {_t(lang, 'state', 'สถานะ')} |
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


def cam_page(slug_key: str, entries: list[tuple[str, dict, dict]],
             lang: str = "en") -> str:
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
        state = _t(lang, "live", "ออนไลน์")
    elif ts:
        state = _t(lang, f"stale — last frame {age}s ago",
                   f"ภาพเก่า — เฟรมล่าสุด {age} วินาทีที่แล้ว")
    else:
        state = _t(lang, "down — no frame on record",
                   "ขัดข้อง — ไม่มีเฟรมบันทึกไว้")
    det_top, det_last = cam_dets(zone, key)
    det_line = (_t(lang, f"{det_top} (last seen {det_last}, 24h window)",
                   f"{det_top} (พบล่าสุด {det_last} น., ช่วง 24 ชม.)")
                if det_top else _t(lang, "none in window", "ไม่มีในช่วง"))
    walls = ", ".join(f"[{z}]({BASE}/?zone={z})"
                      for z, _, _ in sorted(
                          entries, key=lambda e: e[0]))
    ident = (f"- **{_t(lang, 'Source', 'แหล่ง')}**: DVR `{cam['dev']}` · "
             f"{_t(lang, 'channel', 'ช่อง')} `{cam['ch']}`\n"
             if cam.get("dev") else "")
    return f"""# {_t(lang, 'CCTV', 'กล้อง')}: {_area(cam_area(zone, cam), lang)} — {_label(cam, lang)}

![latest]({BASE}/data/{zone}/{key}.jpg)

{ident}- **{_t(lang, 'Walls', 'กำแพง')}**: {walls} (`{"`, `".join(
        wall_key(z) for z in sorted({z for z, _, _ in entries}))}`)
- **{_t(lang, 'State', 'สถานะ')}**: {state} · {_t(lang, 'manifest as of', 'ข้อมูล ณ')} {bucket}
{f"- **{_t(lang, 'Error', 'ข้อผิดพลาด')}**: {err}" if err else ""}
- **{_t(lang, 'Detections', 'การตรวจจับ')}**: {det_line}

{_t(lang, f'Part of `cctv-walls` — camera dossier for `{slug_key}`.',
        f'ส่วนหนึ่งของ `cctv-walls` — แฟ้มกล้อง `{slug_key}`')}
"""


CMS = "https://idc01.taila0626a.ts.net/cms"


def dvr_wall_page(cam_groups: dict[str, list[tuple[str, dict, dict]]],
                  lang: str = "en") -> str:
    """Video-wall CMS page — every DVR/VMS channel as a clickable image
    tile, grouped by DVR device. Each tile links to the camera's own
    cam-* dossier page; image is the freshest still across the walls
    that list it."""
    per_dev: dict[str, list[tuple[str, dict, dict, str]]] = {}
    for slug, entries in cam_groups.items():
        zone, cam, man = max(
            entries, key=lambda e: e[2].get("updated") or 0)
        if not cam.get("dev"):
            continue
        per_dev.setdefault(cam["dev"], []).append((zone, cam, man, slug))
    if not per_dev:
        return ""
    sections = []
    for dev in sorted(per_dev):
        cams = sorted(per_dev[dev],
                      key=lambda e: str(e[1].get("ch", e[1]["key"])))
        cells = []
        for zone, cam, man, slug in cams:
            state = (_t(lang, "live", "ออนไลน์") if cam.get("ok") else
                     (_t(lang, "stale", "ภาพเก่า") if cam.get("ts")
                      else _t(lang, "down", "ขัดข้อง")))
            cells.append(
                f"[![{_label(cam, lang)}]({BASE}/data/{zone}/{cam['key']}.jpg)]"
                f"({CMS}/#/{slug})<br>{_label(cam, lang)} · {state}")
        # 4-column grid via markdown table
        rows = []
        for i in range(0, len(cells), 4):
            row = cells[i:i + 4]
            row += [""] * (4 - len(row))
            rows.append("| " + " | ".join(row) + " |")
        live = sum(1 for _, c, _, _ in cams if c.get("ok"))
        sections.append(
            f"## {_area(DEV_AREA.get(dev, dev), lang)} DVR (`{dev}`) — "
            f"{live}/{len(cams)} {_t(lang, 'live', 'ออนไลน์')}\n\n"
            "| | | | |\n|---|---|---|---|\n" + "\n".join(rows))
    return f"""# {_t(lang, 'DVR Video Wall', 'กำแพงวิดีโอ DVR')}

{_t(lang, "One tile per physical DVR channel (XMEye VMS on mn01, snaps via "
          "the vms-snap shim). Click any tile for that camera's dossier "
          "page. Refresh follows each channel's wall interval — typically "
          "minutes.",
        'หนึ่งช่องต่อกล้องจริงบน DVR (XMEye VMS บน mn01 จับภาพผ่าน '
        'vms-snap) — แตะช่องใดก็ได้เพื่อเปิดแฟ้มกล้องนั้น '
        'การรีเฟรชตามจังหวะกำแพงของแต่ละช่อง โดยทั่วไปไม่กี่นาที')}

{chr(10).join(sections)}

{_t(lang, 'Walls these channels appear on: `cctv-walls` index.',
        'กำแพงที่ช่องเหล่านี้ปรากฏ: ดัชนี `cctv-walls`')}
"""


def index_page(zones: dict[str, dict], lang: str = "en") -> str:
    rows = []
    for zone, m in sorted(zones.items()):
        man = m["manifest"]
        live = sum(1 for c in man["cams"] if c.get("ok"))
        age = int(time.time() - man.get("updated", 0))
        st = m["state"]
        eff = (st.get("settings") or {}).get("effects") or []
        en_st = "on" if st.get("enabled") else "warm"
        th_st = "เปิด" if st.get("enabled") else "ค้าง"
        rows.append(
            f"| [{zone}]({BASE}/?zone={zone}) | "
            f"![{zone}]({BASE}/data/{zone}/montage.jpg) | "
            f"{live}/{len(man['cams'])} | "
            f"{_t(lang, en_st, th_st)} · {age}s | "
            f"{', '.join(eff) or '—'} |")
    return f"""# CCTV / traffic camera walls

One wall per area — each is a live grid page plus a CMS dossier page
(`camwall-<area>`). Cast with `cctv_wall`; tune with the ⚙ drawer on the
wall page or `cctv_wall settings`.

| wall | montage | cams live | refresh | effects |
|---|---|---|---|---|
{chr(10).join(rows)}

Detail pages: {', '.join(f'`{wall_key(z)}`' for z in sorted(zones))}
· `dvr-wall` — every DVR channel as a clickable tile grid

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
                f"again ({wall_key(zone)} updated)")
        elif was > 0 and live == 0:
            notes.append(
                f"camwall {zone} went all-dead — 0/{len(cams)} live "
                f"({wall_key(zone)} updated)")
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
        area = AREA.get(zone, zone)
        info = ZONE_INFO.get(zone, "Camera wall zone.")
        for lang in ("en", "th"):
            ok &= mddb_add(
                wall_key(zone),
                wall_page(zone, m["manifest"], m["state"], lang),
                _t(lang, f"CCTV Wall: {area}",
                   f"กำแพงกล้อง: {_area(area, lang)}"),
                lang=lang, summary=_t(lang, info,
                                      ZONE_INFO_TH.get(zone, "")))
        # retire the old wall-<zone> key (renamed to camwall-<area>)
        legacy_wall = f"wall-{zone}"
        if legacy_wall != wall_key(zone):
            mddb_delete(legacy_wall)
        for c in m["manifest"].get("cams") or []:
            cam_groups.setdefault(cam_slug(zone, c), []).append(
                (zone, c, m["manifest"]))
    cam_pages = len(cam_groups)
    for lang in ("en", "th"):
        dvr = dvr_wall_page(cam_groups, lang)
        if dvr:
            ok &= mddb_add(
                "dvr-wall", dvr,
                _t(lang, "DVR Video Wall", "กำแพงวิดีโอ DVR"),
                lang=lang,
                summary=_t(lang, "Every DVR channel as a tile grid",
                           "ทุกช่อง DVR เป็นช่องภาพกดได้"))
    for slug_key, entries in sorted(cam_groups.items()):
        _, cam, _ = max(entries, key=lambda e: e[2].get("updated") or 0)
        zone, _cam, _ = entries[0]
        for lang in ("en", "th"):
            ok &= mddb_add(
                slug_key, cam_page(slug_key, entries, lang),
                _t(lang, f"CCTV: {cam_area(zone, cam)} — {cam['label']}",
                   f"กล้อง: {_area(cam_area(zone, cam), lang)} — "
                   f"{_label(cam, lang)}"),
                lang=lang,
                summary=_t(
                    lang,
                    f"{cam_area(zone, cam)} — {cam['label']} "
                    f"({'live' if cam.get('ok') else 'down'})",
                    f"{_area(cam_area(zone, cam), lang)} — "
                    f"{_label(cam, lang)} "
                    f"({'ออนไลน์' if cam.get('ok') else 'ขัดข้อง'})"))
        # retire the old zone-scoped key the canonical dev-key replaced
        for z, c, _ in entries:
            legacy = f"cam-{z}-{c['key']}"
            if legacy != slug_key:
                mddb_delete(legacy)
    if zones:
        for lang in ("en", "th"):
            ok &= mddb_add(
                "cctv-walls", index_page(zones, lang),
                _t(lang, "CCTV & Traffic Camera Walls",
                   "กำแพงกล้อง CCTV และจราจร"),
                lang=lang,
                summary=_t(lang, "Index of every camera wall — montage, "
                                 "live counts, shared controls",
                           "ดัชนีกำแพงกล้องทั้งหมด — ภาพรวม จำนวนออนไลน์ "
                           "และสวิตช์ควบคุมกลาง"),
                parent="")
        notify_transitions(zones)
    print(f"walls: {len(zones)} pages + {cam_pages} cams + index "
          f"{'ok' if ok else 'ERR'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
