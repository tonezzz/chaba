#!/usr/bin/env python3
"""vms-snap — HTTP snapshot shim for the XMEye VMS Wine viewer.

Runs on the VMS host (mn01). Selects a channel in the VMS device tree via
xdotool, waits for the cloud-P2P stream to start, captures the :99 X display
with xwd, crops the monitor pane, and returns a PNG.

Endpoints:
  GET /health                      -> 200 {"ok": true}
  GET /channels                    -> 200 {"channels": [...]}
  GET /snap?ch=<name>[&settle=<s>][&zoom=0][&native=1] -> 200 image/png
  zoom=0 skips the single-pane zoom — grid-res frame, ~15s instead of ~40s+.
  native=1 uses the VMS's own OSD snapshot: the ACTIVE PANE's channel lands
  in pictures/*.bmp at native decode res (2560x1440), saved via the preview
  dialog's Save. Zoomed single-pane gives one channel at full res; the
  grid composite carries every attached pane at once.
  GET /composite?chs=a,b,c[&settle=<s>][&native=1][&layout=4|9]
      -> 200 application/zip of "<i>.png" members + _manifest.json
      (manifest entries carry request index, resolved name, ok/err, w/h).
  One capture cycle for several channels: binds each channel to a monitor
  pane (bindings persist per pane index — already-bound panes are not
  re-attached), verifies video per pane, then snapshots every pane in the
  same cycle. native=1 (default) runs each pane's context-menu Snapshot ->
  BMP at native decode res (~3s/pane once bound); native=0 splits a single
  :99 xwd into per-pane tiles (~1s total, grid resolution).

Channel name matching is case-insensitive substring against channels.json.
Coordinates live in channels.json (device tree rows — recalibrate if the tree
layout changes; row height is ~20px).

Pure stdlib: no PIL/ffmpeg on the host — XWD is parsed and PNG encoded inline.
"""

from __future__ import annotations

import io
import json
import logging
import os
import struct
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("vms-snap")

HERE = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.environ.get("VMS_SNAP_CHANNELS",
                               os.path.join(HERE, "channels.json"))
CONTAINER = os.environ.get("VMS_CONTAINER", "xmeye-vms-vnc")
DISPLAY = os.environ.get("VMS_DISPLAY", ":99")
DEFAULT_SETTLE = float(os.environ.get("VMS_SNAP_SETTLE", "9"))
MAX_SETTLE = 30.0

# Monitor pane 1 (top-left) inside the maximized 1920x1080 VMS desktop —
# includes the pane title bar so the channel label is visible in the frame.
PANE_RECT = (8, 85, 855, 537)   # x1, y1, x2, y2
# Click target to make pane 1 the active pane before selecting a channel.
PANE_CLICK = (430, 310)
# Point inside the device tree used to reset its scroll — row coordinates in
# channels.json assume the tree is scrolled fully up; a drifted scroll shifts
# every row and silently selects the wrong camera.
TREE_ANCHOR = (1780, 300)
# Rows at the top of PANE_RECT carrying the pane title/OSD header — stripped
# before autocrop so it doesn't count as "content".
PANE_TITLE_H = 30
# Single-pane zoom: double-clicking the active monitor pane toggles a zoomed
# view where the video area is ~4x the pixels of the grid cell — capture that
# for quality. The 4-grid toolbar button restores multi-view afterwards.
SINGLE_PANE_RECT = (8, 113, 1706, 1000)  # zoomed pane video area; y1 below
                                        # the pane's own OSD title strip (CH
                                        # label + icons) — a bar otherwise
                                        # tops every frame
GRID1_BTN = (530, 1030)                 # bottom-toolbar single-pane icon —
                                        # the deterministic "zoom" (a pane
                                        # double-click toggles nothing in
                                        # this build; the layout buttons do)
GRID4_BTN = (620, 1030)                 # bottom-toolbar multi-pane icon —
                                        # re-measured 2026-10-06: the pill is
                                        # 1p=526, 2x2=566, focus6=606,
                                        # focus7=642, 3x3=686, 4x4=715.
                                        # 620 lands on focus6 (1 big + 5
                                        # small); pane 1 stays the big pane,
                                        # which is what this shim captures.
                                        # (the old "4-grid" label was wrong —
                                        # even 2x2 lives at 566)
# Native snapshot path (?native=1): the pane OSD photo-cam (or the pane
# context-menu "Snapshot") writes the ACTIVE PANE's channel to
# <user>/pictures/*.bmp at native decode res (2560x1440 — ~2.9x the 1698px
# screen crop). There is NO monitor-composite BMP — verified 2026-10-06 via
# the Capture Information dialog's Device/Channel field (per-channel).
# The preview is a modal dialog: SAVE keeps the file and closes it; CANCEL
# DELETES the just-written file (learned 2026-10-03 — stray clicks while it
# is open are swallowed and corrupt the next step).
SNAP_ICON = (1599, 100)                 # pane OSD photo-camera (right side,
                                        # single-pane/2-pane strip)
SNAP_ICON_GRID = (1042, 97)             # same icon when the 4-pane grid is
                                        # up — each pane's strip ends at its
                                        # own right edge, not the monitor's
CAP_SAVE = (1198, 743)                  # Capture Information -> Save
CAP_CANCEL = (1287, 743)                # Capture Information -> Cancel
PIC_DIR = Path(os.environ.get(
    "VMS_PIC_DIR",
    str(Path.home()
        / ".local/share/xmeye-vms/vms-runtime/data/users/admin/pictures")))
# Tree strip scanned for the selected-row blue highlight (verify the click
# landed on the intended channel instead of silently returning another).
TREE_STRIP_X = (1710, 1910)

# --- multi-pane composite capture --------------------------------------------
# Channel->pane bindings persist per pane INDEX across layout switches and
# captures (verified 2026-10-06: streams re-seat onto the same indices).
# A composite cycle therefore costs one layout click + binds only for panes
# whose channel changed + ~3s per pane for context-menu Snapshot -> BMP ->
# Save; warm refreshes skip attach entirely.
MONITOR_RECT = (8, 68, 1704, 998)   # monitor area, maximized 1920x1080
# even-grid layouts only — focus layouts produce unequal tiles. Buttons are
# the bottom-pill icon centers measured 2026-10-06.
COMPOSITE_LAYOUTS = {
    "4": {"btn": (566, 1030), "cols": 2, "rows": 2},
    "9": {"btn": (686, 1030), "cols": 3, "rows": 3},
}
MAX_COMPOSITE_PANES = max(v["cols"] * v["rows"]
                          for v in COMPOSITE_LAYOUTS.values())
# Context menu opens with its top-left at the right-click point; "Snapshot"
# is item 5, centred ~(+65,+95) — measured on panes in both grid columns.
CTX_SNAP_OFFSET = (65, 95)
# Verify deadline. Cold multi-attach on one DVR serializes at the DVR —
# panes land over ~90-120s (2026-10-06: a 4-pane noble-club bind drew its
# first stream ~100s in; 40s lost every pane). Warm runs exit early, so
# the cost is only paid when panes genuinely need it.
COMPOSITE_SETTLE = float(os.environ.get("VMS_COMPOSITE_SETTLE", "90"))
# pane index -> channel name currently bound (row-major pane order)
_pane_map: dict[int, str] = {}

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


def _tree_scroll_reset() -> None:
    # Scroll the device tree fully to the top so channel-row coordinates
    # stay true — a scrolled tree shifts every row and picks a wrong camera.
    _podman("xdotool", "mousemove", str(TREE_ANCHOR[0]),
            str(TREE_ANCHOR[1]), timeout=10)
    _podman("xdotool", "click", "--repeat", "20", "--delay", "40", "4",
            timeout=15)
    time.sleep(0.3)


def _dblclick_row(x: int, y: int) -> None:
    _podman("xdotool", "mousemove", str(x), str(y), timeout=10)
    _podman("xdotool", "click", "--repeat", "2", "--delay", "150", "1",
            timeout=10)


def select_channel(x: int, y: int,
                   pane: tuple[int, int] = PANE_CLICK) -> None:
    # Activate the target pane, then double-click the channel's tree row.
    # No --sync anywhere: a synced mousemove blocks >30s whenever the Wine
    # app's event loop is busy (stream switch / reconnect) — fire-and-forget
    # plus our own sleeps is strictly more robust.
    _podman("xdotool", "mousemove", str(pane[0]), str(pane[1]),
            "click", "1", timeout=10)
    time.sleep(0.4)
    _tree_scroll_reset()
    _dblclick_row(x, y)


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


def bmp_to_rgb(data: bytes) -> tuple[int, int, bytes]:
    """Uncompressed 24/32bpp BMP -> (w, h, RGB bytes). Rows are bottom-up
    BGR(A); slice-assignment does the channel swap at C speed."""
    if data[:2] != b"BM":
        raise ValueError("not a BMP")
    off = int.from_bytes(data[10:14], "little")
    w = int.from_bytes(data[18:22], "little", signed=True)
    h = int.from_bytes(data[22:26], "little", signed=True)
    bpp = int.from_bytes(data[28:30], "little")
    if int.from_bytes(data[30:34], "little") != 0:
        raise ValueError("compressed BMP")
    topdown = h < 0
    h = abs(h)
    bypp = bpp // 8
    stride = (w * bypp + 3) & ~3
    if bpp not in (24, 32):
        raise ValueError(f"unsupported bpp {bpp}")
    px = bytearray(w * h * 3)
    for y in range(h):
        sy = y if topdown else h - 1 - y
        row = bytearray(data[off + sy * stride: off + sy * stride + w * bypp])
        if bpp == 24:
            row[0::3], row[2::3] = row[2::3], row[0::3]  # BGR -> RGB
            px[y * w * 3:(y + 1) * w * 3] = row
        else:  # BGRA -> RGB
            row[0::4], row[2::4] = row[2::4], row[0::4]
            del row[3::4]
            px[y * w * 3:(y + 1) * w * 3] = row
    return w, h, bytes(px)


def _wait_bmp(t0: float, timeout: float = 15) -> Path | None:
    """Poll the pictures dir for a BMP written at/after t0."""
    deadline = t0 + timeout
    while time.time() < deadline:
        time.sleep(0.6)
        try:
            for p in sorted(PIC_DIR.glob("*.bmp"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
                st = p.stat()
                if st.st_mtime >= t0 - 1 and st.st_size > 100_000:
                    return p
        except OSError:
            pass
    return None


def _keep_bmp(found: Path) -> tuple[int, int, bytes]:
    data = found.read_bytes()
    # The bmp lands ~0.5s BEFORE the preview dialog finishes painting —
    # click Save too early and the hit falls into the still-empty button
    # row, leaving the dialog up to cover the next frame (2026-10-03).
    time.sleep(1.2)
    # Save = keep + close the modal (Cancel would DELETE the file). Verify
    # it actually closed — an orphaned modal swallows every later click
    # (2026-10-06: one orphan cascaded into a whole run of dead panes).
    for _ in range(3):
        _podman("xdotool", "mousemove", str(CAP_SAVE[0]), str(CAP_SAVE[1]),
                "click", "1", timeout=10)
        time.sleep(0.9)
        if not _cap_dialog_open():
            break
    else:
        # refuses to close — the bytes are already in memory, so Cancel
        # (which deletes the FILE) is safe and prevents the orphan
        _podman("xdotool", "mousemove", str(CAP_CANCEL[0]),
                str(CAP_CANCEL[1]), "click", "1", timeout=10)
        time.sleep(0.8)
    try:
        found.unlink()
    except OSError:
        pass
    return bmp_to_rgb(data)


def _native_capture(grid: bool = False) -> tuple[int, int, bytes]:
    """Click the pane OSD snapshot icon, keep the capture via the preview
    dialog's Save, and return the BMP it wrote as (w, h, rgb). The file is
    written AT icon-click — the dialog only gates keep/delete/close.
    grid=True clicks pane 1's strip (the OSD icons sit at each pane's own
    right edge; the monitor-width coordinate only exists when zoomed)."""
    icon = SNAP_ICON_GRID if grid else SNAP_ICON
    t0 = time.time()
    _podman("xdotool", "mousemove", str(icon[0]), str(icon[1]),
            "click", "1", timeout=10)
    found = _wait_bmp(t0)
    if found is None:
        # nothing landed — the modal may still be up or still painting;
        # dismiss until verifiably closed so the next snap's clicks are
        # not silently swallowed.
        _dismiss_modal()
        raise RuntimeError("native snapshot: no bmp written")
    return _keep_bmp(found)


def _pane_rects(cols: int, rows: int) -> list[tuple[int, int, int, int]]:
    """Row-major pane rects for an even grid over MONITOR_RECT."""
    x1, y1, x2, y2 = MONITOR_RECT
    cw, ch = (x2 - x1) / cols, (y2 - y1) / rows
    return [(round(x1 + c * cw), round(y1 + r * ch),
             round(x1 + (c + 1) * cw), round(y1 + (r + 1) * ch))
            for r in range(rows) for c in range(cols)]


def _inset(rect: tuple[int, int, int, int], n: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = rect
    return x1 + n, y1 + n, x2 - n, y2 - n


def _pane_point(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """A click-safe spot inside a pane: clear of the OSD strip (top ~30px)
    and of the pane borders, so a right-click opens the video context menu
    and a left-click just activates the pane."""
    x1, y1, x2, y2 = rect
    return (int(x1 + (x2 - x1) * 0.4), int(y1 + (y2 - y1) * 0.45))


def _ctx_menu_open(cx: int, cy: int) -> bool:
    """Did the pane context menu open? It is a warm light-gray box
    (bg ~212,208,200) anchored at the right-click point — sample a small
    grid below-right of the cursor instead of trusting blind timing: a
    right-click swallowed by a still-closing modal opens no menu at all
    (2026-10-06: one pane per composite run lost its bmp to that race)."""
    try:
        w, h, rgb = _grab_xwd(1)
    except RuntimeError:
        return False

    def _warm(x: int, y: int) -> bool:
        if x >= w or y >= h:
            return False
        o = (y * w + x) * 3
        return (195 <= rgb[o] <= 228 and 190 <= rgb[o + 1] <= 222
                and 182 <= rgb[o + 2] <= 216)

    # a real menu is a SOLID warm-gray rectangle — a bright video pane can
    # hold scattered warm pixels (sunlit concrete) but not a ~180px
    # unbroken vertical stripe of them (2026-10-06: loose color matching
    # alone false-positived on live video, clicking "Snapshot" into thin
    # air). The menu anchors its left edge at the cursor and is ~132px
    # wide; both interior margins (x+8 left, x+122 right, clear of item
    # text) are uniform bg. Either stripe + a few grid hits is enough.
    stripe = max(
        sum(1 for y in range(cy + 10, cy + 190, 8) if _warm(cx + 8, y)),
        sum(1 for y in range(cy + 10, cy + 190, 8) if _warm(cx + 122, y)))
    grid = sum(1 for dy in (25, 65, 105, 145, 170)
               for dx in (15, 45, 75, 105) if _warm(cx + dx, cy + dy))
    return stripe >= 16 and grid >= 4


def _grab_xwd(retries: int = 3) -> tuple[int, int, bytes]:
    """capture_xwd + decode with retries — a truncated podman-exec stream
    is a flake, not a failure worth aborting a whole composite over."""
    last: Exception | None = None
    for _ in range(retries):
        try:
            return xwd_to_rgb(capture_xwd())
        except Exception as exc:
            last = exc
            time.sleep(0.8)
    raise RuntimeError(f"xwd capture failed: {last}")


def _cap_dialog_open() -> bool:
    """Is the Capture Information modal up? Its title bar is a ~700px
    stripe of near-uniform light gray (227/215/204 gradient) at y~330 —
    video content never produces that. An orphaned modal swallows EVERY
    later click — tree dblclicks, pane right-clicks, everything — and
    2026-10-06 showed one early orphan cascading into a whole run of
    'context menu did not open' + dead rebinds."""
    try:
        w, h, rgb = _grab_xwd(1)
    except RuntimeError:
        return False
    hits = tot = 0
    for x in range(660, 1330, 15):
        o = (330 * w + x) * 3
        r, g, b = rgb[o], rgb[o + 1], rgb[o + 2]
        lo, hi = min(r, g, b), max(r, g, b)
        tot += 1
        if hi - lo < 12 and 190 <= hi <= 245:
            hits += 1
    return tot > 10 and hits / tot > 0.8


def _dismiss_modal() -> None:
    """Clear whatever transient UI is up: Escape closes an open context
    menu; the Cancel coordinate clears a Capture Information dialog (or
    harmlessly clicks a pane when neither is open). The dialog can still
    be PAINTING when we get here — the bmp lands up to a few seconds
    before the modal finishes opening, so a single early Cancel falls
    into the not-yet-open window and orphans it. Click once, then poll
    until it is verifiably gone."""
    _podman("xdotool", "key", "Escape", timeout=10)
    time.sleep(0.4)
    _podman("xdotool", "mousemove", str(CAP_CANCEL[0]),
            str(CAP_CANCEL[1]), "click", "1", timeout=10)
    for _ in range(6):
        time.sleep(1.0)
        if not _cap_dialog_open():
            return
        _podman("xdotool", "mousemove", str(CAP_CANCEL[0]),
                str(CAP_CANCEL[1]), "click", "1", timeout=10)


def _native_capture_pane(rect: tuple[int, int, int, int]) -> tuple[int, int, bytes]:
    """Context-menu Snapshot for one pane: right-click inside the pane
    (which also makes it the active pane) opens the context menu anchored
    at the cursor; "Snapshot" is item 5 at a fixed offset. Same BMP+modal
    contract as the OSD icon — the dialog's Device/Channel proves it is
    the pane's own channel at native decode res."""
    cx, cy = _pane_point(rect)
    # bounded worst case per pane. Menu-never-opens = the UI thread was
    # busy (attach churn on other panes eats right-clicks) — worth four
    # spaced tries. Menu opened but no bmp = the stream is dead — one try
    # is enough.
    saw_menu = False
    for _attempt in range(4):
        t0 = time.time()
        _podman("xdotool", "mousemove", str(cx), str(cy), "click", "3",
                timeout=10)
        opened = False
        for _poll in range(4):
            time.sleep(0.5)
            if _ctx_menu_open(cx, cy):
                opened = True
                break
        if not opened:
            _dismiss_modal()
            time.sleep(1.0)
            continue
        saw_menu = True
        # the bmp clock starts at the SNAPSHOT click, not the right-click —
        # menu-open polling can eat most of an 8s window under attach
        # churn and the file then lands just after the deadline (which
        # also orphans its preview dialog: 2026-10-06).
        t0 = time.time()
        _podman("xdotool", "mousemove", str(cx + CTX_SNAP_OFFSET[0]),
                str(cy + CTX_SNAP_OFFSET[1]), "click", "1", timeout=10)
        found = _wait_bmp(t0, timeout=12)
        if found is not None:
            return _keep_bmp(found)
        _dismiss_modal()
        break
    if saw_menu:
        raise RuntimeError("native snapshot: no bmp written "
                           "(stream died between verify and capture)")
    # Last resort: a blind right-click + Snapshot-offset click. Covers a
    # menu that opened but evaded detection; if none opened, the second
    # click just lands on live video — harmless.
    _podman("xdotool", "mousemove", str(cx), str(cy), "click", "3",
            timeout=10)
    time.sleep(1.2)
    t0 = time.time()
    _podman("xdotool", "mousemove", str(cx + CTX_SNAP_OFFSET[0]),
            str(cy + CTX_SNAP_OFFSET[1]), "click", "1", timeout=10)
    found = _wait_bmp(t0, timeout=12)
    if found is not None:
        return _keep_bmp(found)
    _dismiss_modal()
    raise RuntimeError("native snapshot: context menu did not open")


def composite(queries: list[str], settle: float, native: bool = True,
              layout: str | None = None) -> tuple[list[dict], dict[int, bytes]]:
    """One capture cycle for several channels.

    Binds each channel to a monitor pane (panes already bound to the
    requested channel are skipped — pane bindings persist across calls and
    layout switches), waits for every bound pane to show video, then takes
    each pane's snapshot: context-menu Snapshot -> native BMP (native=1),
    or a single xwd composite split into per-pane tiles (native=0).

    Returns (manifest, {request_index: png_bytes}); per-cam failures land
    in the manifest entries, not as exceptions.
    """
    channels = load_channels()
    manifest: dict[int, dict] = {}
    order: list[tuple[int, str, dict]] = []
    seen: set[str] = set()
    for i, q in enumerate(queries):
        manifest[i] = {"i": i, "q": q, "ok": False}
        hit = resolve_channel(q, channels)
        if hit is None:
            manifest[i]["err"] = f"unknown channel {q!r}"
            continue
        name, meta = hit
        manifest[i]["name"] = name
        if name in seen:
            manifest[i]["err"] = f"duplicate channel {name!r}"
            continue
        seen.add(name)
        order.append((i, name, meta))
    if len(order) > MAX_COMPOSITE_PANES:
        raise ValueError(
            f"composite supports at most {MAX_COMPOSITE_PANES} channels")
    results: dict[int, bytes] = {}
    if not order:
        return list(manifest.values()), results
    lay = COMPOSITE_LAYOUTS[
        layout if layout in COMPOSITE_LAYOUTS
        else ("4" if len(order) <= 4 else "9")]
    rects = _pane_rects(lay["cols"], lay["rows"])
    with _lock:
        # clear a stray modal (leftover Capture dialog would swallow every
        # click this cycle) — no-ops when nothing is open.
        _dismiss_modal()
        btn = lay["btn"]
        _podman("xdotool", "mousemove", str(btn[0]), str(btn[1]),
                "click", "1", timeout=10)
        time.sleep(0.8)
        # a shrunken grid detaches the panes that no longer exist — their
        # streams are gone, so the map must not keep claiming them
        for p in [k for k in _pane_map if k >= lay["cols"] * lay["rows"]]:
            del _pane_map[p]
        # --- bind: only panes whose target channel differs --------------
        need = [(p, i, name, meta) for p, (i, name, meta)
                in enumerate(order) if _pane_map.get(p) != name]
        if need:
            _tree_scroll_reset()
        # grace clock for the re-bind rule below — already-bound panes get
        # the same 12s so a slow re-attach isn't killed by our own click.
        bind_at: dict[int, float] = {p: time.time() for p in range(len(order))}
        for p, i, name, meta in need:
            pt = _pane_point(rects[p])
            _podman("xdotool", "mousemove", str(pt[0]), str(pt[1]),
                    "click", "1", timeout=10)
            time.sleep(0.4)
            _dblclick_row(meta["x"], meta["y"])
            _pane_map[p] = name
            bind_at[p] = time.time()
            # Pace the next bind: the DVR serializes cloud-P2P attaches and
            # rapid-fire dblclicks drop most of them (2026-10-06: back-to-back
            # binds left 3-4 of 5 panes showing no video while serial /snap
            # of the same channels attached fine). ~3s between attach
            # requests keeps the cold-bind cost far below serial snapping.
            time.sleep(3.0)
        # --- verify: one xwd per round; re-bind panes that stay dead ----
        # P2P attach is a coin flip, but a re-dblclick can abort an
        # in-flight attach — only re-bind a pane that has had >=12s to draw.
        # A pane also has to prove its stream is MOVING: a dropped attach
        # leaves the last decoded frame — textured enough to pass
        # _has_video but Snapshot on the dead stream writes no bmp
        # (2026-10-06: noble-club 9-pane run lost 4 panes this way). The
        # burned-in OSD clock guarantees a live stream changes every
        # round, so require two consecutive differing sightings.
        def _rebind(p: int, meta: dict) -> None:
            pt = _pane_point(rects[p])
            _podman("xdotool", "mousemove", str(pt[0]), str(pt[1]),
                    "click", "1", timeout=10)
            time.sleep(0.3)
            _dblclick_row(meta["x"], meta["y"])
            bind_at[p] = time.time()

        live: set[int] = set()
        dead: set[int] = set()          # frozen after a re-bind — give up
        prev_px: dict[int, int] = {}    # pane -> crc of last textured crop
        rebound: set[int] = set()       # panes that got their one re-bind
        deadline = time.time() + settle
        while time.time() < deadline and len(live) < len(order):
            try:
                w, h, rgb = _grab_xwd(2)
            except RuntimeError:
                time.sleep(1.0)
                continue
            now = time.time()
            for p, (i, name, meta) in enumerate(order):
                if p in live or p in dead:
                    continue
                pw, ph, prgb = crop_rgb(w, h, rgb, _inset(rects[p], 6))
                if not _has_video(pw, ph, prgb):
                    prev_px.pop(p, None)
                    if (now - bind_at.get(p, 0) > 12
                            and now + 4 < deadline):
                        _rebind(p, meta)
                    continue
                crc = zlib.crc32(prgb)
                old = prev_px.get(p)
                prev_px[p] = crc
                if old is None:
                    continue            # first sighting — prove it moves
                if crc != old:
                    live.add(p)
                    continue
                # frozen frame — one re-bind, then mark dead
                if p not in rebound and now + 4 < deadline:
                    _rebind(p, meta)
                    rebound.add(p)
                    prev_px.pop(p, None)
                else:
                    dead.add(p)
            time.sleep(2.0)
        for p, (i, name, meta) in enumerate(order):
            if p not in live:
                _pane_map.pop(p, None)
                manifest[i]["err"] = ("stream dropped after attach "
                                      "(frozen frame)" if p in dead else
                                      "pane shows no video (attach failed)")
        # --- capture ----------------------------------------------------
        # give the UI a breath — attach churn on still-pending panes eats
        # right-clicks fired in the same instant (menu never opens).
        time.sleep(1.5)
        retry_left = 2      # re-bind-and-retry budget for mid-cycle drops
        if native:
            for p, (i, name, meta) in enumerate(order):
                if p not in live:
                    continue
                got = None
                for attempt in range(2):
                    try:
                        got = _native_capture_pane(rects[p])
                        break
                    except Exception as exc:
                        manifest[i]["err"] = str(exc)[:120]
                        logger.info("composite: pane %d (%s) capture "
                                    "failed: %s", p, name, exc)
                        _pane_map.pop(p, None)
                        if (attempt > 0 or not retry_left
                                or "no bmp" not in str(exc)):
                            break
                        # stream died between verify and capture — a fresh
                        # attach is another coin flip, cheap enough to try
                        retry_left -= 1
                        _rebind(p, meta)
                        _pane_map[p] = name
                        time.sleep(10)
                        try:
                            wv, hv, rv = _grab_xwd(1)
                            ok = _has_video(*crop_rgb(wv, hv, rv,
                                                      _inset(rects[p], 6)))
                        except RuntimeError:
                            ok = False
                        if not ok:
                            manifest[i]["err"] = ("stream still dead after "
                                                  "re-bind")
                            break
                if got is None:
                    continue
                w3, h3, rgb3 = got
                if not _has_video(w3, h3, rgb3):
                    manifest[i]["err"] = "pane shows no video"
                    _pane_map.pop(p, None)
                    continue
                try:
                    _check_frame_identity(name, w3, h3, rgb3)
                except RuntimeError as exc:
                    # pane kept a stale/other channel's frame — drop the
                    # claim so the next cycle re-binds instead of serving
                    # the wrong camera again.
                    manifest[i]["err"] = str(exc)[:120]
                    _pane_map.pop(p, None)
                    continue
                results[i] = png_encode(w3, h3, rgb3)
                manifest[i].update(ok=True, w=w3, h=h3)
        else:
            w, h, rgb = _grab_xwd()
            for p, (i, name, meta) in enumerate(order):
                if p not in live:
                    continue
                pw, ph, prgb = crop_rgb(w, h, rgb, _inset(rects[p], 8))
                box = content_bbox(pw, ph, prgb)
                if box:
                    pw, ph, prgb = crop_rgb(pw, ph, prgb, box)
                if not _has_video(pw, ph, prgb):
                    manifest[i]["err"] = "pane shows no video"
                    _pane_map.pop(p, None)
                    continue
                try:
                    _check_frame_identity(name, pw, ph, prgb)
                except RuntimeError as exc:
                    manifest[i]["err"] = str(exc)[:120]
                    _pane_map.pop(p, None)
                    continue
                results[i] = png_encode(pw, ph, prgb)
                manifest[i].update(ok=True, w=pw, h=ph)
    return list(manifest.values()), results


def snap(query: str, settle: float, zoom: bool = True,
         _retry: int = 1, native: bool = False) -> tuple[bytes, str]:
    channels = load_channels()
    hit = resolve_channel(query, channels)
    if hit is None:
        raise LookupError(query)
    name, meta = hit
    with _lock:
        # clear a stray Capture modal first — it swallows clicks whole
        _dismiss_modal()
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
                # pane 1 (PANE_CLICK) is verified bound to this channel —
                # keep the composite pane map honest across interleavings.
                _pane_map[0] = name
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
        native_frame = None
        if zoom:
            # Zoom to the single-pane layout — deterministic via the
            # toolbar's 1-pane button (pane dbl-click toggles nothing in
            # this build). Activate pane 1 first so it stays the pane
            # shown. NOTE: no --sync — a synced mousemove blocks >30s while
            # the Wine app re-renders after the channel switch.
            _podman("xdotool", "mousemove", str(PANE_CLICK[0]),
                    str(PANE_CLICK[1]), "click", "1", timeout=10)
            _podman("xdotool", "mousemove", str(GRID1_BTN[0]),
                    str(GRID1_BTN[1]), "click", "1", timeout=10)
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
            try:
                if native:
                    native_frame = _native_capture()   # while still zoomed
            finally:
                _podman("xdotool", "mousemove", str(GRID4_BTN[0]),
                        str(GRID4_BTN[1]), "click", "1", timeout=10)
        elif native:
            native_frame = _native_capture(grid=True)
    if native_frame is not None:
        w, h, rgb = native_frame
        # The OSD snapshot is ALWAYS the active pane's channel at native
        # decode res — never a monitor composite (2026-10-03: what looked
        # like a 2-pane composite was Mini Mart's dual-view single frame).
        if not _has_video(w, h, rgb):
            raise RuntimeError(
                f"'{name}' pane shows no video — camera offline or "
                "stream stalled")
        try:
            _check_frame_identity(name, w, h, rgb)
        except RuntimeError:
            if _retry:
                logger.warning("'%s' stale-pane frame; forcing re-select",
                               name)
                return snap(query, settle, zoom, _retry=0, native=native)
            raise
        return png_encode(w, h, rgb), name
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
            return snap(query, settle, zoom, _retry=0, native=native)
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
        if url.path == "/composite":
            q = parse_qs(url.query)
            chs = [c.strip()
                   for c in (q.get("chs") or [""])[0].split(",") if c.strip()]
            try:
                settle = min(float((q.get("settle")
                                    or [COMPOSITE_SETTLE])[0]), 120.0)
            except ValueError:
                settle = COMPOSITE_SETTLE
            native = (q.get("native") or ["1"])[0] != "0"
            layout = (q.get("layout") or [""])[0] or None
            if not chs or len(chs) > MAX_COMPOSITE_PANES:
                self._json(400, {"error": "chs=<csv> required "
                                 f"(1-{MAX_COMPOSITE_PANES} channels)"})
                return
            try:
                manifest, pngs = composite(chs, settle, native, layout)
            except Exception as exc:
                logger.exception("composite failed")
                if "pane shows no video" in str(exc):
                    _watchdog_novideo()
                self._json(503, {"error": str(exc)})
                return
            if not any(c.get("ok") for c in manifest):
                _watchdog_novideo()
                self._json(503, {"error": "no channels captured",
                                 "cams": manifest})
                return
            _watchdog_ok()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("_manifest.json", json.dumps({"cams": manifest}))
                for i, png in sorted(pngs.items()):
                    zf.writestr(f"{i}.png", png)
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                logger.warning("composite: client disconnected mid-response")
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
            native = (q.get("native") or ["0"])[0] != "0"
            try:
                png, resolved = snap(ch, settle, zoom, native=native)
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
            try:
                self.wfile.write(png)
            except (BrokenPipeError, ConnectionResetError):
                logger.warning("snap: client disconnected mid-response")
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
