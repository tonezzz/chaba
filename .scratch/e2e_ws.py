#!/usr/bin/env python3
"""ws-sink E2E: real relay.py + fake screen ws client + yolo server."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VENV = "/home/tony/.cache/ultralytics-yolo-venv/bin/python"
SCRATCH = "/home/tony/CascadeProjects/dispatch-wt-20261015-125005-rebuild-gesture-pointer-with-y/.scratch"
ROOT = "/home/tony/CascadeProjects/dispatch-wt-20261015-125005-rebuild-gesture-pointer-with-y"
HAND_IMG = open(f"{SCRATCH}/one.jpg", "rb").read()
got = []
got_lock = threading.Lock()


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(HAND_IMG)))
        self.end_headers()
        self.wfile.write(HAND_IMG)


def screen_client():
    """Connect to the relay as a screen and collect msgs."""
    from websockets.sync.client import connect
    ws = connect("ws://127.0.0.1:18894/ws?role=screen")
    while True:
        try:
            m = json.loads(ws.recv(timeout=60))
        except Exception:
            return
        with got_lock:
            got.append(m)


def main():
    stub = ThreadingHTTPServer(("127.0.0.1", 18098), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    relay = subprocess.Popen(
        [VENV, "relay.py"],
        cwd=f"{ROOT}/stacks/tony-dell/gesture-relay",
        env={**os.environ, "GESTURE_RELAY_HOST": "127.0.0.1",
             "GESTURE_RELAY_PORT": "18894"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)

    # health check over plain HTTP
    h = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:18894/health", timeout=5).read())
    print("relay health:", h)

    t = threading.Thread(target=screen_client, daemon=True)
    t.start()
    time.sleep(0.5)

    svc = subprocess.Popen(
        [VENV, "server.py"],
        cwd=f"{ROOT}/experiments/ultralytics-yolo-ha",
        env={**os.environ,
             "YOLO_FRAME_URL": "http://127.0.0.1:18098/frame",
             "YOLO_MODEL": "hand_yolov8n.pt",
             "POINTER_SINK": "ws://127.0.0.1:18894/ws?role=controller",
             "POINTER_EMIT_MS": "60",
             "POINTER_FLIP": "1",
             "YOLO_HOST": "127.0.0.1", "YOLO_PORT": "18786"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        t0 = time.time()
        while time.time() - t0 < 40:
            gm = [m for m in got if m.get("type") == "gesture" and "x" in m]
            if gm:
                print("screen received:", json.dumps(gm[0]))
                print("RESULT: PASS")
                return 0
            time.sleep(0.3)
        print("RESULT: FAIL — no gesture msgs reached the screen")
        return 1
    finally:
        svc.terminate(); relay.terminate()
        try:
            print("--- svc log tail ---")
            print("\n".join(svc.communicate(timeout=10)[0].splitlines()[-8:]))
            print("--- relay log ---")
            print(relay.communicate(timeout=10)[0])
        except Exception:
            pass
        stub.shutdown()


if __name__ == "__main__":
    sys.exit(main())
