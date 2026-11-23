#!/usr/bin/env python3
"""yt-live-api.py — REST shim around yt-live.sh for voice/agent casting.

POST /cast   {"q"|"url"|"query": "...", "lang": "th",
              "voice": "off|th|en"}                   -> start pipeline
POST /stop                                            -> stop cast
GET  /status                                          -> progress + dub phase
GET  /list                                            -> cast-ready media files
GET  /health                                          -> ok

Env: YT_LIVE_APP (media dir, shared with yt-live.sh), YT_LIVE_MCACHE,
YT_LIVE_BASE (public media URL base for /list links), YT_LIVE_API_PORT,
HA_BASE (fast_cast target, default http://127.0.0.1:8123).
"""
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Repo home: chaba scripts/ops/. Resolve the sibling yt-live.sh from this
# script's own dir first (repo checkout or installed ~/.local/bin), then
# fall back to the pre-repo-home install path.
_HERE = os.path.dirname(os.path.realpath(__file__))
SH = (os.path.join(_HERE, "yt-live.sh")
      if os.path.exists(os.path.join(_HERE, "yt-live.sh"))
      else os.path.expanduser("~/.local/bin/yt-live.sh"))
APP = os.environ.get(
    "YT_LIVE_APP",
    "/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public"
    "/apps/yt-live")
MCACHE = os.environ.get("YT_LIVE_MCACHE",
                        os.path.expanduser("~/.cache/yt-live-media"))
MEDIA_BASE = os.environ.get(
    "YT_LIVE_BASE", "http://192.168.2.67/apps/yt-live")
RUNLOG = os.path.expanduser("~/.cache/yt-live-api.last.log")
PORT = int(os.environ.get("YT_LIVE_API_PORT", "8791"))
VOICES = ("off", "th", "en")

PLAYER = "media_player.tony_tv_cast"
HA = os.environ.get("HA_BASE", "http://127.0.0.1:8123")


def _ha_token():
    try:
        for line in open(
                os.path.expanduser("~/.config/secrets/nodered-ha.env")):
            if line.startswith("HASS_TOKEN="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def fast_cast(url):
    """Direct media file (mp4 etc.) -> play_media on the TV.

    Skips the yt-dlp + HLS transcode pipeline entirely — a Chromecast
    plays a plain mp4 natively, so this starts in ~2s. Wakes the TV
    first: play_media on an 'off' entity returns 200 but no-ops
    (2026-10-05 incident)."""
    import time
    import urllib.request
    tok = _ha_token()
    def call(svc, payload):
        req = urllib.request.Request(
            f"{HA}/api/services/{svc}",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=10).status
    def state():
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                f"{HA}/api/states/{PLAYER}",
                headers={"Authorization": f"Bearer {tok}"}), timeout=5)
            return json.load(r)["state"]
        except Exception:
            return "?"
    def box_state():
        # media_player.tony_tv is the TrueID box via Android TV — the
        # Samsung panel itself has no sensor (IR toggle only).
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                f"{HA}/api/states/media_player.tony_tv",
                headers={"Authorization": f"Bearer {tok}"}), timeout=5)
            return json.load(r)["state"]
        except Exception:
            return "?"
    if state() == "off":
        call("media_player/turn_on", {"entity_id": PLAYER})
        time.sleep(5)
    code = call("media_player/play_media",
                {"entity_id": PLAYER, "media_content_id": url,
                 "media_content_type": "video/mp4"})
    return {"http": code, "player": state(), "box": box_state(),
            "panel": "unsensed (IR toggle only)"}


def spawn(args):
    os.makedirs(os.path.dirname(RUNLOG), exist_ok=True)
    with open(RUNLOG, "ab") as f:
        subprocess.Popen([SH] + args, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)


def status():
    segs = len([f for f in os.listdir(APP)
                if re.fullmatch(r"seg_\d+\.ts", f)]) if os.path.isdir(APP) else 0
    m3u8 = os.path.join(APP, "media.m3u8")
    done = os.path.exists(m3u8) and "#EXT-X-ENDLIST" in open(m3u8).read()
    running = subprocess.run(
        ["pgrep", "-f", "ffmpeg.*yt-live"], capture_output=True).returncode == 0
    tail = ""
    phase = "idle"
    title = None
    if os.path.exists(RUNLOG):
        lines = open(RUNLOG, errors="replace").readlines()
        tail = "".join(lines[-6:])
        # Only lines after the last "== resolving" belong to the current run.
        start = max((i for i, ln in enumerate(lines)
                     if ln.strip().startswith("== resolving")), default=0)
        for ln in lines[start:]:
            ln = ln.strip()
            if ln.startswith("title:"):
                title = ln[6:].strip()
            elif ln.startswith("== "):
                phase = ln[3:].split(" -> ")[0].strip()
    dub = None
    try:
        raw = open(os.path.join(APP, "dub.state")).read().strip()
        if raw:                      # "<voice>:<phase>" written by yt-live.sh
            v, _, s = raw.partition(":")
            dub = {"voice": v or None, "phase": s or None}
    except OSError:
        pass
    if done and not running:
        phase = "complete"
    elif running and phase not in ("transcoding + burning subs", "casting"):
        phase = "transcoding"
    mc_bytes = mc_entries = 0
    try:
        for e in os.scandir(MCACHE):
            if not e.is_dir():
                continue
            if os.path.exists(os.path.join(e, "complete")):
                mc_entries += 1
            for f in os.scandir(e):
                if f.is_file():
                    mc_bytes += f.stat().st_size
    except OSError:
        pass
    return {"transcoding": running, "segments": segs, "vod_complete": done,
            "subtitles": os.path.exists(os.path.join(APP, "subs.vtt")),
            "phase": phase, "title": title, "dub": dub,
            "media_cache_bytes": mc_bytes,
            "media_cache_entries": mc_entries,
            "log_tail": tail.strip()}


class H(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        if self.path.startswith("/health"):
            self._json(200, {"ok": True})
        elif self.path.startswith("/list"):
            try:
                files = sorted(
                    f for f in os.listdir(APP)
                    if f.lower().endswith((".mp4", ".m4v", ".webm", ".mkv",
                                           ".mp3", ".m4a")))
            except OSError:
                files = []
            self._json(200, {"ok": True, "files": [
                {"name": f, "url": f"{MEDIA_BASE}/{f}"} for f in files]})
            return
        elif self.path.startswith("/status"):
            self._json(200, status())
        else:
            self._json(404, {"error": "unknown path"})

    def do_POST(self):
        if self.path.startswith("/stop"):
            spawn(["stop"])
            self._json(200, {"ok": True, "action": "stop"})
            return
        if self.path.startswith("/cast"):
            b = self._body()
            q = b.get("q") or b.get("url") or b.get("query")
            if not q:
                self._json(400, {"error": "need q/url/query"})
                return
            # direct media files play natively on Chromecast — skip the
            # yt-dlp + transcode pipeline (2026-10-05: mp4 demo casts)
            if re.search(r"\.(mp4|m4v|webm|mkv|mp3|m4a|m3u8)(\?|#|$)",
                         str(q), re.I):
                try:
                    res = fast_cast(str(q))
                    self._json(200, {"ok": True, "action": "cast",
                                     "mode": "direct", "query": q,
                                     **res})
                except Exception as e:
                    self._json(502, {"ok": False, "error": str(e)[:200]})
                return
            lang = str(b.get("lang") or "th")
            voice = str(b.get("voice") or "off").lower()
            if voice not in VOICES:
                self._json(400, {"error": "voice must be off|th|en"})
                return
            spawn([str(q), lang, voice])
            self._json(200, {"ok": True, "action": "cast",
                             "query": q, "lang": lang, "voice": voice})
            return
        self._json(404, {"error": "unknown path"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"yt-live-api on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
