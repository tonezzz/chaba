#!/usr/bin/env python3
"""Snapshot a Lovelace card via playlived headless Chrome and publish as PNG.

Flow:
  1. Create a playwright-headless session on playlived (127.0.0.1:9230).
  2. Navigate to the HA origin, inject a long-lived token into localStorage
     (hassTokens), then navigate to the target view.
  3. Deep-query the DOM (piercing shadow roots) for the card element, get its
     bounding box, screenshot the viewport, crop to the card with PIL.
  4. Resize to fit the target box (default 240x320 for the CYD display) and
     write atomically to the published path.

Usage:
  snapshot-card.py --url http://127.0.0.1:8124/tony-test/pf3 \
      --selector sunsynk-power-flow-card --out /srv/public/snapshots/pv1.png

Env:
  HA_TOKEN_FILE   file containing HA_LONG_LIVED_TOKEN=...
  PLAYLIVED_URL   default http://127.0.0.1:9230
"""
import argparse
import io
import json
import os
import sys
import tempfile
import time
import urllib.request

from PIL import Image

PLAYLIVED = os.environ.get("PLAYLIVED_URL", "http://127.0.0.1:9230")
TOKEN_FILE = os.environ.get("HA_TOKEN_FILE", os.path.expanduser(
    "~/.config/secrets/home-assistant-token.env"))


def load_token():
    with open(TOKEN_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("HA_LONG_LIVED_TOKEN="):
                return line.split("=", 1)[1]
    raise SystemExit(f"HA_LONG_LIVED_TOKEN not found in {TOKEN_FILE}")


def rpc(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        PLAYLIVED + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = json.load(resp)
    if not out.get("ok"):
        raise RuntimeError(f"{method} {path} failed: {out}")
    return out


def action(sid, name, payload=None):
    return rpc("POST", f"/sessions/{sid}/{name}", payload or {})


def action_retry(sid, name, payload=None, tries=10, delay=1.0):
    last = None
    for _ in range(tries):
        try:
            return action(sid, name, payload)
        except Exception as e:
            last = e
            time.sleep(delay)
    raise last


FIND_ELEMENT_JS = """
(sel) => {
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches && el.matches(sel)) return el;
      if (el.shadowRoot) { const r = walk(el.shadowRoot); if (r) return r; }
    }
    return null;
  };
  const el = walk(document) ||
    Array.from(document.querySelectorAll('*')).find(e => e.shadowRoot && walk(e.shadowRoot));
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.x, y: r.y, w: r.width, h: r.height,
           vw: window.innerWidth, vh: window.innerHeight };
}
"""


def snapshot(url, selector, out_path, max_w, max_h, wait_s, bands):
    token = load_token()
    origin = url.split("/", 3)[0] + "//" + url.split("/", 3)[2]
    sess = rpc("POST", "/sessions",
               {"type": "playwright-headless", "target": "local"})
    sid = sess["session_id"]
    try:
        # Establish origin context so localStorage is writable for this origin.
        action(sid, "navigate", {"url": origin + "/"})
        time.sleep(2.0)
        expires = int(time.time() * 1000) + 10 * 365 * 24 * 3600 * 1000
        hass_tokens = {
            "access_token": token, "token_type": "Bearer",
            "expires_in": 10 * 365 * 24 * 3600, "expires": expires,
            "hassUrl": origin, "clientId": origin + "/",
            "refresh_token": "",
        }
        action_retry(sid, "eval", {"script":
            f"(() => {{ localStorage.setItem('hassTokens', {json.dumps(json.dumps(hass_tokens))}); return true; }})()"})
        action(sid, "navigate", {"url": url})
        time.sleep(2.0)

        box = None
        deadline = time.time() + wait_s
        while time.time() < deadline:
            time.sleep(1.5)
            try:
                res = action(sid, "eval",
                             {"script": f"({FIND_ELEMENT_JS})({json.dumps(selector)})"})
                box = res.get("result")
            except Exception:
                box = None
            if box and box.get("w", 0) > 10 and box.get("h", 0) > 10:
                break
            box = None
        if not box:
            raise RuntimeError(f"selector {selector!r} not found/visible at {url}")
        # Let animations settle before capture.
        time.sleep(1.0)
        shot = action(sid, "screenshot", {})
        img = Image.open(io.BytesIO(
            __import__("base64").b64decode(shot["base64"]))).convert("RGB")
        left = max(0, int(box["x"]))
        top = max(0, int(box["y"]))
        right = min(img.width, int(box["x"] + box["w"]))
        bottom = min(img.height, int(box["y"] + box["h"]))
        img = img.crop((left, top, right, bottom))
        scale = min(max_w / img.width, max_h / img.height, 1.0)
        if scale < 1.0:
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))),
                             Image.LANCZOS)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        def atomic_save(image, path):
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                                       suffix=".png")
            os.close(fd)
            image.save(tmp, "PNG")
            os.replace(tmp, path)

        atomic_save(img, out_path)
        print(f"wrote {out_path} ({img.width}x{img.height})")

        if bands > 1:
            base, ext = os.path.splitext(out_path)
            band_h = img.height // bands
            for i in range(bands):
                top = i * band_h
                bottom = img.height if i == bands - 1 else (i + 1) * band_h
                band = img.crop((0, top, img.width, bottom))
                path = f"{base}_{i}.bmp"
                fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                                           suffix=".bmp")
                os.close(fd)
                band.save(tmp, "BMP")
                os.replace(tmp, path)
            print(f"wrote {bands} BMP bands at {base}_N.bmp")
    finally:
        try:
            rpc("DELETE", f"/sessions/{sid}")
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--selector", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-w", type=int, default=240)
    p.add_argument("--max-h", type=int, default=320)
    p.add_argument("--wait", type=float, default=30)
    p.add_argument("--bands", type=int, default=1,
                   help="also write N horizontal band files <out>_N.png")
    args = p.parse_args()
    snapshot(args.url, args.selector, args.out, args.max_w, args.max_h,
             args.wait, args.bands)


if __name__ == "__main__":
    main()
