#!/usr/bin/env python3
"""yt-live-api.py — REST shim around yt-live.sh for voice/agent casting.

POST /cast   {"q"|"url"|"query": "...", "lang": "th",
              "voice": "off|th|en"}                   -> start pipeline
POST /stop                                            -> stop cast
GET  /status                                          -> progress + dub phase
GET  /health                                          -> ok
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
RUNLOG = os.path.expanduser("~/.cache/yt-live-api.last.log")
PORT = int(os.environ.get("YT_LIVE_API_PORT", "8791"))
VOICES = ("off", "th", "en")


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
