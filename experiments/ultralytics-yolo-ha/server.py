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
MODEL_NAME = os.environ.get("YOLO_MODEL", "yolov8n.pt")
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
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"{name} {conf:.2f}"
                cv2.putText(
                    annotated,
                    label,
                    (x1, max(y1 - 5, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )

        _, buf = cv2.imencode(".jpg", annotated)

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

    def _send(self, code, data, ctype, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, indent=2).encode(), "application/json")

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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
            url = f"http://192.168.2.67:8780/image?v={int(time.time())}"
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
    def worker():
        while True:
            detect()
            time.sleep(0)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving YOLO {GO2RTC_SOURCE} results on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
