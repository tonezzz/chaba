#!/usr/bin/env python3
"""inbox-processor.py — auto-execute picker repair submissions.

Scans ~/adobe-work/inbox/*.json (written by picker-server POST /submit).
For each unprocessed request:
  1. resolve the source image (picker dir first, else pull the named
     asset from the campaign's 30-candidates/ on Drive)
  2. fire land-render.py --lane gemini-image --init-image SRC
     --prompt <gemini_prompt>  (region is described in the prompt text;
     Gemini has no mask input — cf-inpaint remains the masked lane)
  3. move the request to inbox/done/ so it never re-fires

Cron: */5 * * * * python3 .../inbox-processor.py
Log:   ~/adobe-work/inbox/processor.log
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

INBOX = Path.home() / "adobe-work/inbox"
PICKER_DIR = Path.home() / "adobe-work/picker"
LAND = Path(__file__).resolve().parent / "land-render.py"
CAMPAIGN = "AS-2026-11-05-REMOTE-WORK-001"
REMOTE = "gdrive:ada-nest-adobe-stock"
GEMINI_MODEL = "gemini-2.5-flash-image"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line)
    with open(INBOX / "processor.log", "a") as f:
        f.write(line + "\n")


def resolve_image(name: str) -> Path | None:
    for d in (PICKER_DIR, INBOX):
        p = d / name
        if p.exists():
            return p
    # name may be an asset id — pull latest candidate from Drive
    for cand in (f"{name}.png", f"{name}.jpg"):
        dst = INBOX / cand
        r = subprocess.run(
            ["rclone", "copy",
             f"{REMOTE}/campaigns/{CAMPAIGN}/30-candidates/{name}/{cand}",
             str(INBOX)], capture_output=True, timeout=120)
        if dst.exists():
            return dst
    return None


def process(req_path: Path) -> str:
    body = json.loads(req_path.read_text())
    rid = req_path.stem
    image = body.get("image", "")
    prompt = body.get("gemini_prompt") or body.get("comment") or ""
    src = resolve_image(image)
    if not src:
        return f"{rid}: image_not_found:{image}"
    asset_id = f"picker-{rid}"[:80]
    env = dict(os.environ)
    if not env.get("GEMINI_API_KEY"):
        # load key file if present
        kf = Path.home() / ".config/secrets/gemini-api-key.env"
        if kf.exists():
            for line in kf.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    cmd = [sys.executable, str(LAND), "--lane", "gemini-image",
           "--job", GEMINI_MODEL, "--prompt", prompt,
           "--init-image", str(src), "--campaign", CAMPAIGN,
           "--asset-id", asset_id, "--request-id", rid,
           "--timeout-s", "300"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=360, env=env)
    try:
        out = json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        out = {"ok": False, "error": (r.stderr or r.stdout)[-300:]}
    if out.get("ok"):
        done = INBOX / "done"
        done.mkdir(exist_ok=True)
        shutil.move(str(req_path), str(done / req_path.name))
        mask = req_path.with_suffix(".mask.png")
        if mask.exists():
            shutil.move(str(mask), str(done / mask.name))
        return f"{rid}: LANDED {out.get('asset_id')} {out.get('sha256','')[:12]}"
    return f"{rid}: FAILED {out.get('error', r.stderr[-200:])}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    INBOX.mkdir(parents=True, exist_ok=True)
    reqs = sorted(INBOX.glob("*.json"))
    if not reqs:
        return 0
    for p in reqs:
        try:
            log(process(p))
        except Exception as exc:
            log(f"{p.stem}: processor_error:{type(exc).__name__}:{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
