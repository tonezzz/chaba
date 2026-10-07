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

Page lifecycle (supersede-by-construction, card cms-cam-page-compaction):
the publish set this run computes is canonical truth — any page we
generated that is no longer in it (legacy key forms, cams/zones retired
from the manifests) gets status:superseded + superseded_by, never deleted
(cam pages are operational history). New pages carry meta.supersedes
back to the keys they replace. A retention pass then flips generated
docs that are both superseded AND older than ARCHIVE_DAYS to
kind:archive — queryable, but out of reports-index weight.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BRIDGE = os.environ.get(
    "VCAST_API", "https://tony-dell.taila0626a.ts.net/api/input-bridge")
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023/v1")
DATA = Path(os.environ.get(
    "CAMWALL_DATA",
    str(Path.home() / "CascadeProjects/chaba-tony-dell/stacks/web/public/apps/camwall/data")))
BASE = "https://tony-dell.taila0626a.ts.net/apps/camwall"
COLLECTION = "ada-cms-pages"
GENERATOR = "cam-wall-cms"
# fresh_for feeds the reports-index ⚠STALE flag — must be a parseable TTL
# ('1h'/'30m'/'1d'); bare seconds like the old "600" never evaluated, so
# dead/orphan pages could never flag stale. ~4 missed 15-min ticks.
FRESH_FOR = "1h"
# superseded generated pages whose content is older than this get
# kind:archive — retention, not deletion.
ARCHIVE_DAYS = 7
# memory-schema statuses that take a doc out of the live corpus
DROP_STATUS = {"superseded", "archived", "retracted", "expired"}
DRY = "--dry-run" in sys.argv

# Zone metadata — areas, coverage notes, group/site/tab classification —
# lives in zones.yml next to this script (single SSOT, shared with the
# puller; see zone_meta.py). A zone absent from zones.yml classifies as
# 'unsorted' and keeps its raw slug as the area — visible, never guessed.
import zone_meta  # noqa: E402 — sibling module, script dir on sys.path

ZMETA = zone_meta.load()


def zone_cls(zone: str) -> dict:
    return zone_meta.classify(zone, ZMETA)


def zone_area(zone: str, lang: str) -> str:
    c = zone_cls(zone)
    return c["area_th"] if lang == "th" else c["area"]


def dev_area(dev: str, lang: str) -> str:
    a = (zone_meta.device_entry(dev, ZMETA).get("area") or {})
    return a.get(lang) or a.get("en") or dev


def zone_info(zone: str, lang: str) -> str:
    info = zone_cls(zone).get("info") or {}
    if lang == "th":
        return info.get("th") or info.get("en") or "กำแพงกล้องวงจรปิด"
    return info.get("en") or "Camera wall zone."


def _cls_union(classifications: list[dict]) -> dict:
    """Merge per-zone/cam classifications for a multi-zone page — each
    field becomes the sorted set of values present."""
    return {k: sorted({c[k] for c in classifications if c.get(k)})
            for k in ("tab", "group", "site")}

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
    "4. Entrance Gate": "ประตูทางเข้า",
}

# cam key -> (en, th) one-liner: what the camera actually watches. Curated —
# the difference between a dossier and a telemetry dump.
CAM_NOTES = {
    "washing-machines": (
        "Laundry room — washer/dryer row and the seating area inside",
        "ห้องซักผ้า — แถวเครื่องซัก/อบและพื้นที่นั่งรอภายใน"),
    "stairway-room": (
        "Stairwell room — the indoor stairs between floors",
        "ห้องบันได — บันไดภายในระหว่างชั้น"),
    "mini-mart": (
        "Mini-mart — counter and shelf aisles",
        "มินิมาร์ท — เคาน์เตอร์และทางเดินระหว่างชั้นวาง"),
    "front-rd-left": (
        "Front road, left side — covers the inbound stretch",
        "ถนนหน้าฝั่งซ้าย — ครอบคลุมช่วงขาเข้า"),
    "front-rd-right": (
        "Front road, right side — covers the outbound stretch",
        "ถนนหน้าฝั่งขวา — ครอบคลุมช่วงขาออก"),
    "swimming-pool": (
        "Pool deck and water — safety-critical view",
        "รอบสระว่ายน้ำ — มุมสำคัญด้านความปลอดภัย"),
    "tennis-court": (
        "Tennis court — full court view",
        "สนามเทนนิส — เห็นเต็มคอร์ท"),
    "play-ground": (
        "Children's playground",
        "สนามเด็กเล่น"),
    "road-in": (
        "Estate entry road — approaching vehicles and pedestrians",
        "ถนนเข้าโครงการ — รถและคนเดินขาเข้า"),
    "guard-view": (
        "Guard post view — what the gate guard watches",
        "มุมกระจกยาม — เหมือนที่ยามเห็นที่ประตู"),
    "walkway-in": (
        "Entry walkway — foot traffic into the building",
        "ทางเดินเข้า — คนเดินเข้าอาคาร"),
    "road-corner": (
        "Road corner — the turn at the far edge of the estate",
        "หัวมุมถนน — โค้งสุดขอบโครงการ"),
    "entrance-gate": (
        "Entrance gate — gate leaf and barrier approach",
        "ประตูทางเข้า — บานประตูและทางขึ้นไม้กั้น"),
    "c100": ("House — C100 interior cam", "บ้าน — กล้อง C100 ภายใน"),
    "c201": ("House — C201 interior cam", "บ้าน — กล้อง C201 ภายใน"),
    "coffee-corner": ("Coffee corner — kitchen nook",
                      "มุมกาแฟ — ติดในครัว"),
}


def _t(lang: str, en: str, th: str) -> str:
    return th if lang == "th" else en


def _label(cam: dict, lang: str) -> str:
    return LABEL_TH.get(cam["label"], cam["label"]) if lang == "th" \
        else cam["label"]


def _ascii_slug(s: str) -> str:
    """ASCII-normalize a cam key for CMS slugs — registry cams carry Thai
    road-group prefixes that mangle into runs of dashes
    ('ทางพ-เศษบ-รพาว-ถ----bangna-…' -> 'bangna-…')."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s).lower()
    s = "".join(c for c in s if ord(c) < 128 and (c.isalnum() or c in "-_"))
    s = re.sub(r"^[^a-z0-9]+", "", s)   # drop leading dash-runs (dead Thai)
    return re.sub(r"-{2,}", "-", s).strip("-") or "cam"


def cam_slug(zone: str, cam: dict) -> str:
    """Canonical cam-page key. VMS cams key on <device>-<camkey> so the
    same physical camera is ONE page even when several walls list it
    (a retired wall may share channels with a per-DVR wall)."""
    dev = cam.get("dev")
    key = _ascii_slug(cam["key"])
    return f"cam-{dev}-{key}" if dev else f"cam-{zone}-{key}"


def cam_area(zone: str, cam: dict, lang: str = "en") -> str:
    """Localized display area — canonical DVR device area when the cam
    carries one, else the zone's area, else the raw zone slug."""
    c = zone_meta.cam_classify(zone, cam, ZMETA)
    return c["area_th"] if lang == "th" else c["area"]


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


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def mddb_post(path: str, payload: dict, timeout: float = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def mddb_get(key: str, lang: str) -> dict | None:
    try:
        return mddb_post("get", {"collection": COLLECTION, "key": key,
                                 "lang": lang})
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            return None
        print(f"mddb get {key}/{lang}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"mddb get {key}/{lang}: {exc}", file=sys.stderr)
        return None


def mddb_write(key: str, lang: str, md: str, meta: dict) -> bool:
    """POST /add — a full doc replace. MDDB re-embeds on every write."""
    if DRY:
        print(f"[dry] write {key}/{lang} "
              f"(kind={meta.get('kind')} status={meta.get('status')})")
        return True
    body = json.dumps({"collection": COLLECTION, "key": key, "lang": lang,
                       "contentMd": md, "meta": meta}).encode()
    req = urllib.request.Request(
        f"{MDDB}/add", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status < 300
    except Exception as exc:
        print(f"mddb add {key}: {exc}", file=sys.stderr)
        return False


def collection_docs() -> list[dict]:
    """Paginated ada-cms-pages listing — the supersede/archive passes and
    the superseded_by->supersedes link map all read from this one fetch."""
    docs, offset = [], 0
    while True:
        try:
            page = mddb_post("search", {"collection": COLLECTION,
                                        "query": "", "limit": 500,
                                        "offset": offset}, timeout=60)
        except Exception as exc:
            print(f"mddb search failed: {exc}", file=sys.stderr)
            return docs
        if isinstance(page, dict):
            page = page.get("documents") or page.get("docs") or []
        docs += page
        if len(page) < 500:
            return docs
        offset += 500


def mddb_add(key: str, md: str, title: str, lang: str = "en",
             summary: str = "", parent: str = "cctv-walls",
             sources: list[str] | None = None,
             classification: dict | None = None,
             supersedes: list[str] | None = None,
             force: bool = False) -> bool:
    import hashlib
    # cms-audit R2: every generated page needs a provenance footer.
    # Static text only — a timestamp here would change the pub hash
    # every cycle and defeat the dedup below.
    md = md.rstrip() + _t(
        lang,
        "\n\n---\n*Generated by cam-wall-cms from the zone manifests, "
        "thumbnail puller state and detection log.*\n",
        "\n\n---\n*รวบรวมอัตโนมัติโดย cam-wall-cms จาก manifest ของแต่ละโซน "
        "สถานะตัวดึงภาพ และบันทึกการตรวจจับ*\n")
    # The hash covers the supersedes link set too, so a page republishes
    # the cycle it gains a predecessor even when its body is unchanged.
    h = hashlib.sha256(
        md.encode() + b"\x00" +
        ",".join(sorted(supersedes or ())).encode()).hexdigest()[:16]
    if classification:
        # fold classification into the dedup hash — a zones.yml change
        # republishes the affected pages so the meta tag actually lands
        h = h + ":" + hashlib.sha256(
            json.dumps(classification, sort_keys=True).encode()
        ).hexdigest()[:8]
    hkey = f"{key}:{lang}"
    if not force and _pub_hash.get(hkey) == h:
        return True  # unchanged — skip write + re-embedding
    # Merge existing meta so memory-schema fields set by
    # cms-normalize-meta.py (and the original valid_from) survive.
    old = mddb_get(key, lang) or {}
    old_meta = {k: (v if isinstance(v, list) else [str(v)])
                for k, v in (old.get("meta") or {}).items()}
    today = time.strftime("%Y-%m-%d", time.gmtime())
    meta = dict(old_meta)
    meta.update({
        "kind": ["page"], "attribute": ["page"], "bank": ["cms"],
        "slug": [key], "subject": [key], "title": [title],
        "format": ["markdown"], "lang": [lang],
        "domain": ["cctv"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "generated_by": [GENERATOR],
        "written_by": [GENERATOR],
        # cms-audit R1: generated pages must name their inputs
        "sources": sources or ["cam-wall-manifest"],
        "fresh_for": [FRESH_FOR],
        "updated": [_now_iso()],
        "last_verified": [today],
        "instance": [GENERATOR],
    })
    # tag every tab they span).
    if classification:
        for mk, cv in (("zone_tab", classification.get("tab")),
                       ("zone_group", classification.get("group")),
                       ("zone_site", classification.get("site"))):
            if cv:
                meta[mk] = cv if isinstance(cv, list) else [cv]
    # A page being (re)published is canonically live: strip the lifecycle
    # markers a supersede/archive pass may have stamped — this is how a
    # cam returning to the roster revives cleanly.
    for f in ("superseded_by", "superseded_at", "archived_at"):
        meta.pop(f, None)
    sup = sorted({*old_meta.get("supersedes", []), *(supersedes or [])})
    if sup:
        meta["supersedes"] = sup
    meta.setdefault("valid_from", [today])
    if summary:
        meta["summary"] = [summary]
    if parent:
        meta["parent"] = [parent]
    if not mddb_write(key, lang, md, meta):
        return False
    if not DRY:
        _pub_hash[hkey] = h
        try:
            PUB_HASH.write_text(json.dumps(_pub_hash))
        except Exception:
            pass
    return True


def mddb_supersede(old_key: str, new_key: str) -> bool:
    """Mark `old_key` as replaced by `new_key`, both lang variants —
    the memory-schema supersede verb (status:superseded + superseded_by).
    Never deletes: the retention pass archives the doc once its content
    crosses ARCHIVE_DAYS. Returns True when a doc existed."""
    existed = False
    for lang in ("en", "th"):
        doc = mddb_get(old_key, lang)
        if not doc:
            continue
        existed = True
        meta = {k: (v if isinstance(v, list) else [str(v)])
                for k, v in (doc.get("meta") or {}).items()}
        if (meta.get("status") or [""])[0] in DROP_STATUS \
                or (meta.get("kind") or [""])[0] == "archive":
            continue  # already superseded/archived — idempotent
        meta["status"] = ["superseded"]
        meta["superseded_by"] = [new_key]
        meta["superseded_at"] = [_now_iso()]
        if DRY:
            print(f"[dry] supersede {old_key}/{lang} -> {new_key}")
            continue
        mddb_write(old_key, lang, doc.get("contentMd") or "", meta)
    return existed


def _ours(meta: dict) -> bool:
    """Doc was generated by this script (either lane — dell or VPS)."""
    return any((meta.get(f) or [""])[0] == GENERATOR
               for f in ("generated_by", "written_by", "instance"))


def _zone_sources(meta: dict) -> set[str]:
    return {s[5:] for s in meta.get("sources") or []
            if isinstance(s, str) and s.startswith("zone:")}


def _cam_successor(raw: str, zones: dict, current: set[str]) -> str | None:
    """The live page for a cam whose key moved across zones or key forms
    (raw/Thai slug -> ascii, zone-scoped -> dev-canonical)."""
    for z, m in zones.items():
        for c in m["manifest"].get("cams") or []:
            if _ascii_slug(c["key"]) == raw:
                slug = cam_slug(z, c)
                if slug in current:
                    return slug
    return None


def _successor_for(key: str, meta: dict, zones: dict,
                   current: set[str]) -> str | None:
    """Which live page replaces `key` — or None when the doc belongs to
    another lane (zone: sources we don't own) or matches nothing we can
    name. The two lanes share this collection and instance tag, so the
    zone-source check is the boundary that keeps each lane honest."""
    my = set(zones)
    zsrc = _zone_sources(meta)
    if zsrc and not zsrc & my:
        return None  # foreign lane's zone — not ours to touch
    for z in sorted(my):
        if key == f"wall-{z}":
            return wall_key(z) if wall_key(z) in current else "cctv-walls"
        pre = f"cam-{z}-"
        if key.startswith(pre):
            raw = _ascii_slug(key[len(pre):])
            return (_cam_successor(raw, zones, current)
                    or (wall_key(z) if wall_key(z) in current
                        else "cctv-walls"))
    for dev in sorted(ZMETA.get("devices") or {}):
        pre = f"cam-{dev}-"
        if key.startswith(pre):
            raw = _ascii_slug(key[len(pre):])
            if f"cam-{dev}-{raw}" in current:
                return f"cam-{dev}-{raw}"
            return (_cam_successor(raw, zones, current)
                    or (f"camwall-{dev}" if f"camwall-{dev}" in current
                        else "cctv-walls"))
    if key == "dvr-wall":
        return "cctv-walls" if "cctv-walls" in current else None
    return None


def supersede_stale_pages(docs: list[dict], current: set[str],
                          zones: dict) -> int:
    """Supersede-by-construction: every page we generated that is absent
    from this run's publish set (legacy key forms, cams/zones that left
    the manifests) is marked status:superseded + superseded_by. Returns
    how many keys were newly marked."""
    if not zones:
        return 0  # empty roster means we can't know the intended state
    n = 0
    seen = set()
    for d in docs:
        key = d.get("key") or ""
        if key in seen or key in current:
            continue
        meta = d.get("meta") or {}
        if not _ours(meta):
            continue
        if (meta.get("status") or [""])[0] in DROP_STATUS \
                or (meta.get("kind") or [""])[0] == "archive":
            continue
        succ = _successor_for(key, meta, zones, current)
        if not succ or succ == key:
            continue
        seen.add(key)
        if mddb_supersede(key, succ):
            n += 1
            # keep every lang variant current in-memory so the archive
            # pass and the supersedes link map see this mark in the
            # same run
            for dd in docs:
                if dd.get("key") == key:
                    m = dd.setdefault("meta", {})
                    m["status"] = ["superseded"]
                    m["superseded_by"] = [succ]
                    m["superseded_at"] = [_now_iso()]
    return n


def supersede_links(docs: list[dict]) -> dict[str, list[str]]:
    """new key -> old keys it replaces (the mirror of superseded_by) —
    feeds meta.supersedes on each generated page."""
    links: dict[str, set[str]] = {}
    for d in docs:
        for n in (d.get("meta") or {}).get("superseded_by") or []:
            k = d.get("key")
            if k:
                links.setdefault(str(n), set()).add(k)
    return {k: sorted(v) for k, v in links.items()}


def _doc_age_epoch(doc: dict) -> float:
    """Content age — meta.updated first (it freezes when a page stops
    being regenerated), updatedAt/addedAt epochs as fallback."""
    upd = ((doc.get("meta") or {}).get("updated") or [""])[0]
    if upd:
        try:
            return datetime.datetime.fromisoformat(
                upd.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    return float(doc.get("updatedAt") or doc.get("addedAt") or 0)


def archive_superseded(docs: list[dict]) -> int:
    """Retention pass: generated docs that are superseded AND whose
    content is older than ARCHIVE_DAYS flip to kind:archive. Archive is
    not delete — the page stays queryable, it just leaves reports-index
    weight (the index only lists kind:page|report)."""
    cutoff = time.time() - ARCHIVE_DAYS * 86400
    n = 0
    for d in docs:
        meta = d.get("meta") or {}
        if not _ours(meta):
            continue
        if (meta.get("status") or [""])[0] != "superseded":
            continue
        if (meta.get("kind") or [""])[0] == "archive":
            continue
        age = _doc_age_epoch(d)
        if not age or age > cutoff:
            continue
        new_meta = {k: (v if isinstance(v, list) else [str(v)])
                    for k, v in meta.items()}
        new_meta["kind"] = ["archive"]
        new_meta["archived_at"] = [_now_iso()]
        if DRY:
            print(f"[dry] archive {d.get('key')}/{d.get('lang')}")
            n += 1
            continue
        if mddb_write(d["key"], d.get("lang") or "en",
                      d.get("contentMd") or "", new_meta):
            meta.update(new_meta)
            n += 1
    return n


def regen_reports_index() -> None:
    """Re-render reports-index after lifecycle marks — shared lib so the
    same superseded/archived filter applies to every writer."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from lib.cms_index import regen_reports_index as _regen
        _regen(MDDB, written_by=GENERATOR, instance=GENERATOR)
    except Exception as exc:
        print(f"reports-index regen failed: {exc}", file=sys.stderr)


DET_MAX_BYTES = 8 * 1024 * 1024   # ~14d of hourly-ish sweeps


def _det_recs(zone: str) -> list[dict]:
    """Read the rolling detection log; trim it past DET_MAX_BYTES so a
    long-running yolo wall doesn't grow the file unboundedly."""
    f = DATA / zone / f"detections-{zone}.jsonl"
    if not f.exists():
        return []
    try:
        if f.stat().st_size > DET_MAX_BYTES and not DRY:
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
        f"| [{_label(c, lang)}](https://idc03.taila0626a.ts.net/cms/"
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
    return f"""# {_t(lang, 'CCTV Wall', 'กำแพงกล้อง')}: {zone_area(zone, lang)} (`{zone}`)

{zone_info(zone, lang)}

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


def _err_short(err: str, lang: str = "en") -> str:
    """Normalize puller/ffmpeg stderr into a short readable status — raw
    stderr leaks pointer addresses and truncates mid-word on the page."""
    import re
    e = (err or "").lower()
    if "404" in e or "not found" in e:
        s = "source not found (404)"
    elif "503" in e or "502" in e or "service unavailable" in e:
        s = "source unavailable"
    elif "timed out" in e or "timeout" in e:
        s = "source timed out"
    elif "connection refused" in e:
        s = "connection refused"
    elif "tls" in e or "ssl" in e:
        s = "TLS error"
    else:
        # strip ffmpeg internals, cap at a sane length on word boundary
        s = re.sub(r"\[[^\]]*\]", "", err).split(": ")[-1].strip()
        s = (s[:77] + "…") if len(s) > 80 else s
    return (_t(lang, s, {
        "source not found (404)": "ไม่พบแหล่งภาพ (404)",
        "source unavailable": "แหล่งภาพไม่พร้อมใช้งาน",
        "source timed out": "แหล่งภาพหมดเวลาตอบสนอง",
        "connection refused": "แหล่งภาพปฏิเสธการเชื่อมต่อ",
        "TLS error": "ข้อผิดพลาด TLS",
    }.get(s, s)))


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
    if det_top:
        det_line = _t(lang, f"{det_top} (last seen {det_last}, 24h window)",
                      f"{det_top} (พบล่าสุด {det_last} น., ช่วง 24 ชม.)")
    elif any(c.get("det") for c in man.get("cams") or []):
        det_line = _t(lang, "none in window", "ไม่มีในช่วง")
    else:
        det_line = _t(lang, "no detection feed on this wall",
                      "กำแพงนี้ไม่มีการตรวจจับ")
    note = CAM_NOTES.get(key)
    note_line = (f"- **{_t(lang, 'Covers', 'ครอบคลุม')}**: "
                 f"{_t(lang, *note)}\n" if note else "")
    img = f"{key}-status.jpg" if not ok else f"{key}.jpg"
    walls = ", ".join(f"[{z}]({BASE}/?zone={z})"
                      for z, _, _ in sorted(
                          entries, key=lambda e: e[0]))
    ident = (f"- **{_t(lang, 'Source', 'แหล่ง')}**: DVR `{cam['dev']}` · "
             f"{_t(lang, 'channel', 'ช่อง')} `{cam['ch']}`\n"
             if cam.get("dev") else "")
    return f"""# {_t(lang, 'CCTV', 'กล้อง')}: {cam_area(zone, cam, lang)} — {_label(cam, lang)}

![{_t(lang, 'latest', 'ล่าสุด')}]({BASE}/data/{zone}/{img})

{ident}- **{_t(lang, 'Walls', 'กำแพง')}**: {walls} (`{"`, `".join(
        wall_key(z) for z in sorted({z for z, _, _ in entries}))}`)
{note_line}- **{_t(lang, 'State', 'สถานะ')}**: {state} · {_t(lang, 'manifest as of', 'ข้อมูล ณ')} {bucket}
{f"- **{_t(lang, 'Error', 'ข้อผิดพลาด')}**: {_err_short(err, lang)}" if err else ""}
- **{_t(lang, 'Detections', 'การตรวจจับ')}**: {det_line}

{_t(lang, f'Part of `cctv-walls` — camera dossier for `{slug_key}`.',
        f'ส่วนหนึ่งของ `cctv-walls` — แฟ้มกล้อง `{slug_key}`')}
"""


CMS = "https://idc03.taila0626a.ts.net/cms"


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
            f"## {dev_area(dev, lang)} DVR (`{dev}`) — "
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
    "ADA_NOTIFY_URL", "https://idc03.taila0626a.ts.net/api/notify")
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
        cls = zone_cls(zone)
        for c in m["manifest"].get("cams") or []:
            cam_groups.setdefault(cam_slug(zone, c), []).append(
                (zone, c, m["manifest"]))
    cam_pages = len(cam_groups)

    # ---- lifecycle: supersede-by-construction, then retention ----------
    # The publish set this run computes is canonical truth — any page we
    # generated that is absent from it gets status:superseded (never
    # deleted; cam pages are operational history). superseded docs whose
    # content crosses ARCHIVE_DAYS flip to kind:archive. Both passes run
    # off one collection listing, before publishing so the new pages pick
    # up their supersedes links in the same cycle.
    has_dev = any(c.get("dev") for m in zones.values()
                  for c in m["manifest"].get("cams") or [])
    current = {wall_key(z) for z in zones} | set(cam_groups)
    if zones:
        current.add("cctv-walls")
    if has_dev:
        current.add("dvr-wall")
    docs = collection_docs() if zones else []
    n_sup = supersede_stale_pages(docs, current, zones)
    links = supersede_links(docs)
    n_arch = archive_superseded(docs)
    # A page whose key is back in the publish set revives — force the
    # write so status/kind flip back even when the body is unchanged.
    revive = {d.get("key") for d in docs
              if d.get("key") in current
              and (((d.get("meta") or {}).get("status") or [""])[0]
                   in DROP_STATUS
                   or ((d.get("meta") or {}).get("kind") or [""])[0]
                      == "archive")}

    for zone, m in zones.items():
        for lang in ("en", "th"):
            ok &= mddb_add(
                wall_key(zone),
                wall_page(zone, m["manifest"], m["state"], lang),
                _t(lang, f"CCTV Wall: {cls['area']}",
                   f"กำแพงกล้อง: {cls['area_th']}"),
                lang=lang, summary=_t(lang, zone_info(zone, "en"),
                                      zone_info(zone, "th")),
                sources=[f"zone:{zone}", "cam-wall-manifest",
                         "cam-wall-state", "cam-wall-detections"],
                classification=cls,
                supersedes=links.get(wall_key(zone)),
                force=wall_key(zone) in revive)
    # multi-zone pages tag every tab/group/site they span
    dev_cls = [zone_meta.cam_classify(z, c, ZMETA)
               for es in cam_groups.values() for z, c, _ in es
               if c.get("dev")]
    dvr_cls = _cls_union(dev_cls)
    for lang in ("en", "th"):
        dvr = dvr_wall_page(cam_groups, lang)
        if dvr:
            ok &= mddb_add(
                "dvr-wall", dvr,
                _t(lang, "DVR Video Wall", "กำแพงวิดีโอ DVR"),
                lang=lang,
                summary=_t(lang, "Every DVR channel as a tile grid",
                           "ทุกช่อง DVR เป็นช่องภาพกดได้"),
                sources=["cam-wall-manifest", "vms-snap"],
                classification=dvr_cls,
                supersedes=links.get("dvr-wall"),
                force="dvr-wall" in revive)
    for slug_key, entries in sorted(cam_groups.items()):
        fzone, cam, _ = max(entries, key=lambda e: e[2].get("updated") or 0)
        zone, _cam, _ = entries[0]
        cam_cls = zone_meta.cam_classify(fzone, cam, ZMETA)
        for lang in ("en", "th"):
            ok &= mddb_add(
                slug_key, cam_page(slug_key, entries, lang),
                _t(lang, f"CCTV: {cam_cls['area']} — {cam['label']}",
                   f"กล้อง: {cam_cls['area_th']} — "
                   f"{_label(cam, lang)}"),
                lang=lang,
                summary=_t(
                    lang,
                    f"{cam_cls['area']} — {cam['label']} "
                    f"({'live' if cam.get('ok') else 'down'})",
                    f"{cam_cls['area_th']} — "
                    f"{_label(cam, lang)} "
                    f"({'ออนไลน์' if cam.get('ok') else 'ขัดข้อง'})"),
                sources=sorted({f"zone:{z}" for z, _, _ in entries})
                + ["cam-wall-detections"],
                classification=cam_cls,
                supersedes=links.get(slug_key),
                force=slug_key in revive)
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
                parent="",
                sources=[f"zone:{z}" for z in sorted(zones)],
                classification=_cls_union([zone_cls(z) for z in zones]),
                supersedes=links.get("cctv-walls"),
                force="cctv-walls" in revive)
        notify_transitions(zones)
    print(f"walls: {len(zones)} pages + {cam_pages} cams + index "
          f"{'ok' if ok else 'ERR'} · superseded {n_sup} "
          f"archived {n_arch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
