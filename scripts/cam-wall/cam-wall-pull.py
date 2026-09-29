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
        # leave headroom so honest 503s aren't cut off as timeouts
        _, data = http_get(url, 95)
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


def pull_zone(zone: str, cfg: dict, zdir: Path) -> dict:
    """Pull all cams for a zone; write thumbs; return manifest dict."""
    cams = []
    vms = [c for c in cfg["cams"] if c[1] == "vms"]
    fast = [c for c in cfg["cams"] if c[1] != "vms"]

    def one(cam: tuple) -> dict:
        label, kind, key = cam[0], cam[1], cam[2]
        alts = tuple(cam[3:])
        out = {"key": slug(label), "label": label, "ts": 0, "ok": False}
        try:
            data = pull_cam(kind, key, alts)
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
        cams += list(pool.map(one, fast))
    for cam in vms:
        cams.append(one(cam))
    return {"zone": zone, "updated": int(time.time()), "cams": cams}


def _vms_backoff(zone: str, cfg: dict, manifest: Path) -> bool:
    """VMS outage backoff for warm pulls: when every vms cam in the zone
    failed last cycle, require 4x the warm interval before retrying —
    serial dead-P2P snaps burn ~35s each."""
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
    # forced/CLI zones first — a --only run shouldn't queue behind a
    # multi-minute VMS dead-pull warm sweep
    order = sorted(ZONES, key=lambda z: 0 if (args.all or z in only) else 1)
    for zone in order:
        cfg = ZONES[zone]
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
                if not enabled and _vms_backoff(zone, cfg, manifest):
                    wait = interval * 4
                if time.time() - last < wait:
                    continue
            except Exception:
                pass
        man = pull_zone(zone, cfg, zdir)
        (zdir / f"manifest-{zone}.json").write_text(json.dumps(man))
        ok = sum(1 for c in man["cams"] if c.get("ok"))
        mode = "enabled" if enabled else "warm" if not forced else "forced"
        print(f"{zone}: {ok}/{len(man['cams'])} thumbs refreshed ({mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
