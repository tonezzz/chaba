#!/usr/bin/env python3
"""inpaint-mask.py — build an inpaint mask from a QC-note region spec.

Input = a candidate image + a defect region from a QC note / picker
request: one or more axis-aligned boxes ("x,y,w,h") and/or polygons
("x1,y1;x2,y2;..."). Output = a PNG mask where WHITE marks pixels to
regenerate and BLACK marks pixels to preserve — the convention used by
cf-inpaint (Workers AI), sd-cli, and diffusers inpaint pipelines.

Options soften the mask for better blends: --dilate grows the region
(pixels), --feather blurs the edge (pixels, sigma).

Usage:
  inpaint-mask.py --image cand.png --box 177,290,319,559 --out mask.png
  inpaint-mask.py --image cand.png --poly 10,10;200,10;200,300 --dilate 8 \
      --feather 12 --out mask.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    sys.exit("inpaint-mask.py needs Pillow (pip install pillow)")


def parse_box(spec: str) -> tuple[int, int, int, int]:
    x, y, w, h = (int(v) for v in spec.split(","))
    return x, y, x + w, y + h


def parse_poly(spec: str) -> list[tuple[int, int]]:
    pts = []
    for pair in spec.split(";"):
        x, y = (int(v) for v in pair.split(","))
        pts.append((x, y))
    if len(pts) < 3:
        raise ValueError(f"polygon needs >=3 points: {spec}")
    return pts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="source image (for size)")
    ap.add_argument("--box", action="append", default=[],
                    help="rect region 'x,y,w,h' (repeatable)")
    ap.add_argument("--poly", action="append", default=[],
                    help="polygon 'x1,y1;x2,y2;...' (repeatable)")
    ap.add_argument("--dilate", type=int, default=0,
                    help="grow region by N px before feathering")
    ap.add_argument("--feather", type=int, default=8,
                    help="gaussian blur radius on mask edge (0=hard)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not args.box and not args.poly:
        ap.error("at least one --box or --poly required")

    src = Image.open(args.image)
    mask = Image.new("L", src.size, 0)
    draw = ImageDraw.Draw(mask)
    for b in args.box:
        draw.rectangle(parse_box(b), fill=255)
    for p in args.poly:
        draw.polygon(parse_poly(p), fill=255)

    if args.dilate > 0:
        mask = mask.filter(ImageFilter.MaxFilter(args.dilate * 2 + 1))
    if args.feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(args.feather))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mask.save(out)
    print(f"{out}: {src.size[0]}x{src.size[1]} "
          f"boxes={len(args.box)} polys={len(args.poly)} "
          f"dilate={args.dilate} feather={args.feather}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
