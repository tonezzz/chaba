#!/usr/bin/env python3
"""Ultralytics YOLOv8 detector for a go2rtc stream."""
import json
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from ultralytics import YOLO

GO2RTC_BASE = os.environ.get("GO2RTC_BASE", "http://127.0.0.1:1984")
GO2RTC_SOURCE = os.environ.get("GO2RTC_SOURCE", "xiaomi_c201")
# Generic frame source — when set, {src} expands to the source name and
# any URL works (e.g. the input-bridge last-frames endpoint):
#   YOLO_FRAME_URL=http://100.102.134.91:3010/frame?screen={src}&token=cam
FRAME_URL_TEMPLATE = os.environ.get("YOLO_FRAME_URL", "")
MODEL_NAME = os.environ.get("YOLO_MODEL", "yolov8n.pt")

# --- gesture pointer (YOLO hand boxes -> pointer msgs) -------------------
# POINTER_SINK: comma-separated sinks, each one of:
#   vcast:<N>            -> POST <INPUT_BRIDGE>/pub {screen:N, ...msg}
#                           (display's own camera uplink drives its cursor)
#   http(s)://<url>      -> POST msg JSON to that URL
#   ws(s)://<url>        -> send msg over a ws client conn (e.g. the
#                           gesture-relay ?role=controller endpoint — the
#                           YOLO service IS just another controller)
# Emits the same contract the gesture screens already consume:
#   {type:"gesture", src:"yolo", x,y, wx,wy, hands, conf, action?}
# Bounding-box model has no landmarks: box centre is the pointer, TWO hands
# sustained = fist_start/fist_end (grab), gone = hand lost > POINTER_GONE_MS.
POINTER_SINK = os.environ.get("POINTER_SINK", "")
POINTER_CLASSES = {
    c.strip() for c in os.environ.get("POINTER_CLASSES", "hand").split(",")
    if c.strip()
}
POINTER_MIN_CONF = float(os.environ.get("POINTER_MIN_CONF", "0.35"))
POINTER_EMIT_MS = int(os.environ.get("POINTER_EMIT_MS", "100"))
POINTER_GONE_MS = int(os.environ.get("POINTER_GONE_MS", "800"))
# front-facing display cameras mirror the scene: user-right hand shows on
# frame-left, so flip X by default (set 0 for a rear/room camera)
POINTER_FLIP = os.environ.get("POINTER_FLIP", "1") not in ("0", "false", "no")
INPUT_BRIDGE = os.environ.get("INPUT_BRIDGE", "http://127.0.0.1:3010")
HA_BASE = os.environ.get("HA_BASE", "http://192.168.2.67:8123")
HA_TOKEN_FILE = os.environ.get("HA_TOKEN_FILE", "/home/tony/.config/secrets/home-assistant-token.env")
HA_TOKEN = os.environ.get("HA_TOKEN")
HOST = os.environ.get("YOLO_HOST", "0.0.0.0")
PORT = int(os.environ.get("YOLO_PORT", "8780"))

model = YOLO(MODEL_NAME)

state = {
    "ts": None,
    "detections": [],
    "counts": {},
    "person_count": 0,
    "annotated": None,
    "error": None,
    "source": GO2RTC_SOURCE,
}
state_lock = threading.Lock()

# --- pointer emitter state -------------------------------------------------
ptr = {
    "sinks": [s.strip() for s in POINTER_SINK.split(",") if s.strip()],
    "ws": {},            # url -> connected ws client
    "grabbing": False,
    "grab_streak": 0,    # consecutive frames with >=2 hands
    "open_streak": 0,    # consecutive frames with <2 hands
    "present": False,    # a hand was seen recently
    "gone_sent": True,   # dedupe the gone edge
    "last_seen": 0.0,    # last time a hand box qualified
    "last_emit": 0.0,
    "last_msg": None,
}


def _ptr_ws(url):
    """Lazy ws client per sink (websockets.sync — optional dep)."""
    ws = ptr["ws"].get(url)
    if ws is not None:
        try:
            ws.ping()
            return ws
        except Exception:
            try:
                ws.close()
            except Exception:
                pass
            ptr["ws"].pop(url, None)
    try:
        from websockets.sync.client import connect
        ws = connect(url, open_timeout=5, ping_interval=None)
        ptr["ws"][url] = ws
        return ws
    except Exception as e:
        ptr["ws"].pop(url, None)
        with state_lock:
            ptr["last_error"] = f"ws {url}: {e}"
        return None


def ptr_emit(msg):
    """Deliver one pointer message to every configured sink."""
    if not ptr["sinks"]:
        return
    ptr["last_msg"] = {**msg, "ts": time.time()}
    for sink in ptr["sinks"]:
        try:
            if sink.startswith("vcast:"):
                screen = int(sink.split(":", 1)[1])
                body = json.dumps({"screen": screen, **msg}).encode()
                req = urllib.request.Request(
                    f"{INPUT_BRIDGE}/pub", data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                urllib.request.urlopen(req, timeout=5).read()
            elif sink.startswith("ws://") or sink.startswith("wss://"):
                ws = _ptr_ws(sink)
                if ws is not None:
                    ws.send(json.dumps(msg))
            else:
                body = json.dumps(msg).encode()
                req = urllib.request.Request(
                    sink, data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            with state_lock:
                ptr["last_error"] = f"{sink}: {e}"


def pointer_update(detections, frame_w, frame_h):
    """Turn hand detections into gesture msgs. Boxes only — no landmarks:
    box centre is the pointer; >=2 hands sustained = grab (fist_start/end)."""
    if not ptr["sinks"]:
        return
    now = time.time() * 1000
    hands = [d for d in detections
             if d["class"] in POINTER_CLASSES and d["conf"] >= POINTER_MIN_CONF]
    hands.sort(key=lambda d: (d["xyxy"][2] - d["xyxy"][0])
               * (d["xyxy"][3] - d["xyxy"][1]), reverse=True)

    if not hands:
        ptr["grab_streak"] = 0
        ptr["open_streak"] += 1
        if ptr["grabbing"] and ptr["open_streak"] >= 2:
            ptr["grabbing"] = False
            ptr_emit({"type": "gesture", "src": "yolo", "action": "fist_end",
                      "x": 0.5, "y": 0.5, "wx": 0.5, "wy": 0.5, "hands": 0})
        if ptr["present"] and now - ptr["last_seen"] > POINTER_GONE_MS \
                and not ptr["gone_sent"]:
            ptr["gone_sent"] = True
            ptr["present"] = False
            ptr_emit({"type": "gesture", "src": "yolo", "gone": 1, "hands": 0})
        return

    ptr["last_seen"] = now
    ptr["present"] = True
    ptr["gone_sent"] = False
    x1, y1, x2, y2 = hands[0]["xyxy"]
    nx = (x1 + x2) / 2 / max(1, frame_w)
    ny = (y1 + y2) / 2 / max(1, frame_h)
    if POINTER_FLIP:
        nx = 1.0 - nx
    nx = min(1.0, max(0.0, nx))
    ny = min(1.0, max(0.0, ny))
    base = {"type": "gesture", "src": "yolo", "x": round(nx, 4),
            "y": round(ny, 4), "wx": round(nx, 4), "wy": round(ny, 4),
            "hands": len(hands), "conf": hands[0]["conf"]}

    # two-hands-sustained = grab; drop below = release (dwell debounce so a
    # single flicker frame can't forge a grab/release)
    if len(hands) >= 2:
        ptr["grab_streak"] += 1
        ptr["open_streak"] = 0
    else:
        ptr["open_streak"] += 1
        ptr["grab_streak"] = 0
    if not ptr["grabbing"] and ptr["grab_streak"] >= 3:
        ptr["grabbing"] = True
        ptr_emit({**base, "action": "fist_start"})
        return
    if ptr["grabbing"] and ptr["open_streak"] >= 2:
        ptr["grabbing"] = False
        ptr_emit({**base, "action": "fist_end"})
        return

    if now - ptr["last_emit"] >= POINTER_EMIT_MS:
        ptr["last_emit"] = now
        ptr_emit(base)


def _ha_token():
    try:
        with open(HA_TOKEN_FILE) as f:
            m = re.search(r"HA_LONG_LIVED_TOKEN=(.+)", f.read())
            return m.group(1).strip() if m else None
    except Exception:
        return None


HA_TOKEN = HA_TOKEN or _ha_token()


def fetch_frame():
    with state_lock:
        src = state["source"]
    if FRAME_URL_TEMPLATE:
        url = FRAME_URL_TEMPLATE.format(src=src)
    else:
        url = f"{GO2RTC_BASE}/api/frame.jpeg?src={src}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = resp.read()
    img = np.frombuffer(data, np.uint8)
    return cv2.imdecode(img, cv2.IMREAD_COLOR)


def detect():
    try:
        frame = fetch_frame()
        results = model(frame, verbose=False)
        r = results[0]
        counts = {}
        person_count = 0
        detections = []
        annotated = frame.copy()
        if r.boxes is not None and r.boxes.shape[0] > 0:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                name = r.names.get(cls_id, "unknown")
                conf = float(box.conf[0])
                x1, y1, x2, y2 = (int(x) for x in box.xyxy[0].tolist())
                detections.append(
                    {
                        "class": name,
                        "conf": round(conf, 3),
                        "xyxy": [x1, y1, x2, y2],
                    }
                )
                counts[name] = counts.get(name, 0) + 1
                if name == "person":
                    person_count += 1
                # pointer classes draw cyan so /image shows what drives it
                color = (255, 200, 0) if name in POINTER_CLASSES else (0, 255, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                label = f"{name} {conf:.2f}"
                cv2.putText(
                    annotated,
                    label,
                    (x1, max(y1 - 5, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                )

        _, buf = cv2.imencode(".jpg", annotated)

        pointer_update(detections, frame.shape[1], frame.shape[0])

        with state_lock:
            state["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["detections"] = detections
            state["counts"] = counts
            state["person_count"] = person_count
            state["annotated"] = buf.tobytes()
            state["error"] = None
    except Exception as e:
        with state_lock:
            state["error"] = str(e)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, data, ctype, extra_headers=None, method="GET"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, indent=2).encode(), "application/json")

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/image":
            with state_lock:
                img = state["annotated"]
            if img is None:
                self._send(404, b"no image yet", "text/plain", method="HEAD")
            else:
                self._send(200, img, "image/jpeg", method="HEAD")
            return
        self._send(200, b"", "text/plain", method="HEAD")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            with state_lock:
                body = {
                    "ok": state["error"] is None,
                    "ts": state["ts"],
                    "error": state["error"],
                    "source": state["source"],
                    "person_count": state["person_count"],
                    "counts": state["counts"],
                    "detections_count": len(state["detections"]),
                }
            self._json(200, body)
            return

        if path == "/detect":
            with state_lock:
                body = {
                    "person_count": state["person_count"],
                    "counts": state["counts"],
                    "detections": state["detections"],
                    "ts": state["ts"],
                    "error": state["error"],
                    "source": state["source"],
                }
            self._json(200, body)
            return

        if path == "/image":
            with state_lock:
                img = state["annotated"]
            if img is None:
                self._send(404, b"no image yet", "text/plain")
            else:
                self._send(200, img, "image/jpeg")
            return

        if path == "/pointer":
            with state_lock:
                body = {
                    "enabled": bool(ptr["sinks"]),
                    "sinks": ptr["sinks"],
                    "present": ptr["present"],
                    "grabbing": ptr["grabbing"],
                    "classes": sorted(POINTER_CLASSES),
                    "min_conf": POINTER_MIN_CONF,
                    "flip": POINTER_FLIP,
                    "last_msg": ptr["last_msg"],
                    "last_error": ptr.get("last_error"),
                }
            self._json(200, body)
            return

        if path == "/set-source":
            q = self._query()
            src = (q.get("src") or ["xiaomi_c201"])[0]
            with state_lock:
                state["source"] = src
            self._json(200, {"ok": True, "source": src})
            return

        if path == "/tvs":
            if not HA_TOKEN:
                self._json(503, {"ok": False, "error": "HA token not available"})
                return
            req = urllib.request.Request(
                f"{HA_BASE}/api/states",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    states = json.loads(resp.read())
                tvs = [
                    s["entity_id"]
                    for s in states
                    if s.get("entity_id", "").startswith("media_player.")
                ]
                self._json(200, {"ok": True, "tvs": tvs})
            except Exception as e:
                self._json(502, {"ok": False, "error": str(e)})
            return

        if path == "/cast":
            q = self._query()
            target = (q.get("target") or ["media_player.tony_tv_cast"])[0]
            if not HA_TOKEN:
                self._json(503, {"ok": False, "error": "HA token not available"})
                return
            host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
            url = f"http://{host}/image?v={int(time.time())}"
            payload = json.dumps({
                "entity_id": target,
                "media_content_type": "image/jpeg",
                "media_content_id": url,
            }).encode()
            req = urllib.request.Request(
                f"{HA_BASE}/api/services/media_player/play_media",
                data=payload,
                headers={
                    "Authorization": f"Bearer {HA_TOKEN}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp.read()
                self._json(200, {"ok": True, "target": target, "url": url})
            except Exception as e:
                self._json(502, {"ok": False, "error": str(e), "target": target})
            return

        self._send(404, b"not found", "text/plain")


def main():
    loop_s = float(os.environ.get("YOLO_LOOP_MS", "0")) / 1000

    def worker():
        while True:
            t0 = time.monotonic()
            detect()
            if loop_s:
                time.sleep(max(0.0, loop_s - (time.monotonic() - t0)))
            else:
                time.sleep(0)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving YOLO {GO2RTC_SOURCE} results on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
