#!/usr/bin/env python3
"""traffic-snap — HTTP snapshot shim for public Thai traffic cameras.

Sibling of vms-snap (XMEye CCTV, :8377): same endpoint contract, so any
consumer that already speaks `GET /snap?ch=<name>` can fetch a traffic-cam
frame exactly like a CCTV frame — no Wine/X, all sources are plain HTTP.

Endpoints:
  GET /health                    -> 200 {"ok": true, "cameras": N}
  GET /channels                  -> 200 {"channels": {name: {...}}}
  GET /search?q=<query>          -> 200 {"matches": [...]} (registry + Longdo)
  GET /snap?ch=<name>[&fresh=1]  -> 200 image/jpeg  (X-Camera* headers say
                                    which camera actually served the frame)

Camera sources (in `ch` resolution order):
  1. registry — frigate/cameras.json (camera SSOT; CAMERAS_JSON env or
     --cameras-json overrides). Every enabled cam with a fetchable URL:
        stream_type hls -> ffmpeg -frames:v 1 on hls_url, alt_urls in order
        stream_type rtsp -> ffmpeg on frigate_overrides.ffmpeg_inputs[0]
        jpeg_url field    -> direct GET (iTIC jpeg2.php stills)
     Cams with source == "local" are skipped (house cams stay on go2rtc).
  2. longdo feed — camera.longdo.com/feed/?command=json (~190 Thai cams,
     cached 5min). Reachable as `longdo:<camid>`, or by title substring
     when the query matches nothing in the registry. Frame = imgurl GET,
     else the mjpeg vdourl's first frame, else its hls_url via ffmpeg —
     same fallback chain as ada-pi backend/traffic_camera.py.

Caching: per-camera CACHE_TTL_S (default 15s) so a burst of polls doesn't
spawn an ffmpeg each; fresh=1 forces a new grab. ffmpeg concurrency is
capped (SEM, default 4) — excess requests queue rather than pile up.

Pure stdlib + the ffmpeg binary. No PIL, no Wine, no display.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logger = logging.getLogger("traffic-snap")

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]  # stacks/services/traffic-cam -> repo root

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
CAMERAS_JSON = os.environ.get("CAMERAS_JSON") or next(
    (p for p in (REPO_ROOT / "frigate" / "cameras.json",
                 REPO_ROOT / "stacks" / "web" / "public" / "cameras.json")
     if p.exists()), None)
LONGDO_FEED = os.environ.get(
    "TRAFFIC_CAM_FEED", "https://camera.longdo.com/feed/?command=json")
FEED_CACHE_S = 300.0
CACHE_TTL_S = float(os.environ.get("TRAFFIC_SNAP_CACHE_S", "15"))
HTTP_TIMEOUT = float(os.environ.get("TRAFFIC_SNAP_HTTP_TIMEOUT", "20"))
FFMPEG_TIMEOUT = float(os.environ.get("TRAFFIC_SNAP_FFMPEG_TIMEOUT", "45"))
# DOH/iTIC playlists stall mid-read — cap socket waits inside ffmpeg too.
FFMPEG_RW_TIMEOUT_US = "15000000"
UA = {"User-Agent": "traffic-snap/1.0"}
# jpeg2.php dead-cam stubs: 43B "not found" or a fixed ~3KB "No sengnal"
# jpeg; real frames are ~20KB+. Same cutoff as cam-wall-pull/traffic_camera.
MIN_JPEG_BYTES = 8000

_ffmpeg_sem = threading.Semaphore(
    int(os.environ.get("TRAFFIC_SNAP_FFMPEG_JOBS", "4")))
_frame_cache: dict[str, tuple[float, bytes]] = {}
_feed_cache: tuple[float, list[dict]] | None = None
_feed_lock = threading.Lock()
_cache_lock = threading.Lock()

# --- registry -------------------------------------------------------------
# frigate/cameras.json is generated from stacks/web/public/cameras.json by
# frigate/generate_config.py; either file works, the fields used here are
# identical.


def load_registry() -> dict[str, dict]:
    """name -> {name,title,group,lat,lon,source,kind,urls,aliases}."""
    if not CAMERAS_JSON:
        return {}
    try:
        reg = json.loads(Path(CAMERAS_JSON).read_text())
    except Exception as exc:
        logger.error("cannot read registry %s: %s", CAMERAS_JSON, exc)
        return {}
    out: dict[str, dict] = {}
    for cam in reg.get("cameras", []):
        if not cam.get("enabled", True):
            continue
        if cam.get("source") == "local":
            continue  # house cams are go2rtc/VMS territory, not traffic
        name = cam.get("name")
        if not name:
            continue
        urls: list[str] = []
        kind = None
        st = cam.get("stream_type")
        if st == "hls" and cam.get("hls_url"):
            kind = "hls"
            urls = [cam["hls_url"], *(cam.get("alt_urls") or [])]
        elif st == "rtsp":
            inputs = (cam.get("frigate_overrides") or {}).get(
                "ffmpeg_inputs") or []
            if inputs and inputs[0].get("path"):
                kind = "rtsp"
                urls = [inputs[0]["path"]]
        elif cam.get("jpeg_url"):
            kind = "jpeg"
            urls = [cam["jpeg_url"]]
        if not urls:
            continue
        aliases = [a for a in (cam.get("camid"),
                               str(cam.get("windy_id") or "")) if a]
        out[name] = {
            "name": name, "title": cam.get("title") or name,
            "group": cam.get("group"), "source": cam.get("source"),
            "lat": cam.get("lat"), "lon": cam.get("lon"),
            "camid": cam.get("camid"), "kind": kind, "urls": urls,
            "aliases": aliases,
        }
    return out


def resolve_registry(query: str, cams: dict[str, dict]) -> dict | None:
    q = query.strip().lower()
    if not q:
        return None
    if q in cams:
        return cams[q]
    for name, meta in cams.items():
        if name.lower() == q or q == str(meta.get("camid") or "").lower():
            return meta
    for name, meta in cams.items():
        if (q in name.lower()
                or q in str(meta.get("title") or "").lower()
                or any(q in str(a).lower() for a in meta.get("aliases", []))):
            return meta
    return None


# --- longdo feed (port of ada-pi backend/traffic_camera.py) ----------------

AREA_ALIASES = {
    "bangna": "บางนา", "bang na": "บางนา", "บางนา": "บางนา",
    "burapha": "บูรพาวิถี", "บูรพา": "บูรพาวิถี",
    "chonburi": "ชลบุรี", "ชลบุรี": "ชลบุรี",
    "chachoengsao": "ฉะเชิงเทรา", "ฉะเชิงเทรา": "ฉะเชิงเทรา",
    "nonthaburi": "นนทบุรี", "นนทบุรี": "นนทบุรี",
    "khonkaen": "ขอนแก่น", "khon kaen": "ขอนแก่น", "ขอนแก่น": "ขอนแก่น",
    "expressway": "ทางพิเศษ", "ทางพิเศษ": "ทางพิเศษ",
    "motorway": "มอเตอร์เวย์", "มอเตอร์เวย์": "มอเตอร์เวย์",
    "rama": "พระราม", "พระราม": "พระราม",
    "sukhumvit": "สุขุมวิท", "สุขุมวิท": "สุขุมวิท",
    "ratchada": "รัชดา", "รัชดา": "รัชดา",
    "sriracha": "ศรีราชา", "ศรีราชา": "ศรีราชา",
    "pattaya": "พัทยา", "พัทยา": "พัทยา",
    "jomtien": "จอมเทียน", "จอมเทียน": "จอมเทียน",
    "na kluea": "นาเกลือ", "naklua": "นาเกลือ", "นาเกลือ": "นาเกลือ",
    "kamphaeng": "กำแพงเพชร", "กำแพงเพชร": "กำแพงเพชร",
    "don muang": "ดอนเมือง", "ดอนเมือง": "ดอนเมือง",
    "bangkok": "กรุงเทพ", "กรุงเทพ": "กรุงเทพ",
}


def _fetch_feed() -> list[dict]:
    global _feed_cache
    with _feed_lock:
        if _feed_cache and time.time() - _feed_cache[0] < FEED_CACHE_S:
            return _feed_cache[1]
        req = urllib.request.Request(LONGDO_FEED, headers=UA)
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            cams = json.loads(r.read())
        for c in cams:
            urls = str(c.get("imgurl")) + str(c.get("hls_url"))
            # suspended cams carry placeholder URLs and can never frame
            c["_live"] = "X.X.X.X" not in urls and "tempsus" not in urls
        _feed_cache = (time.time(), cams)
        return cams


def _score_feed(query: str, limit: int = 5) -> list[dict]:
    q = (query or "").strip().lower()
    tokens = [AREA_ALIASES.get(t, t) for t in q.split() if t.strip()]
    kw = AREA_ALIASES.get(q)
    if kw and kw not in tokens:
        tokens.append(kw)
    ranked = []
    for c in _fetch_feed():
        if not c.get("_live"):
            continue
        title = str(c.get("title") or "")
        camid = str(c.get("camid") or "")
        hits = sum(1 for t in tokens if t and (t in title or t in camid.lower()))
        if tokens and not hits:
            continue
        c["_score"] = 60.0 * hits + (40.0 if hits == len(tokens) else 0.0)
        ranked.append(c)
    ranked.sort(key=lambda c: -c["_score"])
    return ranked[:limit]


def resolve_feed(query: str) -> dict | None:
    q = query.strip()
    if q.lower().startswith("longdo:"):
        camid = q.split(":", 1)[1]
        for c in _fetch_feed():
            if str(c.get("camid")) == camid:
                return c if c.get("_live") else None
        return None
    hits = _score_feed(q, limit=1)
    return hits[0] if hits else None


# --- frame fetch ------------------------------------------------------------


def _http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _ffmpeg_frame(url: str, kind: str) -> bytes:
    cmd = [FFMPEG, "-y", "-loglevel", "error"]
    if kind == "hls":
        cmd += ["-rw_timeout", FFMPEG_RW_TIMEOUT_US,
                "-timeout", FFMPEG_RW_TIMEOUT_US]
    elif kind == "rtsp":
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url, "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-"]
    with _ffmpeg_sem:
        out = subprocess.run(cmd, capture_output=True,
                             timeout=FFMPEG_TIMEOUT)
    if not out.stdout.startswith(b"\xff\xd8"):
        raise ValueError(f"ffmpeg: {out.stderr.decode()[:120] or 'no frame'}")
    return out.stdout


def _jpeg_get(url: str) -> bytes:
    data = _http_get(url, HTTP_TIMEOUT)
    if len(data) < MIN_JPEG_BYTES or not data.startswith(b"\xff\xd8"):
        raise ValueError(f"dead frame ({len(data)}B)")
    return data


def _mjpeg_first_frame(url: str, timeout: float) -> bytes:
    """First complete JPEG out of an MJPEG stream. read1() not read() —
    a dribbling dead-cam stream stalls read() filling its 64KB buffer."""
    req = urllib.request.Request(url, headers=UA)
    buf = b""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        end_at = time.time() + timeout
        while time.time() < end_at and len(buf) < 4 * 1024 * 1024:
            chunk = r.read1(65536)
            if not chunk:
                break
            buf += chunk
            i = buf.find(b"\xff\xd8")
            if i >= 0:
                j = buf.find(b"\xff\xd9", i + 2)
                if j > 0:
                    return buf[i:j + 2]
    raise ValueError("no frame in mjpeg stream")


def snap_registry(meta: dict) -> bytes:
    kind, last = meta["kind"], None
    for url in meta["urls"]:
        try:
            if kind == "jpeg":
                return _jpeg_get(url)
            return _ffmpeg_frame(url, kind)
        except Exception as exc:
            last = exc
    raise ValueError(f"{kind} frame failed ({len(meta['urls'])} urls): {last}")


def snap_feed(cam: dict) -> bytes:
    for url in (cam.get("imgurl"), cam.get("vdourl")):
        if not url:
            continue
        try:
            if "mjpeg" in str(url):
                return _mjpeg_first_frame(str(url), HTTP_TIMEOUT)
            return _jpeg_get(str(url))
        except Exception:
            continue
    hls = cam.get("hls_url")
    if hls and "tempsus" not in str(hls):
        return _ffmpeg_frame(str(hls), "hls")
    raise ValueError("camera returned no usable frame (may be offline)")


# --- HTTP -------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "traffic-snap/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        logger.info("%s %s", self.address_string(), fmt % args)

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _image(self, code: int, data: bytes, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 (stdlib handler name)
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/health":
            return self._json(200, {"ok": True,
                                    "cameras": len(load_registry())})
        if u.path == "/channels":
            cams = load_registry()
            return self._json(200, {"channels": {
                n: {k: m[k] for k in ("title", "group", "source", "camid",
                                      "lat", "lon", "kind")}
                for n, m in cams.items()}})
        if u.path == "/search":
            q = (qs.get("q") or [""])[0]
            reg = load_registry()
            reg_hits = [m for n, m in reg.items()
                        if q.lower() in n.lower()
                        or q.lower() in str(m.get("title") or "").lower()][:5]
            feed_hits = _score_feed(q)
            return self._json(200, {"matches": [
                {"name": m["name"], "title": m["title"], "src": "registry",
                 "camid": m.get("camid")} for m in reg_hits] + [
                {"name": f"longdo:{c.get('camid')}", "title": c.get("title"),
                 "src": "longdo", "camid": c.get("camid")}
                for c in feed_hits]})
        if u.path == "/snap":
            ch = (qs.get("ch") or [""])[0]
            fresh = qs.get("fresh", ["0"])[0] in ("1", "true", "yes")
            return self._snap(ch, fresh)
        self._json(404, {"error": "unknown endpoint",
                         "endpoints": ["/health", "/channels", "/search?q=",
                                       "/snap?ch=<name>"]})

    def _snap(self, ch: str, fresh: bool) -> None:
        if not ch.strip():
            return self._json(400, {"error": "missing ch="})
        reg = load_registry()
        meta = resolve_registry(ch, reg)
        feed_cam = None
        if meta is None:
            try:
                feed_cam = resolve_feed(ch)
            except Exception as exc:
                return self._json(502, {"error": f"longdo feed: {exc}"})
            if feed_cam is None:
                suggestions = [n for n in reg
                               if ch.split(":")[-1].lower()[:4] in n][:5]
                return self._json(404, {"error": f"unknown camera: {ch}",
                                        "did_you_mean": suggestions,
                                        "hint": "longdo:<camid> for feed cams"})
        cam_key = (f"reg:{meta['name']}" if meta is not None
                   else f"longdo:{feed_cam.get('camid')}")
        if not fresh:
            with _cache_lock:
                hit = _frame_cache.get(cam_key)
            if hit and time.time() - hit[0] < CACHE_TTL_S:
                return self._image(200, hit[1], self._hdrs(
                    meta, feed_cam, age=time.time() - hit[0], cached=True))
        try:
            data = (snap_registry(meta) if meta is not None
                    else snap_feed(feed_cam))
        except Exception as exc:
            return self._json(502, {"error": str(exc), "camera": cam_key})
        with _cache_lock:
            _frame_cache[cam_key] = (time.time(), data)
        self._image(200, data, self._hdrs(meta, feed_cam, age=0))

    @staticmethod
    def _hdrs(meta, feed_cam, age: float, cached: bool = False) -> dict:
        # header values must be latin-1 — titles carry Thai, so
        # percent-encode (RFC 5987-style) anything not plain ascii
        def hv(v) -> str:
            s = str(v)
            return s if s.isascii() else urllib.parse.quote(s)
        h = {"X-Frame-Age": f"{age:.0f}", "X-Cache": "hit" if cached else "miss"}
        if meta is not None:
            h.update({"X-Camera": hv(meta["name"]),
                      "X-Camera-Source": "registry",
                      "X-Camera-Title": hv(meta.get("title") or "")})
        elif feed_cam is not None:
            h.update({"X-Camera": hv(f"longdo:{feed_cam.get('camid')}"),
                      "X-Camera-Source": "longdo",
                      "X-Camera-Title": hv(feed_cam.get("title") or "")})
        return h


def main() -> int:
    ap = argparse.ArgumentParser(description="traffic camera snapshot shim")
    ap.add_argument("--bind", default=os.environ.get("TRAFFIC_SNAP_BIND",
                                                   "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("TRAFFIC_SNAP_PORT", "8378")))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cams = load_registry()
    logger.info("registry %s -> %d snappable cameras",
                CAMERAS_JSON or "(none)", len(cams))
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    logger.info("traffic-snap on http://%s:%d", args.bind, args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
