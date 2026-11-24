#!/usr/bin/env python3
"""omen-inpaint.py — masked defect repair via sd-cli on tony-omen.

The omen sd-server exposes no inpaint HTTP endpoint (spike 2026-11-07),
but sd-cli does: `-i INIT --mask MASK` runs masked denoise in img_gen
mode (latents.denoise_mask — pixels outside the mask are preserved
bit-exact). This driver:

  1. scp's the init image + mask to omen:/tmp
  2. runs sd-cli over ssh (niced, bounded threads)
  3. scp's the result back and lands it via land-render.py
     --lane local-file

Models (present on omen, ~/models/sd/):
  sdxl-base-1.0-Q8_0.gguf      quality lane — 20 steps, cfg 7  (slow CPU)
  sdxl-lightning-4step.q4_0    fast lane   — 8 steps, cfg 2   (cheap CPU)

Usage:
  omen-inpaint.py --image cand.png --mask mask.png \
      --prompt "repaired region description" \
      --campaign AS-... --asset-id cand-sdxl-inpaint [--model sdxl-q8]
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import time
from pathlib import Path

HOST = "tony-omen"
SD_CLI = "~/stable-diffusion.cpp/build/bin/sd-cli"
MODELS = {
    "sdxl-q8": {
        "path": "~/models/sd/sdxl-base-1.0-Q8_0.gguf",
        "steps": 20, "cfg": 7.0, "sampler": "euler_a",
    },
    "sdxl-lightning": {
        "path": "~/models/sd/sdxl-lightning-4step.q4_0.gguf",
        "steps": 8, "cfg": 2.0, "sampler": "euler_a",
    },
}
LAND = Path(__file__).resolve().parent / "land-render.py"


def png_dims(p: Path) -> tuple[int, int]:
    data = p.read_bytes()[:26]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"{p}: not a PNG (mask/init must be PNG)")
    return struct.unpack(">II", data[16:24])


def sh(cmd: list[str] | str, **kw) -> subprocess.CompletedProcess:
    shell = isinstance(cmd, str)
    return subprocess.run(cmd, shell=shell, capture_output=True,
                          text=True, **kw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--mask", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="deformed, warped, floating, "
                    "extra objects, cartoon, painting, watermark")
    ap.add_argument("--model", choices=list(MODELS), default="sdxl-q8")
    ap.add_argument("--steps", type=int, default=0, help="override model default")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--asset-id", required=True)
    ap.add_argument("--request-id", default="")
    ap.add_argument("--out", default="", help="local result path "
                    "(default ./<asset-id>.omen-inpaint.png)")
    ap.add_argument("--keep-remote", action="store_true")
    args = ap.parse_args()

    img, mask = Path(args.image), Path(args.mask)
    for p in (img, mask):
        if not p.exists():
            sys.exit(f"missing input: {p}")
    out = Path(args.out or f"{args.asset_id}.omen-inpaint.png")
    w, h = png_dims(img)
    spec = MODELS[args.model]
    steps = args.steps or spec["steps"]
    r_img = f"/tmp/{img.name}"
    r_mask = f"/tmp/{mask.name}"
    r_out = f"/tmp/{out.name}"
    r_log = f"/tmp/{out.stem}.log"

    r = sh(["scp", "-o", "BatchMode=yes", str(img), str(mask),
            f"{HOST}:/tmp/"], timeout=300)
    if r.returncode:
        sys.exit(f"scp up failed: {r.stderr[:300]}")

    cmd = (f"nice -n 10 {SD_CLI} -m {spec['path']} "
           f"-i {r_img} --mask {r_mask} "
           f"-p {args.prompt!r} -n {args.negative!r} "
           f"-W {w} -H {h} --steps {steps} "
           f"--cfg-scale {spec['cfg']} --strength {args.strength} "
           f"--sampling-method {spec['sampler']} -s {args.seed} "
           f"-t {args.threads} -o {r_out}")
    print(f"[omen-inpaint] launching on {HOST}: {args.model} "
          f"{steps} steps -> {r_out}")
    t0 = time.time()
    r = sh(["ssh", "-o", "BatchMode=yes", HOST,
            f"{cmd} > {r_log} 2>&1"], timeout=6 * 3600)
    elapsed = time.time() - t0
    tail = sh(["ssh", "-o", "BatchMode=yes", HOST,
               f"tail -15 {r_log}"], timeout=60)
    if r.returncode:
        sys.exit(f"sd-cli failed rc={r.returncode}\n{tail.stdout[-800:]}")
    print(f"[omen-inpaint] remote run done in {elapsed:.0f}s")
    print(tail.stdout[-600:])

    r = sh(["scp", "-o", "BatchMode=yes", f"{HOST}:{r_out}",
            str(out)], timeout=300)
    if r.returncode or not out.exists():
        sys.exit(f"scp back failed: {r.stderr[:300]}")
    if not args.keep_remote:
        sh(["ssh", "-o", "BatchMode=yes", HOST,
            f"rm -f {r_img} {r_mask} {r_out} {r_log}"], timeout=60)

    land = [sys.executable, str(LAND), "--lane", "local-file",
            "--job", str(out), "--campaign", args.campaign,
            "--asset-id", args.asset_id,
            "--request-id", args.request_id or out.stem]
    r = subprocess.run(land, capture_output=True, text=True, timeout=600)
    print(r.stdout[-1200:])
    if r.returncode:
        sys.exit(f"land failed: {r.stderr[-300:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
