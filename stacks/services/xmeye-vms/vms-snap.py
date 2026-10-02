#!/usr/bin/env python3
"""vms-snap — HTTP snapshot shim for the XMEye VMS Wine viewer.

Runs on the VMS host (mn01). Selects a channel in the VMS device tree via
xdotool, waits for the cloud-P2P stream to start, captures the :99 X display
with xwd, crops the monitor pane, and returns a PNG.

Endpoints:
  GET /health                      -> 200 {"ok": true}
  GET /channels                    -> 200 {"channels": [...]}
  GET /snap?ch=<name>[&settle=<s>][&zoom=0] -> 200 image/png | 404/503 JSON
  zoom=0 skips the single-pane zoom — grid-res frame, ~15s instead of ~40s+.

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
# Single-pane zoom: double-clicking the active monitor pane toggles a zoomed
# view where the video area is ~4x the pixels of the grid cell — capture that
# for quality. The 4-grid toolbar button restores multi-view afterwards.
SINGLE_PANE_RECT = (5, 120, 1070, 640)  # video area in zoomed single-pane —
                                        # y1 below the pane's own OSD title
                                        # strip (CH label + icons) which
                                        # otherwise tops every frame
GRID4_BTN = (388, 675)                  # bottom-toolbar 2x2 grid icon (2nd;
                                        # 357 = 1-pane — a miss leaves VMS
                                        # zoomed and corrupts the next snap)
# Tree strip scanned for the selected-row blue highlight (verify the click
# landed on the intended channel instead of silently returning another).
TREE_STRIP_X = (1090, 1260)

STATE_DIR = os.environ.get("VMS_SNAP_STATE", "/tmp")
_lock = threading.RLock()

# --- self-heal watchdog -----------------------------------------------------
# The VMS app's cloud-P2P session to the DVR dies every ~day: clicks still
# select channels but no stream attaches (all panes empty, every snap 503s
# "pane shows no video"). A container restart re-logs in and restores it —
# verified 2026-09-30. Track consecutive no-video failures; >=3 trips a
# systemctl restart, max once per cooldown so a genuinely-down DVR doesn't
# restart-loop.
NOVIDEO_RESTART_AFTER = int(os.environ.get("VMS_NOVIDEO_RESTART_AFTER", "3"))
NOVIDEO_COOLDOWN_S = float(os.environ.get("VMS_NOVIDEO_COOLDOWN_S", "900"))
_novideo_streak = 0
_novideo_next_restart = 0.0


def _watchdog_novideo() -> None:
    global _novideo_streak, _novideo_next_restart
    _novideo_streak += 1
    if (_novideo_streak < NOVIDEO_RESTART_AFTER
            or time.time() < _novideo_next_restart):
        return
    _novideo_next_restart = time.time() + NOVIDEO_COOLDOWN_S
    _novideo_streak = 0
    def _restart():
        logger.warning(
            "watchdog: %d consecutive no-video snaps — restarting %s",
            NOVIDEO_RESTART_AFTER, CONTAINER)
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "xmeye-vms.service"],
                timeout=90, capture_output=True)
        except Exception:
            logger.exception("watchdog: restart failed")
    threading.Thread(target=_restart, daemon=True).start()


def _watchdog_ok() -> None:
    global _novideo_streak
    _novideo_streak = 0


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
    # No --sync anywhere: a synced mousemove blocks >30s whenever the Wine
    # app's event loop is busy (stream switch / reconnect) — fire-and-forget
    # plus our own sleeps is strictly more robust.
    _podman("xdotool", "mousemove", str(PANE_CLICK[0]),
            str(PANE_CLICK[1]), "click", "1", timeout=10)
    time.sleep(0.4)
    # Scroll the device tree fully to the top so channel-row coordinates
    # stay true — a scrolled tree shifts every row and picks a wrong camera.
    _podman("xdotool", "mousemove", str(TREE_ANCHOR[0]),
            str(TREE_ANCHOR[1]), timeout=10)
    _podman("xdotool", "click", "--repeat", "20", "--delay", "40", "4",
            timeout=15)
    time.sleep(0.3)
    _podman("xdotool", "mousemove", str(x), str(y), timeout=10)
    _podman("xdotool", "click", "--repeat", "2", "--delay", "150", "1",
            timeout=10)


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


def selected_row_y(width: int, height: int, rgb: bytes) -> int | None:
    """Y-center of the highlighted (blue) row in the device tree — verifies
    the clicked channel is the one that got selected."""
    x1, x2 = TREE_STRIP_X
    rows: list[int] = []
    run: list[int] = []
    for y in range(120, height, 2):
        blue = 0
        for x in range(x1, min(x2, width), 4):
            o = (y * width + x) * 3
            r, g, b = rgb[o], rgb[o + 1], rgb[o + 2]
            if b > 130 and b > r + 40 and b > g + 20:
                blue += 1
        if blue > 20:
            run.append(y)
        elif run:
            rows.append(sum(run) // len(run))
            run = []
    if run:
        rows.append(sum(run) // len(run))
    return rows[0] if rows else None


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


def snap(query: str, settle: float, zoom: bool = True,
         _retry: int = 1) -> tuple[bytes, str]:
    channels = load_channels()
    hit = resolve_channel(query, channels)
    if hit is None:
        raise LookupError(query)
    name, meta = hit
    with _lock:
        # Pin a known layout: selecting the 4-grid is idempotent, so a
        # later double-click unambiguously means "zoomed".
        _podman("xdotool", "mousemove", str(GRID4_BTN[0]),
                str(GRID4_BTN[1]), "click", "1", timeout=10)
        raw = None
        for _seltry in range(2):
            select_channel(meta["x"], meta["y"])
            time.sleep(settle)
            raw = capture_xwd()
            # The double-clicked row can drift off-target (tree scroll, dead
            # rows shifting positions) — verify the highlighted row is the
            # requested one before trusting the pane content. A busy Wine UI
            # can eat the click; retry once before failing.
            w, h, rgb = xwd_to_rgb(raw)
            sel_y = selected_row_y(w, h, rgb)
            # sel_y=None means NO highlighted row — the click missed and
            # pane 1 still shows whatever stream was attached before (a
            # DIFFERENT device entirely: 2026-10-02 wall showed noble-a
            # CH05 in every noble-club tile because _has_video passed on
            # the stale frame). Absence of highlight is a failure, not a
            # pass — retry once, then fail loudly.
            if sel_y is not None and abs(sel_y - meta["y"]) <= 14:
                break
            if _seltry == 0:
                continue
            raise RuntimeError(
                f"selected row {'not highlighted' if sel_y is None else f'y={sel_y}'} "
                f"does not match '{name}' (y={meta['y']}) — device tree "
                "layout drifted; recalibrate channels.json")

        # zoom=0 (wall thumbs) skips the zoom dance entirely — the zoom
        # re-opens the P2P stream and costs 12-36s per cam, which is why
        # 8-cam zones starve under VMS_BUDGET.
        raw2 = None
        if zoom:
            # Zoom pane 1 for a ~4x-resolution capture. We pinned the grid
            # above, so this double-click deterministically toggles to
            # single-pane; never click again (it would toggle back).
            # NOTE: no --sync — a synced mousemove blocks >30s while the
            # Wine app re-renders after the channel switch.
            _podman("xdotool", "mousemove", str(PANE_CLICK[0]),
                    str(PANE_CLICK[1]), timeout=10)
            _podman("xdotool", "click", "--repeat", "2", "--delay", "150",
                    "1", timeout=10)
            # The stream re-opens on zoom and needs a few seconds to
            # draw — poll until real video appears (bounded).
            for _round in range(3):
                for _poll in range(8):
                    time.sleep(1.5)
                    cand = capture_xwd()
                    w2, h2, rgb2 = xwd_to_rgb(cand)
                    cw, ch, crgb = crop_rgb(w2, h2, rgb2, SINGLE_PANE_RECT)
                    if _has_video(cw, ch, crgb):
                        raw2 = cand
                        break
                if raw2 is not None:
                    break
                # P2P stream open is a coin flip — when it fails the pane
                # stays dead forever no matter how long we wait; re-select
                # the channel to force a fresh stream attach (2026-09-30:
                # ~half the noble-club channels flapped dead per sweep; a
                # single retry still dropped first-attempt snaps in Ada
                # turns).
                select_channel(meta["x"], meta["y"])
                time.sleep(settle / 2)
            if raw2 is None:
                raw2 = cand  # zoomed pane never drew — grid may still show video
            _podman("xdotool", "mousemove", str(GRID4_BTN[0]),
                    str(GRID4_BTN[1]), "click", "1", timeout=10)
    # Zoomed frame first. A dead pane (stream not drawn yet, offline cam)
    # collapses content_bbox to a sliver — reject degenerate crops rather
    # than returning a 5px "frame" that downstream treats as an image.
    if raw2 is not None:
        w, h, rgb = xwd_to_rgb(raw2)
        w, h, rgb = crop_rgb(w, h, rgb, SINGLE_PANE_RECT)
        box = content_bbox(w, h, rgb)
        if box and (box[2] - box[0]) * (box[3] - box[1]) < w * h // 4:
            box = None
        if box:
            w, h, rgb = crop_rgb(w, h, rgb, box)
    if raw2 is None or w * h < 50_000 or min(w, h) < 100:
        # Fall back to the pre-zoom grid capture at pane resolution.
        w, h, rgb = xwd_to_rgb(raw)
        w, h, rgb = crop_rgb(w, h, rgb, PANE_RECT)
        box = content_bbox(w, h, rgb)
        if box:
            w, h, rgb = crop_rgb(w, h, rgb, box)
    if (w * h < 50_000 or min(w, h) < 100
            or not _has_video(w, h, rgb)):
        raise RuntimeError(
            f"'{name}' pane shows no video — camera offline or stream stalled")
    try:
        _check_frame_identity(name, w, h, rgb)
    except RuntimeError:
        # Pane kept the previous channel's stream — the attach failed.
        # One more select is a fresh attach attempt and often lands it
        # (P2P is a coin flip); only then fail.
        if _retry:
            logger.warning("'%s' stale-pane frame; forcing re-select", name)
            return snap(query, settle, zoom, _retry=0)
        raise
    return png_encode(w, h, rgb), name


# channel -> luma fingerprint of its last accepted frame. The
# selected-row check proves the right TREE ROW lit up; it cannot prove
# the PANE switched — when the new stream attach fails the pane keeps
# the previously attached channel's video (2026-10-02: every noble-club
# snap returned the same noble-a_CH05/CH06 frame). A frame identical to
# another channel's recent frame means the pane never switched.
_last_frames: dict[str, bytes] = {}


def _frame_sig(w: int, h: int, rgb: bytes) -> bytes:
    """Coarse 32x18 luma fingerprint — ignores OSD text/noise."""
    out = bytearray()
    for gy in range(18):
        y = gy * h // 18
        for gx in range(32):
            x = gx * w // 32
            o = (y * w + x) * 3
            out.append((rgb[o] + rgb[o + 1] + rgb[o + 2]) // 3)
    return bytes(out)


def _check_frame_identity(name: str, w: int, h: int, rgb: bytes) -> None:
    sig = _frame_sig(w, h, rgb)
    for other, prev in _last_frames.items():
        if other == name:
            continue
        diff = sum(1 for a, b in zip(sig, prev) if abs(a - b) > 40)
        if diff < len(sig) * 0.15:
            raise RuntimeError(
                f"'{name}' frame identical to '{other}' — pane kept the "
                "previous channel's stream (attach failed)")
    _last_frames[name] = sig


def _has_video(width: int, height: int, rgb: bytes) -> bool:
    """A live pane has texture everywhere — high mean neighbor luma delta.
    A dead/offline pane is flat gray with at most an OSD strip — its
    deltas sit near zero (measured ~5 vs ~126 on real video). Threshold
    45 still rejects a 4-pane grid crop where only pane 1 has video
    (diluted to ~31) — a mosaic is not an acceptable frame. Was 60, but
    real night footage measured 58.1 (dark scenes compress neighbor
    deltas) and was wrongly rejected — noble-a Road In, 2026-10-01."""
    tot = n = 0
    for y in range(0, height, 4):
        base = y * width * 3
        for x in range(0, width - 8, 8):
            o = base + x * 3
            if o + 26 < len(rgb):
                lum = rgb[o] + rgb[o + 1] + rgb[o + 2]
                tot += abs(lum - rgb[o + 24] - rgb[o + 25] - rgb[o + 26])
                n += 1
    if n < 100:
        return False
    return tot / n > 45


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
            zoom = (q.get("zoom") or ["1"])[0] != "0"
            try:
                png, resolved = snap(ch, settle, zoom)
            except LookupError:
                self._json(404, {"error": f"unknown channel {ch!r}",
                                 "channels": sorted(load_channels())})
                return
            except Exception as exc:
                logger.exception("snap failed")
                # both are attach-failure signatures — the pane either has
                # no video or still plays the previous channel's stream
                if ("pane shows no video" in str(exc)
                        or "frame identical" in str(exc)):
                    _watchdog_novideo()
                self._json(503, {"error": str(exc)})
                return
            _watchdog_ok()
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
