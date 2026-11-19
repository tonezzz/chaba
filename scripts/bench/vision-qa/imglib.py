#!/usr/bin/env python3
"""imglib — tiny dependency-free canvas for the vision-qa bench corpus.

stdlib + numpy only (no PIL on runners). Renders RGB pixel buffers, writes
real PNGs via zlib, draws shapes/gradients/text (embedded 5x7 bitmap font,
uppercase-only), and applies stock-QC defects (blur, noise, banding,
watermark) deterministically.
"""
import struct
import zlib

import numpy as np


# ------------------------------------------------------------------- font
# 5x7 bitmap font, MSB = left pixel. Uppercase + digits + common punct.
_FONT = {
    " ": [0, 0, 0, 0, 0, 0, 0],
    "!": [0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0, 0b00100],
    '"': [0b01010, 0b01010, 0, 0, 0, 0, 0],
    "%": [0b11001, 0b11010, 0b00010, 0b00100, 0b01000, 0b01011, 0b10011],
    "'": [0b00100, 0b00100, 0b01000, 0, 0, 0, 0],
    "(": [0b00010, 0b00100, 0b01000, 0b01000, 0b01000, 0b00100, 0b00010],
    ")": [0b01000, 0b00100, 0b00010, 0b00010, 0b00010, 0b00100, 0b01000],
    "+": [0, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0],
    ",": [0, 0, 0, 0, 0b00100, 0b00100, 0b01000],
    "-": [0, 0, 0, 0b11111, 0, 0, 0],
    ".": [0, 0, 0, 0, 0, 0b01100, 0b01100],
    "/": [0b00001, 0b00010, 0b00010, 0b00100, 0b01000, 0b01000, 0b10000],
    ":": [0, 0b01100, 0b01100, 0, 0b01100, 0b01100, 0],
    "?": [0b01110, 0b10001, 0b00001, 0b00110, 0b00100, 0, 0b00100],
    "0": [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
    "1": [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    "2": [0b01110, 0b10001, 0b00001, 0b00110, 0b01000, 0b10000, 0b11111],
    "3": [0b11111, 0b00010, 0b00100, 0b00010, 0b00001, 0b10001, 0b01110],
    "4": [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
    "5": [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
    "6": [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
    "7": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
    "8": [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
    "9": [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],
    "A": [0b01110, 0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001],
    "B": [0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110],
    "C": [0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110],
    "D": [0b11100, 0b10010, 0b10001, 0b10001, 0b10001, 0b10010, 0b11100],
    "E": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111],
    "F": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000],
    "G": [0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01111],
    "H": [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    "I": [0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    "J": [0b00111, 0b00010, 0b00010, 0b00010, 0b00010, 0b10010, 0b01100],
    "K": [0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001],
    "L": [0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111],
    "M": [0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001],
    "N": [0b10001, 0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001],
    "O": [0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    "P": [0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000],
    "Q": [0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101],
    "R": [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
    "S": [0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110],
    "T": [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
    "U": [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    "V": [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100],
    "W": [0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010],
    "X": [0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001],
    "Y": [0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100],
    "Z": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111],
}


def write_png(path, arr):
    """arr: HxWx3 uint8 -> real PNG file."""
    a = np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8))
    h, w, _ = a.shape
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


class Canvas:
    def __init__(self, w, h, bg=(255, 255, 255)):
        self.w, self.h = w, h
        self.px = np.tile(np.asarray(bg, np.float32), (h, w, 1))

    # ------------------------------------------------------------- shapes
    def rect(self, x, y, w, h, color, fill=True, width=1, alpha=1.0):
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(self.w, int(x + w)), min(self.h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        c = np.asarray(color, np.float32)
        if fill:
            reg = self.px[y0:y1, x0:x1]
            self.px[y0:y1, x0:x1] = reg * (1 - alpha) + c * alpha
        else:
            self.rect(x0, y0, x1 - x0, width, color, alpha=alpha)
            self.rect(x0, y1 - width, x1 - x0, width, color, alpha=alpha)
            self.rect(x0, y0, width, y1 - y0, color, alpha=alpha)
            self.rect(x1 - width, y0, width, y1 - y0, color, alpha=alpha)

    def circle(self, cx, cy, r, color, fill=True, width=1, alpha=1.0):
        ys, xs = np.mgrid[0:self.h, 0:self.w]
        d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        mask = (d <= r) if fill else ((d <= r) & (d >= r - width))
        c = np.asarray(color, np.float32)
        self.px[mask] = self.px[mask] * (1 - alpha) + c * alpha

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0):
        ys, xs = np.mgrid[0:self.h, 0:self.w]
        mask = ((xs - cx) / max(rx, 1)) ** 2 + ((ys - cy) / max(ry, 1)) ** 2 <= 1
        c = np.asarray(color, np.float32)
        self.px[mask] = self.px[mask] * (1 - alpha) + c * alpha

    def poly(self, pts, color, alpha=1.0):
        ys, xs = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        inside = np.zeros((self.h, self.w), bool)
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            cond = ((y0 > ys) != (y1 > ys)) & (
                xs < (x1 - x0) * (ys - y0) / (y1 - y0 + 1e-9) + x0)
            inside ^= cond
        c = np.asarray(color, np.float32)
        self.px[inside] = self.px[inside] * (1 - alpha) + c * alpha

    def line(self, x0, y0, x1, y1, color, width=1, alpha=1.0):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.linspace(x0, x1, n)
        ys = np.linspace(y0, y1, n)
        hw = max(width // 2, 0)
        for x, y in zip(xs, ys):
            self.rect(x - hw, y - hw, width or 1, width or 1, color, alpha=alpha)

    def gradient_v(self, c_top, c_bottom):
        t = np.linspace(0, 1, self.h, dtype=np.float32)[:, None, None]
        a = np.asarray(c_top, np.float32)[None, None, :]
        b = np.asarray(c_bottom, np.float32)[None, None, :]
        self.px = a + (b - a) * np.broadcast_to(t, (self.h, self.w, 3))

    # --------------------------------------------------------------- text
    def text(self, x, y, s, color, scale=2, alpha=1.0):
        cx = int(x)
        for ch in s.upper():
            glyph = _FONT.get(ch)
            if glyph is None:
                cx += 4 * scale
                continue
            for row, bits in enumerate(glyph):
                for col in range(5):
                    if bits >> (4 - col) & 1:
                        self.rect(cx + col * scale, int(y) + row * scale,
                                  scale, scale, color, alpha=alpha)
            cx += 6 * scale

    def text_size(self, s, scale=2):
        return len(s) * 6 * scale, 7 * scale

    def text_rot(self, x, y, s, color, scale=3, angle_deg=-30, alpha=0.45):
        """Semi-transparent rotated text (watermarks)."""
        w, h = self.text_size(s, scale)
        spr = Canvas(w + 4, h + 4, bg=(0, 0, 0))
        spr.text(2, 2, s, (255, 255, 255), scale=scale)
        mask = spr.px[:, :, 0] > 127
        sy, sx = np.nonzero(mask)
        cx, cy = w / 2, h / 2
        th = np.radians(angle_deg)
        dx = (sx - cx) * np.cos(th) - (sy - cy) * np.sin(th) + x
        dy = (sx - cx) * np.sin(th) + (sy - cy) * np.cos(th) + y
        c = np.asarray(color, np.float32)
        for px_, py_ in zip(dx.astype(int), dy.astype(int)):
            if 0 <= px_ < self.w and 0 <= py_ < self.h:
                self.px[py_, px_] = self.px[py_, px_] * (1 - alpha) + c * alpha

    # ------------------------------------------------------------- defects
    def box_blur(self, r=3, passes=2):
        for _ in range(passes):
            for axis in (0, 1):
                pad = [(0, 0)] * 3
                pad[axis] = (r, r)
                p = np.pad(self.px, pad, mode="edge")
                c = np.cumsum(p, axis=axis)
                lo = [slice(None)] * 3
                hi = [slice(None)] * 3
                lo[axis] = slice(0, -2 * r - 1)
                hi[axis] = slice(2 * r + 1, None)
                self.px = (c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)

    def noise(self, sigma=30, seed=0):
        rng = np.random.default_rng(seed)
        self.px += rng.normal(0, sigma, self.px.shape).astype(np.float32)

    def banding(self, period=3, amp=35):
        bands = np.where((np.arange(self.h) // period) % 2, -amp, 0)
        self.px += bands[:, None, None].astype(np.float32)

    def save(self, path):
        write_png(path, self.px)
