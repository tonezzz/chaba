#!/usr/bin/env python3
"""inpaint-composite.py — paste an inpainted patch back into the source
image, blended at the mask edge.

Used after any lane that returns less than a full-frame result or a
full-frame output that needs outside-mask pixels restored bit-exact
(e.g. CF SD1.5 512x512 upscaled into the masked region, or sd-cli
full-frame denoise composited back inside the feathered mask).

Usage: inpaint-composite.py SRC PATCH_CROP X0 Y0 W H MASK_FULL OUT
  SRC          full-res source image
  PATCH_CROP   inpaint output covering region (X0,Y0,W,H) — resized to fit
  X0 Y0 W H    target rect in SRC coords
  MASK_FULL    full-size mask PNG (white=patched area) — edge is blurred
  OUT          composited output image
"""
import sys
from PIL import Image, ImageFilter

src_p, patch_p, x0, y0, w, h, mask_p, out_p = sys.argv[1:]
x0, y0, w, h = int(x0), int(y0), int(w), int(h)
src = Image.open(src_p).convert("RGB")
patch = Image.open(patch_p).convert("RGB").resize((w, h), Image.LANCZOS)
mask = Image.open(mask_p).convert("L").crop((x0, y0, x0 + w, y0 + h))
mask = mask.filter(ImageFilter.GaussianBlur(6))
base = src.crop((x0, y0, x0 + w, y0 + h))
comp = Image.composite(patch, base, mask)
src.paste(comp, (x0, y0))
src.save(out_p)
print(f"{out_p}: patch {w}x{h} at {x0},{y0} blended")
