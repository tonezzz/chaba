#!/usr/bin/env python3
"""Unit check for the gesture-pointer state machine in server.py.

No model inference — fabricates detections and captures ptr_emit. Run:
    python3 pointer-check.py          (uses whatever python has ultralytics)
"""
import os
import sys
import time

# fast config for the check — must precede server import (env is read at
# module load)
os.environ.setdefault("YOLO_MODEL", "hand_yolov8n.pt")
os.environ["POINTER_SINK"] = "mock"
os.environ["POINTER_EMIT_MS"] = "50"
os.environ["POINTER_GONE_MS"] = "200"
os.environ["POINTER_MIN_CONF"] = "0.35"
os.environ["POINTER_FLIP"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402  (loads the model — a few seconds on CPU)

sent = []
server.ptr["sinks"] = ["mock"]
server.ptr_emit = sent.append          # capture instead of network

W, H = 1000, 500


def det(cls="hand", conf=0.8, box=(100, 100, 200, 200)):
    return {"class": cls, "conf": conf, "xyxy": list(box)}


def reset():
    sent.clear()
    server.ptr.update(grabbing=False, grab_streak=0, open_streak=0,
                      present=False, gone_sent=True, last_seen=0.0,
                      last_emit=0.0)


def expect(cond, what):
    if not cond:
        print(f"FAIL: {what}")
        return False
    print(f"  ok: {what}")
    return True


ok = True

# 1) single hand -> cursor msg, box centre normalized + X flipped
reset()
server.pointer_update([det(box=(800, 200, 900, 300))], W, H)
m = sent[-1]
ok &= expect(m["type"] == "gesture" and m["src"] == "yolo",
             "gesture msg emitted")
ok &= expect(abs(m["x"] - (1 - 0.85)) < 0.01 and abs(m["y"] - 0.5) < 0.01,
             f"centre normalized + flipped ({m['x']},{m['y']})")
ok &= expect(m["hands"] == 1 and m["wx"] == m["x"], "hands/wx carried")

# 2) below min conf -> nothing
reset()
server.pointer_update([det(conf=0.1)], W, H)
ok &= expect(not sent, "low-conf detection ignored")

# 3) wrong class -> nothing
reset()
server.pointer_update([det(cls="person")], W, H)
ok &= expect(not sent, "non-pointer class ignored")

# 4) two hands sustained 3 frames -> fist_start
reset()
two = [det(box=(800, 200, 900, 300)), det(box=(50, 200, 150, 300), conf=0.9)]
for _ in range(2):
    server.pointer_update(two, W, H)
ok &= expect(not any(m.get("action") == "fist_start" for m in sent),
             "2-frame blip does NOT grab (debounce)")
server.pointer_update(two, W, H)
ok &= expect(any(m.get("action") == "fist_start" for m in sent),
             "3 frames of 2 hands -> fist_start")
ok &= expect(server.ptr["grabbing"], "grabbing state set")

# 5) primary box = largest area (hands sorted)
reset()
server.pointer_update(
    [det(box=(0, 0, 40, 40), conf=0.99),      # small but high-conf
     det(box=(400, 200, 700, 400), conf=0.5)],  # big -> wins
    W, H)
ok &= expect(abs(sent[-1]["x"] - (1 - 0.55)) < 0.01,
             f"largest box drives the pointer (x={sent[-1]['x']})")

# 6) drop below 2 hands -> fist_end after debounce
reset()
server.pointer_update(two, W, H)
server.pointer_update(two, W, H)
server.pointer_update(two, W, H)      # grabbing now
sent.clear()
server.pointer_update([det()], W, H)
server.pointer_update([det()], W, H)
ok &= expect(any(m.get("action") == "fist_end" for m in sent),
             "hands<2 sustained -> fist_end")

# 7) hand leaves frame -> fist_end then gone edge (after GONE_MS)
reset()
server.pointer_update(two, W, H)      # make sure 'present' is set
sent.clear()
for _ in range(3):                     # empty frames before GONE_MS elapses
    server.pointer_update([], W, H)
time.sleep(0.25)
server.pointer_update([], W, H)
ok &= expect(any(m.get("gone") for m in sent), "gone edge after GONE_MS")
ok &= expect(len([m for m in sent if m.get("gone")]) == 1, "gone deduped")

# 8) emit throttle — second immediate update doesn't re-send
reset()
server.pointer_update([det()], W, H)
server.pointer_update([det()], W, H)
ok &= expect(len(sent) == 1, f"EMIT_MS throttle ({len(sent)} msg)")

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
