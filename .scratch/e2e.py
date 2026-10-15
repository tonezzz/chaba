#!/usr/bin/env python3
"""E2E for the yolo gesture-pointer: stub /frame server + sink capture +
server.py in pointer mode. Asserts cursor msgs, grab edge, gone edge."""
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRATCH = "/home/tony/CascadeProjects/dispatch-wt-20261015-125005-rebuild-gesture-pointer-with-y/.scratch"
HAND_IMG = open(f"{SCRATCH}/hand1.jpg", "rb").read()      # 4 hands
ONE_IMG = open(f"{SCRATCH}/one.jpg", "rb").read()         # exactly 1 hand
# 1x1 black jpeg — no hand
BLANK = open(f"{SCRATCH}/blank.jpg", "rb").read()

frame = {"buf": HAND_IMG}
got = []          # captured sink POSTs
got_lock = threading.Lock()


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/frame"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame["buf"])))
            self.end_headers()
            self.wfile.write(frame["buf"])
            return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        if self.path == "/pub":
            with got_lock:
                got.append(json.loads(body or b"{}"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        self.send_response(404); self.end_headers()


def wait_for(pred, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.2)
    print(f"TIMEOUT waiting for: {what}")
    return False


def msgs():
    with got_lock:
        return list(got)


def main():
    stub = ThreadingHTTPServer(("127.0.0.1", 18099), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    env = {
        "YOLO_FRAME_URL": "http://127.0.0.1:18099/frame",
        "YOLO_MODEL": "hand_yolov8n.pt",
        "POINTER_SINK": "vcast:1",
        "INPUT_BRIDGE": "http://127.0.0.1:18099",
        "POINTER_EMIT_MS": "60",
        "POINTER_GONE_MS": "600",
        "POINTER_FLIP": "0",
        "YOLO_HOST": "127.0.0.1",
        "YOLO_PORT": "18785",
        "PATH": "/usr/bin:/bin",
    }
    import os
    env = {**os.environ, **env}
    proc = subprocess.Popen(
        ["/home/tony/.cache/ultralytics-yolo-venv/bin/python", "server.py"],
        cwd="/home/tony/CascadeProjects/dispatch-wt-20261015-125005-rebuild-gesture-pointer-with-y/experiments/ultralytics-yolo-ha",
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        ok = True
        # 1) cursor msgs flowing (hand1 has 4 hands -> should also grab)
        ok &= wait_for(lambda: len(msgs()) >= 3, 30, "first pointer msgs")
        m = [x for x in msgs() if x.get("type") == "gesture" and "x" in x]
        assert m, "no gesture msgs"
        assert m[0]["src"] == "yolo" and m[0]["screen"] == 1
        assert 0 <= m[0]["x"] <= 1 and 0 <= m[0]["y"] <= 1
        print("cursor msg:", json.dumps(m[0]))

        # 2) two-hand sustained -> fist_start (hand1 has >=2 hands)
        ok &= wait_for(
            lambda: any(x.get("action") == "fist_start" for x in msgs()),
            30, "fist_start on multi-hand frame")
        assert any(x.get("hands", 0) >= 2 for x in m)

        # 3) drop to single-hand frame -> fist_end
        frame["buf"] = BLANK if False else ONE_IMG
        ok &= wait_for(
            lambda: any(x.get("action") == "fist_end" for x in msgs()),
            30, "fist_end when hands drop below 2")

        # 4) blank frame -> gone edge
        frame["buf"] = BLANK
        ok &= wait_for(
            lambda: any(x.get("gone") for x in msgs()), 30, "gone edge")

        # 5) HTTP api
        pj = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:18785/pointer", timeout=5).read())
        assert pj["enabled"] and pj["sinks"] == ["vcast:1"], pj
        dj = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:18785/detect", timeout=5).read())
        assert "detections" in dj
        print("/pointer:", json.dumps(pj)[:200])
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0]
            if out:
                print("--- server log tail ---")
                print("\n".join(out.splitlines()[-15:]))
        except Exception:
            proc.kill()
        stub.shutdown()


if __name__ == "__main__":
    sys.exit(main())
