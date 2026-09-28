#!/usr/bin/env python3
"""cam-wall puller — periodic CCTV thumbnails for enabled zones.

Runs on tony-dell (systemd timer every 30s). Each run:
  1. GET input-bridge /camwall on idc01 -> which zones are enabled
  2. For each enabled zone whose thumbs are older than its interval:
       house cams  -> go2rtc frame.jpeg on 127.0.0.1:1984 (parallel, ~4s)
       VMS cams    -> mn01 vms-snap shim 8377 (serial — one Wine UI, ~12s each)
       traffic     -> jpeg: direct GET (~0.3s) | youtube: yt-dlp -g
                      (cached ~4h) + ffmpeg -frames:v 1 (~5-10s)
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

# label -> ("vms", channel) | ("go2rtc", stream)
ZONES: dict[str, dict] = {
    "zone-a": {
        "interval": 75,  # ~5 serial vms pulls ~= 60s + margin
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
}

YTDLP = os.environ.get("YTDLP", str(Path.home() / ".local/bin/yt-dlp"))
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
YT_CACHE_TTL = 4 * 3600  # yt live manifest URLs expire (~6h); re-resolve often
_yt_cache: dict[str, tuple[float, str]] = {}


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


def _ffmpeg_frame(src: str, timeout: float = 40) -> bytes:
    out = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", src,
         "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-"],
        capture_output=True, timeout=timeout)
    if not out.stdout.startswith(b"\xff\xd8"):
        raise ValueError(f"ffmpeg frame failed: {out.stderr.decode()[:80]}")
    return out.stdout


def pull_cam(kind: str, key: str) -> bytes:
    if kind == "vms":
        url = f"{VMS_SNAP}/snap?ch={urllib.parse.quote(key)}"
        # dead-pane polling + serialized Wine UI can push a snap to ~40s;
        # leave headroom so honest 503s aren't cut off as timeouts
        _, data = http_get(url, 95)
        return data
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


def pull_zone(zone: str, cfg: dict, zdir: Path) -> dict:
    """Pull all cams for a zone; write thumbs; return manifest dict."""
    cams = []
    vms = [(label, key) for label, kind, key in cfg["cams"] if kind == "vms"]
    fast = [(label, kind, key) for label, kind, key in cfg["cams"]
            if kind != "vms"]

    def one(label: str, key: str, kind: str) -> dict:
        out = {"key": slug(label), "label": label, "ts": 0, "ok": False}
        try:
            data = pull_cam(kind, key)
            if len(data) < 500:
                raise ValueError("short frame")
            (zdir / f"{out['key']}.jpg").write_bytes(data)
            out.update(ts=int(time.time()), ok=True, bytes=len(data))
        except Exception as exc:
            out["err"] = str(exc)[:120]
            prev = zdir / f"{out['key']}.jpg"
            if prev.exists():
                out["ts"] = int(prev.stat().st_mtime)  # keep stale ts
        return out

    # independent-source cams in parallel, then VMS serially (one Wine UI)
    with ThreadPoolExecutor(max_workers=4) as pool:
        cams += list(pool.map(lambda lk: one(lk[0], lk[2], lk[1]), fast))
    for label, key in vms:
        cams.append(one(label, key, "vms"))
    return {"zone": zone, "updated": int(time.time()), "cams": cams}


def main() -> int:
    try:
        state = bridge("/camwall")
    except Exception as exc:
        print(f"camwall state unreachable: {exc}", file=sys.stderr)
        return 0  # keep last thumbs; page shows stale ages

    zones = state.get("zones") or {}
    for zone, cfg in ZONES.items():
        if not (zones.get(zone) or {}).get("enabled"):
            continue
        zdir = DATA / zone
        zdir.mkdir(parents=True, exist_ok=True)
        manifest = zdir / f"manifest-{zone}.json"
        # skip a pull while thumbs are still fresh enough
        if manifest.exists():
            try:
                last = json.loads(manifest.read_text()).get("updated", 0)
                if time.time() - last < cfg["interval"]:
                    continue
            except Exception:
                pass
        man = pull_zone(zone, cfg, zdir)
        (zdir / f"manifest-{zone}.json").write_text(json.dumps(man))
        ok = sum(1 for c in man["cams"] if c.get("ok"))
        print(f"{zone}: {ok}/{len(man['cams'])} thumbs refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
