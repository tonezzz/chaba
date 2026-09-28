#!/usr/bin/env python3
"""vms-snap — HTTP snapshot shim for the XMEye VMS Wine viewer.

Runs on the VMS host (mn01). Selects a channel in the VMS device tree via
xdotool, waits for the cloud-P2P stream to start, captures the :99 X display
with xwd, crops the monitor pane, and returns a PNG.

Endpoints:
  GET /health                      -> 200 {"ok": true}
  GET /channels                    -> 200 {"channels": [...]}
  GET /snap?ch=<name>[&settle=<s>] -> 200 image/png | 404/503 JSON

Channel name matching is case-insensitive substring against channels.json.
Coordinates live in channels.json (device tree rows — recalibrate if the tree
layout changes; row height is ~20px).

Pure stdlib: no PIL/ffmpeg on the host — XWD is parsed and PNG encoded inline.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import subprocess
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("vms-snap")

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.environ.get("VMS_SNAP_CHANNELS",
                               os.path.join(HERE, "channels.json"))
CONTAINER = os.environ.get("VMS_CONTAINER", "xmeye-vms-vnc")
DISPLAY = os.environ.get("VMS_DISPLAY", ":99")
DEFAULT_SETTLE = float(os.environ.get("VMS_SNAP_SETTLE", "9"))
MAX_SETTLE = 30.0

# Monitor pane 1 (top-left) inside the 1280x720 VMS desktop — includes the
# pane title bar so the channel label is visible in the frame.
PANE_RECT = (7, 84, 536, 357)   # x1, y1, x2, y2
# Click target to make pane 1 the active pane before selecting a channel.
PANE_CLICK = (270, 218)
# Point inside the device tree used to reset its scroll — row coordinates in
# channels.json assume the tree is scrolled fully up; a drifted scroll shifts
# every row and silently selects the wrong camera.
TREE_ANCHOR = (1150, 205)
# Rows at the top of PANE_RECT carrying the pane title/OSD header — stripped
# before autocrop so it doesn't count as "content".
PANE_TITLE_H = 30

STATE_DIR = os.environ.get("VMS_SNAP_STATE", "/tmp")
_lock = threading.Lock()


def _podman(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["podman", "exec", "-e", f"DISPLAY={DISPLAY}", CONTAINER, *args],
        capture_output=True, timeout=timeout)


def load_channels() -> dict:
    with open(CHANNELS_FILE) as f:
        return json.load(f)


def resolve_channel(query: str, channels: dict) -> tuple[str, dict] | None:
    q = query.strip().lower()
    if not q:
        return None
    for name, meta in channels.items():
        if name.lower() == q:
            return name, meta
    for name, meta in channels.items():
        if q in name.lower() or any(q in a.lower() for a in meta.get("aliases", [])):
            return name, meta
    return None


def select_channel(x: int, y: int) -> None:
    # Activate pane 1, then double-click the channel's tree row.
    _podman("xdotool", "mousemove", "--sync", str(PANE_CLICK[0]),
            str(PANE_CLICK[1]), "click", "1")
    time.sleep(0.4)
    # Scroll the device tree fully to the top so channel-row coordinates
    # stay true — a scrolled tree shifts every row and picks a wrong camera.
    _podman("xdotool", "mousemove", "--sync", str(TREE_ANCHOR[0]),
            str(TREE_ANCHOR[1]))
    _podman("xdotool", "click", "--repeat", "20", "--delay", "40", "4")
    time.sleep(0.3)
    _podman("xdotool", "mousemove", "--sync", str(x), str(y))
    _podman("xdotool", "click", "--repeat", "2", "--delay", "150", "1")


def capture_xwd() -> bytes:
    out = os.path.join(STATE_DIR, "vms-snap.xwd")
    _podman("xwd", "-root", "-out", out, timeout=20)
    cp = subprocess.run(["podman", "cp", f"{CONTAINER}:{out}", out],
                        capture_output=True, timeout=20)
    if cp.returncode != 0:
        raise RuntimeError(f"podman cp failed: {cp.stderr.decode()[:200]}")
    with open(out, "rb") as f:
        return f.read()


# --- XWD -> PNG (pure stdlib) ------------------------------------------------

def _mask_parts(mask: int) -> tuple[int, int]:
    shift = (mask & -mask).bit_length() - 1
    return shift, mask.bit_count()


def xwd_to_rgb(data: bytes) -> tuple[int, int, bytes]:
    """Decode a ZPixmap XWD dump to (width, height, RGB888 bytes)."""
    if len(data) < 100:
        raise ValueError("truncated XWD header")
    h = struct.unpack(">25I", data[:100])
    (header_size, _ver, _fmt, _depth, width, height, _xoff, byte_order,
     bitmap_unit, _bit_order, _bitmap_pad, bits_pp, bytes_per_line,
     _visual, rmask, gmask, bmask, _bprgb, _ce, ncolors,
     *_rest) = h

    colors_off = header_size
    pixels_off = colors_off + ncolors * 12
    pixels = data[pixels_off:]
    need = bytes_per_line * height
    if len(pixels) < need:
        raise ValueError("truncated XWD pixel data")

    unit_bytes = max(1, bitmap_unit // 8)
    rs, rb = _mask_parts(rmask)
    gs, gb = _mask_parts(gmask)
    bs, bb = _mask_parts(bmask)
    rmax, gmax, bmax = (1 << rb) - 1, (1 << gb) - 1, (1 << bb) - 1
    bo = "little" if byte_order == 0 else "big"

    rgb = bytearray(width * height * 3)
    di = 0
    for row in range(height):
        base = row * bytes_per_line
        for col in range(width):
            o = base + col * unit_bytes
            px = int.from_bytes(pixels[o:o + unit_bytes], bo)
            rgb[di] = ((px & rmask) >> rs) * 255 // rmax
            rgb[di + 1] = ((px & gmask) >> gs) * 255 // gmax
            rgb[di + 2] = ((px & bmask) >> bs) * 255 // bmax
            di += 3
    return width, height, bytes(rgb)


def crop_rgb(width: int, height: int, rgb: bytes,
             rect: tuple[int, int, int, int]) -> tuple[int, int, bytes]:
    x1, y1, x2, y2 = rect
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    w, h = x2 - x1, y2 - y1
    out = bytearray(w * h * 3)
    for row in range(h):
        src = ((y1 + row) * width + x1) * 3
        out[row * w * 3:(row + 1) * w * 3] = rgb[src:src + w * 3]
    return w, h, bytes(out)


def content_bbox(width: int, height: int, rgb: bytes) -> tuple[int, int, int, int] | None:
    """Find the bounding box of non-uniform content by luma variance —
    trims dead pane space (gray bars) and pillarboxing around 4:3 streams."""
    if width < 16 or height < 16:
        return None
    step_y = max(1, height // 90)
    step_x = max(1, width // 120)
    thresh2 = 40 * 40  # luma variance threshold (~6.3 stddev of luma*3)

    def colvar(c: int) -> float:
        s = s2 = n = 0
        for r in range(0, height, step_y):
            o = (r * width + c) * 3
            lum = rgb[o] + rgb[o + 1] + rgb[o + 2]
            s += lum; s2 += lum * lum; n += 1
        m = s / n
        return s2 / n - m * m

    def rowvar(r: int) -> float:
        s = s2 = n = 0
        for c in range(0, width, step_x):
            o = (r * width + c) * 3
            lum = rgb[o] + rgb[o + 1] + rgb[o + 2]
            s += lum; s2 += lum * lum; n += 1
        m = s / n
        return s2 / n - m * m

    cols = [c for c in range(0, width, step_x) if colvar(c) > thresh2]
    rows = [r for r in range(0, height, step_y) if rowvar(r) > thresh2]
    if not cols or not rows:
        return None
    pad = 4
    return (max(0, cols[0] - pad), max(0, rows[0] - pad),
            min(width, cols[-1] + pad), min(height, rows[-1] + pad))


def png_encode(width: int, height: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload)))

    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)
        raw += rgb[row * stride:(row + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def snap(query: str, settle: float) -> tuple[bytes, str]:
    channels = load_channels()
    hit = resolve_channel(query, channels)
    if hit is None:
        raise LookupError(query)
    name, meta = hit
    with _lock:
        select_channel(meta["x"], meta["y"])
        time.sleep(settle)
        raw = capture_xwd()
    w, h, rgb = xwd_to_rgb(raw)
    w, h, rgb = crop_rgb(w, h, rgb, PANE_RECT)
    # strip the pane title/OSD header, then autocrop to the real video so
    # dead pane space and 4:3 pillarboxing don't stretch on the display
    rgb = rgb[PANE_TITLE_H * w * 3:]
    h -= PANE_TITLE_H
    box = content_bbox(w, h, rgb)
    if box:
        w, h, rgb = crop_rgb(w, h, rgb, box)
    return png_encode(w, h, rgb), name


class Handler(BaseHTTPRequestHandler):
    server_version = "vms-snap/0.1"

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.info(fmt, *args)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/health":
            self._json(200, {"ok": True})
            return
        if url.path == "/channels":
            try:
                self._json(200, {"channels": sorted(load_channels())})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if url.path == "/snap":
            q = parse_qs(url.query)
            ch = (q.get("ch") or [""])[0]
            try:
                settle = min(float((q.get("settle") or [DEFAULT_SETTLE])[0]),
                             MAX_SETTLE)
            except ValueError:
                settle = DEFAULT_SETTLE
            try:
                png, resolved = snap(ch, settle)
            except LookupError:
                self._json(404, {"error": f"unknown channel {ch!r}",
                                 "channels": sorted(load_channels())})
                return
            except Exception as exc:
                logger.exception("snap failed")
                self._json(503, {"error": str(exc)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("X-Channel", resolved)
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)
            return
        self._json(404, {"error": "not found"})


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="100.106.196.22")
    ap.add_argument("--port", type=int, default=8377)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    logger.info("vms-snap listening on %s:%d (channels: %s)",
                args.bind, args.port, CHANNELS_FILE)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
