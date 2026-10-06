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
                      Zones carrying a registry_group in zones.yml are
                      generated from frigate/cameras.json (registry SSOT).
  3. Write <DATA>/<zone>/<slug>.jpg + manifest-<zone>.json
     (served at https://tony-dell.taila0626a.ts.net/apps/camwall/data/)

Ada controls zones via the cctv_wall tool (POST /camwall). If the relay is
unreachable the previous state is reused so a network blip doesn't blank
the wall; a down zone simply keeps its last thumbs with stale mtimes.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRIDGE = os.environ.get(
    "VCAST_API", "https://tony-dell.taila0626a.ts.net/api/input-bridge")
VMS_SNAP = os.environ.get("VMS_SNAP_URL", "http://100.106.196.22:8377")
GO2RTC = os.environ.get("GO2RTC_URL", "http://127.0.0.1:1984")

DATA = Path(os.environ.get(
    "CAMWALL_DATA",
    str(Path.home() / "CascadeProjects/chaba-tony-dell/stacks/web/public/apps/camwall/data")))

# Zone roster + classification live in zones.yml next to this script —
# the single SSOT for zone->tab mapping and camera membership (see
# zone_meta.py for the group/site/tab semantics). zone-a and noble-park
# were retired 2026-10-02 (subsets of the per-DVR walls; each duplicate
# pull burned ~80s of the shared serial VMS budget) — retired zones are
# simply absent from zones.yml.
import zone_meta  # noqa: E402 — sibling module, script dir on sys.path

ZMETA = zone_meta.load()
# slug(label) -> display label overrides (walls/dossiers render these;
# tuple labels stay ASCII so jpg/CMS keys stay stable)
LABELS = zone_meta.labels(ZMETA)

# zone -> {"interval", "warm", "cams": [(label, kind, key, *alt_urls)]}
# kind: "vms" (channel) | "go2rtc" (stream) | "jpeg"|"youtube"|"hls" (url)
# interval = refresh cadence while the zone is enabled; warm = keep thumbs
# fresh while DISABLED so casting a cold wall still shows recent frames.
# VMS zones get outage backoff: a dead P2P uplink makes each serial snap
# burn ~35s — when every vms cam in a zone failed last cycle, the warm
# wait is quadrupled.

YTDLP = os.environ.get("YTDLP", str(Path.home() / ".local/bin/yt-dlp"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
CAMERAS_JSON = Path(os.environ.get(
    "CAMERAS_JSON",
    str(Path(__file__).resolve().parents[2] / "frigate" / "cameras.json")))
YT_CACHE_TTL = 4 * 3600  # yt live manifest URLs expire (~6h); re-resolve often
_yt_cache: dict[str, tuple[float, str]] = {}


def load_registry_zones() -> dict[str, dict]:
    """Build zones from the camera registry (frigate/cameras.json).

    Zones with a `registry_group` in zones.yml take every enabled registry
    cam whose `group` matches and that has an hls_url — each becomes
    ("title", "hls", url, alts...); alt_urls are tried in order when the
    primary playlist stalls/dies. A missing/unreadable registry just
    means no registry zones.
    """
    try:
        reg = json.loads(CAMERAS_JSON.read_text())
    except Exception as exc:
        print(f"registry zones: cannot read {CAMERAS_JSON}: {exc}",
              file=sys.stderr)
        return {}
    # registry `group` value -> (zone name, pull config), from zones.yml
    reg_map = {zd["registry_group"]: (name, zd)
               for name, zd in zone_meta.pull_zones(ZMETA).items()
               if zd.get("registry_group")}
    zones: dict[str, dict] = {}
    for cam in reg.get("cameras", []):
        hit = reg_map.get(cam.get("group"))
        if not hit or not cam.get("enabled", True):
            continue
        zone, zd = hit
        url = cam.get("hls_url")
        if not url:
            continue
        alts = [u for u in cam.get("alt_urls") or [] if u != url]
        entry = (cam.get("title") or cam.get("name") or url,
                 "hls", url, *alts)
        zones.setdefault(zone, {"interval": zd["interval"],
                                "warm": zd["warm"],
                                "cams": []})["cams"].append(entry)
    return zones


def load_zones() -> dict[str, dict]:
    """The puller roster: static cams from zones.yml + registry-expanded
    zones. A zone with no cams anywhere is skipped loudly, not pulled
    into an empty manifest."""
    out: dict[str, dict] = {}
    for name, zd in zone_meta.pull_zones(ZMETA).items():
        if zd.get("registry_group"):
            continue  # roster comes from the camera registry below
        if not zd["cams"]:
            print(f"{name}: zone has no cams in zones.yml — skipped",
                  file=sys.stderr)
            continue
        out[name] = {"interval": zd["interval"], "warm": zd["warm"],
                     "cams": zd["cams"]}
    out.update(load_registry_zones())
    return out


ZONES = load_zones()


def slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


# VMS channel -> DVR device map (canonical camera identity). channels.json
# is the xmeye-vms stack SSOT — the same file the snap shim resolves
# coordinates from.
VMS_CHANNELS_JSON = Path(os.environ.get(
    "VMS_CHANNELS_JSON",
    str(Path(__file__).resolve().parents[2]
        / "stacks" / "services" / "xmeye-vms" / "channels.json")))


def _load_vms_channels() -> dict[str, str]:
    try:
        raw = json.loads(VMS_CHANNELS_JSON.read_text())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for name, meta in raw.items():
        dev = (meta or {}).get("device")
        if not dev:
            continue
        out[name.lower()] = dev
        for a in meta.get("aliases") or []:
            out[str(a).lower()] = dev
    return out


_VMS_DEVS = _load_vms_channels()


def vms_device(channel: str) -> str | None:
    """resolve a channels.json name/alias -> DVR device (noble-club…)."""
    q = channel.lower()
    if q in _VMS_DEVS:
        return _VMS_DEVS[q]
    for name, dev in _VMS_DEVS.items():
        if q in name or name in q:
            return dev
    return None


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
        # zoom=0 takes the grid-res pane — wall thumbs don't need the
        # zoomed single-pane re-attach (12-36s/cam) that starved 8-cam
        # zones under VMS_BUDGET; ~15s/cam fits the whole zone in one pass.
        # native=1 takes the VMS's own OSD snapshot of the active pane —
        # the channel at native decode res (Mini Mart: 2560x1440 vs the old
        # 847x452 screen crop) for the same attach cost, ~+2s for the
        # icon->bmp->Save round trip.
        url = (f"{VMS_SNAP}/snap?ch={urllib.parse.quote(key)}"
               "&zoom=0&native=1")
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
# One-shot multi-pane composite: one /composite call per DVR group binds
# every channel to a monitor pane once and captures all panes in a single
# cycle — ~3s/cam once bound vs ~18s serial attach. Pane bindings persist,
# so steady-state refreshes stay cheap; a failed composite call falls back
# to the serial per-channel path. CAMWALL_VMS_COMPOSITE=0 disables.
VMS_COMPOSITE = os.environ.get("CAMWALL_VMS_COMPOSITE", "1") != "0"
VMS_COMPOSITE_TIMEOUT = float(
    os.environ.get("CAMWALL_VMS_COMPOSITE_TIMEOUT", "240"))


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
        elif eff.startswith("thumb_frac:"):
            tw = max(1, img.width // int(eff.split(":")[1]))
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
    if isinstance(settings.get("thumb_frac"), (int, float)):
        eff["effects"].append(f"thumb_frac:{int(settings['thumb_frac'])}")
    if isinstance(settings.get("jpeg_q"), (int, float)):
        eff["effects"].append(f"jpeg_q:{int(settings['jpeg_q'])}")
    return eff


def pull_zone(zone: str, cfg: dict, zdir: Path) -> dict:
    """Pull all cams for a zone; write thumbs; return manifest dict."""
    cams = []
    vms = [c for c in cfg["cams"] if c[1] == "vms"]
    fast = [c for c in cfg["cams"] if c[1] != "vms"]

    effects = cfg.get("effects") or []
    if not any(e.startswith("thumb_") for e in effects):
        effects = [*effects, f"thumb_w:{THUMB_W}"]

    def one(cam: tuple, data: bytes | None = None, err: str | None = None,
            via: str | None = None) -> dict:
        label, kind, key = cam[0], cam[1], cam[2]
        alts = tuple(cam[3:])
        out = {"key": slug(label), "label": LABELS.get(slug(label), label),
               "ts": 0, "ok": False}
        if via:
            out["via"] = via
        # canonical camera identity — vms channels carry DVR device+channel
        # so the same physical cam shares one CMS page no matter how many
        # walls list it (zone-a / vms-noble-a both pull "1. Road In").
        if kind == "vms":
            dev = vms_device(key)
            if dev:
                out["dev"] = dev
                out["ch"] = key
        try:
            if data is None:
                if err:                    # composite already reported a
                    raise ValueError(err)  # per-cam failure — don't re-pull
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
            write_status_card(zdir, out["key"], out["label"], "error",
                              out["ts"])
        return out

    # independent-source cams in parallel, then VMS serially (one Wine UI)
    with ThreadPoolExecutor(max_workers=4) as pool:
        cams += list(pool.map(one, fast))
    t_vms = time.time()
    # One-shot composite per DVR device: a single /composite call binds the
    # group's channels to monitor panes once and captures all panes in one
    # cycle (bindings persist — warm refreshes cost ~capture-only). Any
    # call-level failure pushes the whole group back to the serial path.
    pending: list[tuple] = []
    if VMS_COMPOSITE:
        groups: dict[str, list[tuple]] = {}
        for cam in vms:
            dev = vms_device(cam[2])
            (groups.setdefault(dev, []).append(cam) if dev
             else pending.append(cam))
        for dev, members in groups.items():
            if len(members) < 2 or time.time() - t_vms > VMS_BUDGET:
                pending.extend(members)
                continue
            # a composite call may not outlive the zone's VMS budget —
            # with the 240s default one dead-DVR group would otherwise eat
            # all 180s before the serial fallback ever ran (2026-10-06).
            ctimeout = min(VMS_COMPOSITE_TIMEOUT,
                           VMS_BUDGET - (time.time() - t_vms))
            if ctimeout < 30:
                pending.extend(members)
                continue
            url = (f"{VMS_SNAP}/composite?chs=" + ",".join(
                urllib.parse.quote(c[2]) for c in members))
            try:
                _, zdata = http_get(url, ctimeout)
                zf = zipfile.ZipFile(io.BytesIO(zdata))
                zman = {c["i"]: c for c in
                        json.loads(zf.read("_manifest.json"))["cams"]}
            except Exception as exc:
                print(f"{zone}: composite {dev} failed "
                      f"({str(exc)[:100]}) — serial fallback",
                      file=sys.stderr)
                pending.extend(members)
                continue
            for i, cam in enumerate(members):
                entry = zman.get(i) or {}
                data = None
                if entry.get("ok"):
                    try:
                        data = zf.read(f"{i}.png")
                    except KeyError:
                        entry["err"] = "composite: member missing from zip"
                cams.append(one(cam, data=data,
                                err=entry.get("err") or "composite: no frame",
                                via="composite"))
    else:
        pending = list(vms)
    for cam in pending:
        if time.time() - t_vms > VMS_BUDGET:
            out = {"key": slug(cam[0]), "label": LABELS.get(slug(cam[0]), cam[0]),
                   "ts": 0, "ok": False, "err": "skipped: vms budget"}
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
    # zones.yml classification rides inside the manifest — the CMS sidebar
    # and any other HTTP consumer get group/site/tab without guessing.
    cls = zone_meta.classify(zone, ZMETA)
    return {"zone": zone, "group": cls["group"], "site": cls["site"],
            "tab": cls["tab"], "updated": int(time.time()), "cams": cams}


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
    write_zones_index()
    if own:
        _push_zones(own)
    return 0


def write_zones_index() -> None:
    """DATA/zones.json — the web-readable mirror of zones.yml: tab labels
    + per-zone {group, site, tab, cams}. The CMS sidebar (ada-pi
    pwa/cms) fetches this ONE file instead of guessing tabs from slug
    prefixes; zones absent from zones.yml land in 'unsorted'."""
    if not DATA.is_dir():
        return
    idx = {"updated": int(time.time()),
           "tabs": zone_meta.tabs(ZMETA), "zones": {}}
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
        cls = zone_meta.classify(zone, ZMETA)
        idx["zones"][zone] = {
            "group": cls["group"], "site": cls["site"], "tab": cls["tab"],
            "cams": [{"key": c["key"], "label": c.get("label"),
                      **({"dev": c["dev"]} if c.get("dev") else {})}
                     for c in man.get("cams") or []]}
    try:
        tmp = DATA / "zones.json.tmp"
        tmp.write_text(json.dumps(idx, ensure_ascii=False))
        os.replace(tmp, DATA / "zones.json")
    except Exception as exc:
        print(f"zones.json write failed: {exc}", file=sys.stderr)


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
