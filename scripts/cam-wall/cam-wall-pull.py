#!/usr/bin/env python3
"""cam-wall puller — periodic CCTV thumbnails for enabled zones.

Runs on tony-dell (systemd timer every 30s). Each run:
  1. GET input-bridge /camwall on idc01 -> which zones are enabled
  2. For each enabled zone whose thumbs are older than its interval:
       house cams  -> go2rtc frame.jpeg on 127.0.0.1:1984 (parallel, ~4s)
       VMS cams    -> mn01 vms-snap shim 8377 (serial — one Wine UI, ~12s each)
       traffic     -> jpeg: direct GET (~0.3s) | youtube: yt-dlp -g
                      (cached ~4h) + ffmpeg -frames:v 1 (~5-10s)
       hls         -> ffmpeg -frames:v 1 on a playlist.m3u8 (~3-8s),
                      alt_urls tried in order on failure.
                      Zones traffic/burapha/chonburi are generated from
                      frigate/cameras.json (registry SSOT).
  3. Write <DATA>/<zone>/<slug>.jpg + manifest-<zone>.json
     (served at https://tony-dell.taila0626a.ts.net/apps/camwall/data/)

Ada controls zones via the cctv_wall tool (POST /camwall). If the relay is
unreachable the previous state is reused so a network blip doesn't blank
the wall; a down zone simply keeps its last thumbs with stale mtimes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRIDGE = os.environ.get(
    "VCAST_API", "https://tony-dell.taila0626a.ts.net/api/input-bridge")
VMS_SNAP = os.environ.get("VMS_SNAP_URL", "http://100.106.196.22:8377")
GO2RTC = os.environ.get("GO2RTC_URL", "http://127.0.0.1:1984")

DATA = Path(os.environ.get(
    "CAMWALL_DATA",
    str(Path.home() / "CascadeProjects/chaba-tony-dell/stacks/web/public/apps/camwall/data")))

# label -> ("vms", channel) | ("go2rtc", stream) | ("jpeg"|"youtube"|"hls", url)
# interval = refresh cadence while the zone is enabled; warm = keep thumbs
# fresh while DISABLED so casting a cold wall still shows recent frames.
# VMS zones get outage backoff: a dead P2P uplink makes each serial snap
# burn ~35s — when every vms cam in a zone failed last cycle, the warm
# wait is quadrupled.
ZONES: dict[str, dict] = {
    "zone-a": {
        "interval": 75,  # ~5 serial vms pulls ~= 60s + margin
        "warm": 900,
        "cams": [
            ("Front Rd Left", "vms", "Front Rd. Left"),
            ("Front Rd Right", "vms", "Front Rd. Right"),
            ("Road In", "vms", "1. Road In"),
            ("Walkway", "vms", "3. Walkway In"),
            ("Road Corner", "vms", "5. Road Corner"),
        ],
    },
    "noble-park": {
        "interval": 90,
        "warm": 900,
        "cams": [
            ("Swimming Pool", "vms", "Swimming Pool"),
            ("Tennis Court", "vms", "Tennis Court"),
            ("Play Ground", "vms", "Play Ground"),
            ("Mini Mart", "vms", "Mini Mart"),
            ("Guard View", "vms", "2. Guard View"),
        ],
    },
    # per-DVR walls — every channel the VMS device list exposes for that
    # recorder. Serial pulls (~16s/cam + poll headroom): club 8, A 5.
    "vms-noble-club": {
        "interval": 180,
        "warm": 1800,
        "cams": [
            ("Washing Machines", "vms", "Washing Machines"),
            ("Stairway Room", "vms", "Stairway Room"),
            ("Mini Mart", "vms", "Mini Mart"),
            ("Front Rd Left", "vms", "Front Rd. Left"),
            ("Front Rd Right", "vms", "Front Rd. Right"),
            ("Swimming Pool", "vms", "Swimming Pool"),
            ("Tennis Court", "vms", "Tennis Court"),
            ("Play Ground", "vms", "Play Ground"),
        ],
    },
    "vms-noble-a": {
        "interval": 120,
        "warm": 1800,
        "cams": [
            ("Road In", "vms", "1. Road In"),
            ("Guard View", "vms", "2. Guard View"),
            ("Walkway In", "vms", "3. Walkway In"),
            ("Road Corner", "vms", "5. Road Corner"),
            ("CAM01", "vms", "CAM01"),
        ],
    },
    "tony-house": {
        "interval": 15,
        "warm": 300,
        "cams": [
            ("C100", "go2rtc", "xiaomi_c100_hd"),
            ("C201", "go2rtc", "xiaomi_c201_hd"),
            ("Coffee Corner", "go2rtc", "ip_cam_65_hd"),
            ("IP65 Low", "go2rtc", "ip_cam_65_low"),
        ],
    },
    # demo traffic wall around Rama 9 — mixes direct JPEG stills (iTIC
    # via the Longdo feed) with YouTube live cams grabbed via yt-dlp+ffmpeg.
    # All kinds are independent HTTP pulls — no serial bottleneck.
    "rama9": {
        "interval": 60,
        "warm": 600,
        "cams": [
            ("Petchaburi Rd", "youtube", "a_bUVExv_Cg"),
            ("Sukhumvit Soi 11", "youtube", "UemFRPrl1hk"),
            ("Rama4 x Expy A", "jpeg",
             "https://camera1.iticfoundation.org/jpeg2.php?camid=10.8.0.14:8001"),
            ("Rama4 x Expy B", "jpeg",
             "https://camera1.iticfoundation.org/jpeg2.php?camid=10.8.0.14:8003"),
            ("Rama4 x Expy C", "jpeg",
             "https://camera1.iticfoundation.org/jpeg2.php?camid=10.8.0.14:8002"),
            ("Sathorn Embassy", "jpeg",
             "https://camera1.iticfoundation.org/jpeg2.php?camid=10.8.0.15:8002"),
        ],
    },
    # DOH national highway network — Wowza HLS on 180.180.242.207/208
    # (same infra DOHWeb uses; camera list probed 2026-10-01 — 72 live
    # PER_* streams on Phase3/7/9/10 alone; this is a Bangkok-and-ring
    # subset. Site IDs match DOHWeb survey-station codes.)
    "dohweb": {
        "interval": 120,
        "warm": 900,
        "cams": [
            ("Vibhavadi Don Mueang IN", "hls",
             "https://camerai1.iticfoundation.org/pass/180.180.242.207:1935/Phase3/PER_3_008_IN.stream/playlist.m3u8",
             "http://180.180.242.207:1935/Phase3/PER_3_008_IN.stream/playlist.m3u8"),
            ("Min Buri Hwy304 IN", "hls",
             "https://camerai1.iticfoundation.org/pass/180.180.242.207:1935/Phase9/PER_9_027_IN.stream/playlist.m3u8",
             "http://180.180.242.207:1935/Phase9/PER_9_027_IN.stream/playlist.m3u8"),
            ("Bang Pu Sukhumvit OUT", "hls",
             "http://180.180.242.207:1935/Phase9/PER_9_022_OUT.stream/playlist.m3u8"),
            ("Hwy303 Phra Samut Chedi IN", "hls",
             "http://180.180.242.208:1935/Phase12/PER_12_015_IN.stream/playlist.m3u8"),
            ("Hwy302 Suwinthawong km54", "hls",
             "http://180.180.242.207:1935/Phase3/PER_3_005_IN.stream/playlist.m3u8"),
            ("Hwy320 Pathum Thani km15", "hls",
             "http://180.180.242.207:1935/Phase3/PER_3_015.stream/playlist.m3u8"),
            ("Hwy302 Lam Luk Ka km5", "hls",
             "http://180.180.242.207:1935/Phase3/PER_3_017.stream/playlist.m3u8"),
            ("Hwy21 Saraburi km530", "hls",
             "http://180.180.242.207:1935/Phase7/PER_7_002.stream/playlist.m3u8"),
            ("Hwy305 km55", "hls",
             "http://180.180.242.207:1935/Phase7/PER_7_017.stream/playlist.m3u8"),
            ("Hwy32 Ayutthaya km95 IN", "hls",
             "http://180.180.242.207:1935/Phase10/PER_10_016_IN.stream/playlist.m3u8"),
        ],
    },
}

YTDLP = os.environ.get("YTDLP", str(Path.home() / ".local/bin/yt-dlp"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
CAMERAS_JSON = Path(os.environ.get(
    "CAMERAS_JSON",
    str(Path(__file__).resolve().parents[2] / "frigate" / "cameras.json")))
YT_CACHE_TTL = 4 * 3600  # yt live manifest URLs expire (~6h); re-resolve often
_yt_cache: dict[str, tuple[float, str]] = {}

# camera registry group -> wall zone for traffic cams (frigate/cameras.json
# is the SSOT; streams are DOH/iTIC HLS playlists snapshotted via ffmpeg).
TRAFFIC_ZONE_MAP = {
    "Traffic": "traffic",
    "ทางพิเศษบูรพาวิถี": "burapha",
    "ชลบุรี": "chonburi",
}
TRAFFIC_INTERVAL = 120  # hls grabs ~3-8s each, parallel — 2min is plenty


def load_traffic_zones() -> dict[str, dict]:
    """Build zones from the camera registry (frigate/cameras.json).

    Each enabled cam with an hls_url becomes ("title", "hls", url, alts...);
    alt_urls are tried in order when the primary playlist stalls/dies.
    A missing/unreadable registry just means no traffic zones.
    """
    try:
        reg = json.loads(CAMERAS_JSON.read_text())
    except Exception as exc:
        print(f"traffic zones: cannot read {CAMERAS_JSON}: {exc}",
              file=sys.stderr)
        return {}
    zones: dict[str, dict] = {}
    for cam in reg.get("cameras", []):
        zone = TRAFFIC_ZONE_MAP.get(cam.get("group"))
        if not zone or not cam.get("enabled", True):
            continue
        url = cam.get("hls_url")
        if not url:
            continue
        alts = [u for u in cam.get("alt_urls") or [] if u != url]
        entry = (cam.get("title") or cam.get("name") or url,
                 "hls", url, *alts)
        zones.setdefault(zone, {"interval": TRAFFIC_INTERVAL,
                                "warm": 900,
                                "cams": []})["cams"].append(entry)
    return zones


ZONES.update(load_traffic_zones())


def slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def http_get(url: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def bridge(path: str) -> dict:
    _, data = http_get(BRIDGE + path, 10)
    return json.loads(data)


def _yt_stream_url(video_id: str) -> str:
    """Resolve a youtube live/video id to a streamable URL, cached ~4h
    (googlevideo manifests expire; re-resolve on demand or expiry)."""
    hit = _yt_cache.get(video_id)
    if hit and time.time() - hit[0] < YT_CACHE_TTL:
        return hit[1]
    out = subprocess.run(
        [YTDLP, "-g", f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True, timeout=45)
    url = (out.stdout.splitlines() or [""])[0].strip()
    if not url.startswith("http"):
        raise ValueError(f"yt-dlp resolve failed: {out.stderr[:80]}")
    _yt_cache[video_id] = (time.time(), url)
    return url


def _ffmpeg_frame(src: str, timeout: float = 40, hls: bool = False) -> bytes:
    cmd = [FFMPEG, "-y", "-loglevel", "error"]
    if hls:
        # DOH/iTIC playlists regularly stall mid-read — cap socket waits so
        # a hung segment doesn't eat the whole cam budget
        cmd += ["-rw_timeout", "15000000", "-timeout", "15000000"]
    cmd += ["-i", src,
            "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-"]
    out = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if not out.stdout.startswith(b"\xff\xd8"):
        raise ValueError(f"ffmpeg frame failed: {out.stderr.decode()[:80]}")
    return out.stdout


def pull_cam(kind: str, key: str, alts: tuple = ()) -> bytes:
    if kind == "vms":
        url = f"{VMS_SNAP}/snap?ch={urllib.parse.quote(key)}"
        # dead-pane polling + serialized Wine UI can push a snap to ~40s;
        # 60s leaves headroom without letting a wedged snap eat the budget
        _, data = http_get(url, 60)
        return data
    if kind == "hls":
        # traffic-cam HLS playlist -> single frame; try alt_urls in order
        # (DOH cams mirror across 180.180.242.20x and highwaytraffic.go.th)
        last: Exception | None = None
        for u in (key, *alts):
            try:
                return _ffmpeg_frame(u, timeout=50, hls=True)
            except Exception as exc:
                last = exc
        raise ValueError(f"hls frame failed ({len(alts) + 1} urls): {last}")
    if kind == "jpeg":
        # direct traffic-cam still (iTIC jpeg2.php etc). Dead cams serve a
        # ~43B 'not found' stub or a fixed ~3KB 'No sengnal' jpeg — real
        # frames are ~20KB+.
        _, data = http_get(key, 20)
        if len(data) < 8000 or not data.startswith(b"\xff\xd8"):
            raise ValueError(f"dead frame ({len(data)}B)")
        return data
    if kind == "youtube":
        try:
            return _ffmpeg_frame(_yt_stream_url(key))
        except Exception:
            _yt_cache.pop(key, None)          # stale manifest — re-resolve once
            return _ffmpeg_frame(_yt_stream_url(key))
    # go2rtc: try the stream, then fall back to base/SD variants — an _hd
    # stream can be dead (200 + empty body) while the plain one is alive
    for v in [key, key.removesuffix("_hd"), key.removesuffix("_hd") + "_sd"]:
        try:
            _, data = http_get(
                f"{GO2RTC}/api/frame.jpeg?src={urllib.parse.quote(v)}", 20)
            if len(data) >= 500:
                return data
        except Exception:
            continue
    raise ValueError(f"empty frame from {key} (all variants)")


# ---------------------------------------------------------------------------
# effects pipeline — post-process thumbs before write.
# effect strings: "thumb_w:480" "jpeg_q:5" "timestamp" "grid"
#                 "yolo" | "yolo:person,car@0.4"  (classes + conf)
# yolo runs lazily on first use; detections are recorded per zone while the
# effect is on (detections-<zone>.jsonl — the "on duration" log).
# ---------------------------------------------------------------------------
COCO = ("person bicycle car motorcycle airplane bus train truck boat "
        "traffic_light fire_hydrant stop_sign parking_meter bench bird cat "
        "dog horse sheep cow elephant bear zebra giraffe backpack umbrella "
        "handbag tie suitcase frisbee skis snowboard sports_ball kite "
        "baseball_bat baseball_glove skateboard surfboard tennis_racket "
        "bottle wine_glass cup fork knife spoon bowl banana apple sandwich "
        "orange broccoli carrot hot_dog pizza donut cake chair couch "
        "potted_plant bed dining_table toilet tv laptop mouse remote "
        "keyboard cell_phone microwave oven toaster sink refrigerator book "
        "clock vase scissors teddy_bear hair_drier toothbrush").split()
YOLO_MODEL = os.environ.get(
    "CAMWALL_YOLO", str(Path.home() / ".local/share/camwall/yolov8n.onnx"))
_yolo = None

# default thumb width — wall cells are ~380px; 960 covers ~2.5x zoom.
# zones override via settings.thumb_w; thumb_w:0 keeps full-res frames.
THUMB_W = int(os.environ.get("CAMWALL_THUMB_W", "960"))
# serial VMS snaps run ~12-40s each (~33s+ when the shim's pane is dead).
# Cap the serial section per zone so a degraded VMS can't push one cycle
# past TimeoutStartSec — skipped cams keep their last thumbs.
VMS_BUDGET = float(os.environ.get("CAMWALL_VMS_BUDGET", "180"))


def _yolo_session():
    global _yolo
    if _yolo is None:
        import onnxruntime as ort
        _yolo = ort.InferenceSession(
            YOLO_MODEL, providers=["CPUExecutionProvider"])
    return _yolo


def _yolo_detect(img, classes: set, conf: float) -> list[dict]:
    """YOLOv8n on a PIL image -> [{cls, conf, box:[x1,y1,x2,y2]}] in img px."""
    import numpy as np
    W, H = img.size
    im = img.resize((640, 640))
    x = np.asarray(im, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    pred = _yolo_session().run(None, {"images": x})[0][0]  # (84, 8400)
    boxes, scores, cls_ids = [], [], []
    for i in range(pred.shape[1]):
        p = pred[:, i]
        c = int(p[4:].argmax())
        s = float(p[4 + c])
        if s < conf or (classes and COCO[c] not in classes):
            continue
        cx, cy, w, h = p[:4]
        boxes.append([cx - w / 2, cy - h / 2, w, h])
        scores.append(s)
        cls_ids.append(c)
    # greedy NMS @ IoU 0.45
    keep: list[int] = []
    order = sorted(range(len(boxes)), key=lambda i: -scores[i])
    while order:
        i = order.pop(0)
        keep.append(i)
        order = [j for j in order if _iou(boxes[i], boxes[j]) < 0.45]
    sx, sy = W / 640.0, H / 640.0
    out = []
    for i in keep:
        x1, y1, w, h = boxes[i]
        out.append({"cls": COCO[cls_ids[i]], "conf": round(scores[i], 2),
                    "box": [round(x1 * sx), round(y1 * sy),
                            round((x1 + w) * sx), round((y1 + h) * sy)]})
    return out


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def apply_effects(data: bytes, effects: list[str]) -> tuple[bytes, list[dict]]:
    """bytes -> PIL -> effects -> jpeg bytes (+ yolo detections)."""
    import io
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(data)).convert("RGB")
    tw, q, dets = 0, 0, []
    for eff in effects:
        if eff.startswith("thumb_w:"):
            tw = int(eff.split(":")[1])
        elif eff.startswith("jpeg_q:"):
            q = int(eff.split(":")[1])
        elif eff.startswith("yolo"):
            classes, conf = set(), 0.4
            if ":" in eff:
                spec = eff.split(":", 1)[1]
                if "@" in spec:
                    spec, c = spec.rsplit("@", 1)
                    conf = float(c)
                classes = {c.strip() for c in spec.split(",") if c.strip()}
            dets = _yolo_detect(img, classes, conf)
            dr = ImageDraw.Draw(img)
            for d in dets:
                dr.rectangle(d["box"], outline=(46, 160, 255), width=2)
                dr.text((d["box"][0] + 2, d["box"][1] + 2),
                        f"{d['cls']} {d['conf']}", fill=(46, 160, 255))
        elif eff == "timestamp":
            ImageDraw.Draw(img).text(
                (6, img.height - 18),
                time.strftime("%H:%M:%S"), fill=(255, 255, 0))
        elif eff == "grid":
            dr = ImageDraw.Draw(img)
            for f in (1 / 3, 2 / 3):
                dr.line([(img.width * f, 0), (img.width * f, img.height)],
                        fill=(255, 255, 255, 60))
                dr.line([(0, img.height * f), (img.width, img.height * f)],
                        fill=(255, 255, 255, 60))
    if tw and img.width > tw:
        img = img.resize((tw, int(img.height * tw / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality={0: 80}.get(q, min(95, max(10, 95 - q * 8))))
    return buf.getvalue(), dets


# ---------------------------------------------------------------------------
# status cards — every failed cam renders a generated status image instead of
# a broken tile (ssot.apps.camwall: guaranteed-image standard). Classes:
#   offline — never had a frame, or thumb older than DEAD_AFTER
#   stale   — pull failed, last-good thumb kept (dimmed + banner)
#   delayed — skipped by VMS budget this cycle (dimmed thumb or slate card)
#   error   — anything else (slate card with short reason)
# Written as <key>-status.jpg; deleted on the next successful pull.
# ---------------------------------------------------------------------------
FONT_EN = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# Loma covers Thai + Latin in one file (bilingual cam labels); keep fallbacks.
FONT_BI = [
    "/usr/share/fonts/truetype/tlwg/Loma-Bold.ttf",
    "/usr/share/fonts/opentype/tlwg/Loma-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
]
DEAD_AFTER = 6 * 3600  # stale thumb older than this -> 'offline' card


def _font(path: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _font_bi(size: int):
    from PIL import ImageFont
    for p in FONT_BI:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return _font(FONT_EN, size)


def _age_txt(age_s: int | None) -> str:
    if age_s is None:
        return "never"
    if age_s < 3600:
        return f"{age_s // 60}m ago"
    if age_s < 86400:
        return f"{age_s // 3600}h{(age_s % 3600) // 60}m ago"
    return f"{age_s // 86400}d ago"


def status_card(label: str, issue: str, age_s: int | None,
                thumb: bytes | None) -> bytes:
    """960x540 display image for a failed cam: dimmed last-good thumb with
    an issue banner when we have one, else a generated slate card."""
    import io
    from PIL import Image, ImageDraw, ImageEnhance
    W, H = 960, 540
    big = _font(FONT_EN, 54)
    med = _font(FONT_EN, 30)
    th = _font_bi(30)
    small = _font(FONT_EN, 24)
    if thumb:
        try:
            img = Image.open(io.BytesIO(thumb)).convert("RGB")
            img = img.resize((W, int(img.height * W / img.width)))
            if img.height > H:
                img = img.crop((0, (img.height - H) // 2, W,
                                (img.height - H) // 2 + H))
            elif img.height < H:
                bg = Image.new("RGB", (W, H), (12, 14, 18))
                bg.paste(img, (0, (H - img.height) // 2))
                img = bg
            img = ImageEnhance.Brightness(img).enhance(0.38)
        except Exception:
            thumb = None
    if not thumb:
        img = Image.new("RGB", (W, H), (16, 18, 24) if issue == "offline"
                        else (28, 30, 38))
    dr = ImageDraw.Draw(img, "RGBA")
    title, th_line, color = {
        "offline": ("OFFLINE", "กล้องออฟไลน์", (235, 87, 87)),
        "stale":   ("STALE", "ภาพเก่า ไม่ใช่ภาพสด", (240, 173, 78)),
        "delayed": ("DELAYED", "รอสัญญาณชั่วคราว", (120, 172, 255)),
        "error":   ("NO SIGNAL", "ดึงภาพไม่สำเร็จ", (200, 90, 200)),
    }.get(issue, ("NO SIGNAL", "ดึงภาพไม่สำเร็จ", (200, 90, 200)))
    # banner strip + label — bilingual font (Loma covers Thai + Latin) for
    # any label containing non-ASCII; DejaVu otherwise.
    label_font = th if any(ord(ch) > 127 for ch in label) else med
    dr.rectangle((0, 0, W, 96), fill=(0, 0, 0, 150))
    dr.text((20, 14), label, font=label_font, fill=(230, 235, 240))
    dr.text((W - 20, 60), f"last frame {_age_txt(age_s)}",
            font=small, fill=(160, 168, 178), anchor="ra")
    # centered issue block
    tw = dr.textlength(title, font=big)
    dr.text(((W - tw) / 2, H // 2 - 84), title, font=big, fill=color)
    tw2 = dr.textlength(th_line, font=th)
    dr.text(((W - tw2) / 2, H // 2 - 10), th_line, font=th, fill=color)
    if not thumb:
        dr.text((20, H - 44), "camwall · last-good cache", font=small,
                fill=(90, 96, 108))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def write_status_card(zdir: Path, key: str, label: str, issue: str,
                      ts: int) -> None:
    """(Re)write <key>-status.jpg for a failed cam."""
    p = zdir / f"{key}.jpg"
    thumb = p.read_bytes() if p.exists() else None
    if not thumb or not ts or (time.time() - ts) > DEAD_AFTER:
        # no frame ever, or last-good is beyond the dead horizon — keep the
        # dimmed backdrop if there is one, but the issue is 'offline'
        issue = "offline"
    elif issue != "delayed":
        issue = "stale"
    try:
        data = status_card(label, issue,
                           int(time.time() - ts) if ts else None, thumb)
        f = zdir / f"{key}-status.jpg"
        tmp = f.with_suffix(".jpg.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
    except Exception as exc:
        print(f"{zdir.name}/{key}: status card failed: {exc}",
              file=sys.stderr)


def bake_montage(zdir: Path, cams: list[dict], thumb_w: int = 480) -> None:
    """Composite the zone's thumbs into one jpg for the index page.
    Guaranteed-image contract: a cam with a cached thumb always appears —
    stale tiles render dimmed with a 'stale' tag, never dropped."""
    from PIL import Image, ImageEnhance
    tiles = []
    for c in cams:
        # !ok cams show their generated status card (banner baked in);
        # fall back to dimmed last-good if the card wasn't written
        status = zdir / f"{c['key']}-status.jpg"
        p = (status if not c.get("ok") and status.exists()
             else zdir / f"{c['key']}.jpg")
        if not p.exists():
            continue
        try:
            im = Image.open(p).convert("RGB")
            h = int(im.height * thumb_w / im.width)
            im = im.resize((thumb_w, h))
            label = c["label"]
            if not c.get("ok") and p == zdir / f"{c['key']}.jpg":
                im = ImageEnhance.Brightness(im).enhance(0.45)
                label = f"{label} · stale"
            tiles.append((im, label))
        except Exception:
            pass
    if not tiles:
        return
    cols = 3
    th = max(t.height for t, _ in tiles)
    rows = (len(tiles) + cols - 1) // cols
    from PIL import ImageDraw
    canvas = Image.new("RGB", (cols * thumb_w, rows * (th + 18)), (8, 8, 8))
    dr = ImageDraw.Draw(canvas)
    for i, (im, label) in enumerate(tiles):
        x, y = (i % cols) * thumb_w, (i // cols) * (th + 18)
        canvas.paste(im, (x, y))
        dr.text((x + 6, y + th + 2), label, fill=(140, 170, 200))
    canvas.save(zdir / "montage.jpg", "JPEG", quality=80)


def merge_settings(cfg: dict, settings: dict | None) -> dict:
    """Relay per-zone settings override the static ZONES defaults."""
    if not settings:
        return cfg
    eff = dict(cfg)
    cams = [c for c in cfg["cams"]
            if slug(c[0]) not in (settings.get("cams_skip") or [])]
    for extra in settings.get("cams_extra") or []:
        cams.append((extra.get("label") or "cam",
                     extra.get("kind") or "jpeg",
                     extra.get("url") or ""))
    eff["cams"] = cams
    for k in ("interval", "warm"):
        if isinstance(settings.get(k), (int, float)):
            eff[k] = max(15, int(settings[k]))
    eff["effects"] = list(settings.get("effects") or [])
    if isinstance(settings.get("thumb_w"), (int, float)):
        eff["effects"].append(f"thumb_w:{int(settings['thumb_w'])}")
    if isinstance(settings.get("jpeg_q"), (int, float)):
        eff["effects"].append(f"jpeg_q:{int(settings['jpeg_q'])}")
    return eff


def pull_zone(zone: str, cfg: dict, zdir: Path) -> dict:
    """Pull all cams for a zone; write thumbs; return manifest dict."""
    cams = []
    vms = [c for c in cfg["cams"] if c[1] == "vms"]
    fast = [c for c in cfg["cams"] if c[1] != "vms"]

    effects = cfg.get("effects") or []
    if not any(e.startswith("thumb_w:") for e in effects):
        effects = [*effects, f"thumb_w:{THUMB_W}"]

    def one(cam: tuple) -> dict:
        label, kind, key = cam[0], cam[1], cam[2]
        alts = tuple(cam[3:])
        out = {"key": slug(label), "label": label, "ts": 0, "ok": False}
        try:
            data = pull_cam(kind, key, alts)
            if len(data) < 500:
                raise ValueError("short frame")
            if effects:
                try:
                    data, dets = apply_effects(data, effects)
                    if dets:
                        out["det"] = {d["cls"]: sum(
                            1 for x in dets if x["cls"] == d["cls"])
                            for d in dets}
                        out["dets"] = dets
                except Exception as exc:
                    out["fx_err"] = str(exc)[:100]
            jp = zdir / f"{out['key']}.jpg"
            tmp = jp.with_suffix(".jpg.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, jp)  # atomic — wall page never reads half a jpg
            out.update(ts=int(time.time()), ok=True, bytes=len(data))
            (zdir / f"{out['key']}-status.jpg").unlink(missing_ok=True)
        except Exception as exc:
            out["err"] = str(exc)[:120]
            prev = zdir / f"{out['key']}.jpg"
            if prev.exists():
                out["ts"] = int(prev.stat().st_mtime)  # keep stale ts
            write_status_card(zdir, out["key"], label, "error",
                              out["ts"])
        return out

    # independent-source cams in parallel, then VMS serially (one Wine UI)
    with ThreadPoolExecutor(max_workers=4) as pool:
        cams += list(pool.map(one, fast))
    t_vms = time.time()
    for cam in vms:
        if time.time() - t_vms > VMS_BUDGET:
            out = {"key": slug(cam[0]), "label": cam[0], "ts": 0,
                   "ok": False, "err": "skipped: vms budget"}
            prev = zdir / f"{out['key']}.jpg"
            if prev.exists():
                out["ts"] = int(prev.stat().st_mtime)
            write_status_card(zdir, out["key"], cam[0], "delayed",
                              out["ts"])
            cams.append(out)
            continue
        cams.append(one(cam))
    try:
        bake_montage(zdir, cams)
    except Exception as exc:
        print(f"{zone}: montage failed: {exc}", file=sys.stderr)
    # detections roll into a per-zone rolling log while a yolo effect is on
    if any(e.startswith("yolo") for e in effects):
        recs = [c for c in cams if c.get("dets")]
        if recs:
            line = json.dumps({"zone": zone, "ts": int(time.time()),
                               "cams": {c["key"]: c["dets"] for c in recs}})
            with (zdir / f"detections-{zone}.jsonl").open("a") as f:
                f.write(line + "\n")
    return {"zone": zone, "updated": int(time.time()), "cams": cams}


def _vms_backoff(zone: str, cfg: dict, manifest: Path) -> bool:
    """VMS outage backoff: when every vms cam in the zone failed last
    cycle, require 4x the interval before retrying — serial dead-P2P
    snaps burn ~35s each, and enabled zones otherwise starve every
    other zone each cycle while a DVR stays offline."""
    vms_keys = {slug(c[0]) for c in cfg["cams"] if c[1] == "vms"}
    if not vms_keys or not manifest.exists():
        return False
    try:
        prev = json.loads(manifest.read_text()).get("cams", [])
        vms_prev = [c for c in prev if c.get("key") in vms_keys]
        return bool(vms_prev) and not any(c.get("ok") for c in vms_prev)
    except Exception:
        return False


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="pull every zone once, ignoring enable state")
    ap.add_argument("--only", default="",
                    help="comma-separated zones to pull once (ignores enable)")
    args = ap.parse_args()
    only = {z.strip() for z in args.only.split(",") if z.strip()}

    try:
        state = bridge("/camwall")
    except Exception as exc:
        print(f"camwall state unreachable: {exc}", file=sys.stderr)
        state = {}

    zones = state.get("zones") or {}
    # host ownership — CAMWALL_OWN="burapha,chonburi" means this instance
    # pulls only those zones; the peer host owns the rest. Empty = all
    # (legacy single-host behaviour). Prevents two pullers racing the same
    # zone's manifest.
    own = {z.strip() for z in
           os.environ.get("CAMWALL_OWN", "").split(",") if z.strip()}
    # forced/CLI zones first — a --only run shouldn't queue behind a
    # multi-minute VMS dead-pull warm sweep
    order = sorted(ZONES, key=lambda z: 0 if (args.all or z in only) else 1)
    for zone in order:
        if own and zone not in own and zone not in only and not args.all:
            continue
        cfg = merge_settings(
            ZONES[zone], (zones.get(zone) or {}).get("settings"))
        enabled = bool((zones.get(zone) or {}).get("enabled"))
        forced = args.all or zone in only
        if forced:
            interval = 0
        elif enabled:
            interval = cfg["interval"]
        else:
            interval = cfg.get("warm") or 0
        if not interval and not forced:
            continue
        zdir = DATA / zone
        zdir.mkdir(parents=True, exist_ok=True)
        manifest = zdir / f"manifest-{zone}.json"
        # skip a pull while thumbs are still fresh enough
        if manifest.exists() and not forced:
            try:
                last = json.loads(manifest.read_text()).get("updated", 0)
                wait = interval
                if _vms_backoff(zone, cfg, manifest):
                    wait = interval * 4
                if time.time() - last < wait:
                    continue
            except Exception:
                pass
        man = pull_zone(zone, cfg, zdir)
        mf = zdir / f"manifest-{zone}.json"
        tmp = mf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(man))
        os.replace(tmp, mf)  # atomic — a page fetch never reads half a file
        ok = sum(1 for c in man["cams"] if c.get("ok"))
        mode = "enabled" if enabled else "warm" if not forced else "forced"
        print(f"{zone}: {ok}/{len(man['cams'])} thumbs refreshed ({mode})")
    if own:
        _push_zones(own)
    return 0


def _push_zones(zones: set[str]) -> None:
    """rsync this host's zone dirs to the peer's data dir so both edges
    serve the full set. CAMWALL_PUSH = 'user@host:/path/to/data' — each
    puller pushes only the zones it owns, so there is no write overlap."""
    target = os.environ.get("CAMWALL_PUSH", "").rstrip("/")
    if not target:
        return
    for zone in sorted(zones):
        zdir = DATA / zone
        if not zdir.is_dir():
            continue
        r = subprocess.run(
            ["rsync", "-a", "--delete", f"{zdir}/",
             f"{target}/{zone}/"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"push {zone} -> {target}: {r.stderr.strip()[:200]}",
                  file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
