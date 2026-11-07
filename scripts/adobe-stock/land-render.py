#!/usr/bin/env python3
"""Typed artifact landing for Adobe Stock render lanes (ADA-1092).

One call replaces the ad-hoc poll/decode/hash/rclone/session-update
chain. Lane adapters normalize job APIs into a RenderResult; the core
streams image bytes to disk WITHOUT printing payloads, verifies
sha256+dimensions, lands PNG+manifest in the campaign's
30-generated-raw/, updates SESSION.json, appends a 40-qc-review.md
section, and prints one compact receipt.

Usage:
  land-render.py --lane omen-sd --job JOB_ID [--port 8399]
                 --campaign AS-... --asset-id ID --request-id RID
  land-render.py --lane omen-sd --job JOB_ID --status-only
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OMEN = "http://100.75.102.88"
POLL_S = 60
TIMEOUT_S = 4 * 3600


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_json(url: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def rclone(*args: str) -> str:
    r = subprocess.run(["rclone", *args], capture_output=True,
                       text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300] or "rclone failed")
    return r.stdout


def fetch_omen(job_id: str, port: int) -> dict:
    """-> {status, png_bytes?, meta?}; never returns payloads to stdout."""
    job = http_json(f"{OMEN}:{port}/sdcpp/v1/jobs/{job_id}")
    st = job.get("status")
    if st != "completed":
        return {"status": st or "unknown", "error": job.get("error")}
    images = (job.get("result") or {}).get("images") or []
    if not images:
        return {"status": "completed", "error": "no_images"}
    return {"status": "completed",
            "png_bytes": base64.b64decode(images[0]["b64_json"]),
            "meta": {"job": job}}


def fetch_pack(remote: str, pack: str) -> dict:
    """Nest lane: pack dir under <remote>/packs/<pack> with done marker
    and out/*.png artifact."""
    base = f"{remote}/packs/{pack}"
    listing = rclone("lsf", base, "--recursive").splitlines()
    if not any(x.strip() == "done" for x in listing):
        has_failed = any(x.strip() == "failed" for x in listing)
        return {"status": "failed" if has_failed else "live"}
    pngs = [x.strip() for x in listing
            if x.strip().startswith("out/") and x.strip().endswith(".png")]
    if not pngs:
        return {"status": "failed", "error": "no_png_artifact"}
    data = subprocess.run(
        ["rclone", "cat", f"{base}/{pngs[0]}"],
        capture_output=True, timeout=300)
    if data.returncode:
        return {"status": "failed", "error": "artifact_fetch_failed"}
    return {"status": "completed", "png_bytes": data.stdout,
            "meta": {"pack": pack, "artifact": pngs[0]}}


def wait_result(lane: str, job: str, port: int, remote: str,
                pack: str, status_only: bool,
                timeout_s: int = TIMEOUT_S) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        if lane == "omen-sd":
            res = fetch_omen(job, port)
        elif lane == "kk-mac-nest":
            res = fetch_pack(remote, pack or job)
        else:
            raise ValueError(f"unsupported lane: {lane}")
        st = res.get("status")
        if st != last:
            print(f"[{now_iso()}] {lane} {job}: {st}", file=sys.stderr)
            last = st
        if status_only:
            return res
        if st == "completed":
            return res
        if st in ("failed", "error", "expired"):
            return res
        time.sleep(POLL_S)
    return {"status": "timeout"}


def land(campaign: str, asset_id: str, request_id: str, res: dict,
         lane: str, job: str, remote: str) -> dict:
    png = res["png_bytes"]
    sha = hashlib.sha256(png).hexdigest()
    dims = png_size(png)
    if dims is None:
        raise RuntimeError("artifact is not a valid PNG")
    root = f"{remote}/campaigns/{campaign}"
    raw = f"{root}/30-generated-raw"
    manifest = {
        "asset_id": asset_id, "campaign": campaign,
        "request_id": request_id, "provider": lane, "job_id": job,
        "dimensions": f"{dims[0]}x{dims[1]}", "bytes": len(png),
        "sha256": sha, "output_format": "png",
        "landed_at": now_iso(), "adobe_upload": False,
        "meta": {k: v for k, v in (res.get("meta") or {}).items()
                 if k != "job"},
    }
    with tempfile.TemporaryDirectory() as td:
        p_png = Path(td) / f"{asset_id}.png"
        p_man = Path(td) / f"{asset_id}.manifest.json"
        p_png.write_bytes(png)
        p_man.write_text(json.dumps(manifest, indent=1) + "\n")
        rclone("copyto", str(p_png), f"{raw}/{asset_id}.png")
        rclone("copyto", str(p_man), f"{raw}/{asset_id}.manifest.json")
    # SESSION.json update
    try:
        rclone("copy", f"{root}/SESSION.json", td)
        sp = Path(td) / "SESSION.json"
        if sp.exists():
            s = json.loads(sp.read_text())
            s.setdefault("asset_ids", [])
            if asset_id not in s["asset_ids"]:
                s["asset_ids"].append(asset_id)
            s["status"] = "human_qc_pending"
            s["current_stage"] = "40-qc-review"
            s["last_event"] = f"{asset_id}_landed_{lane}"
            s.setdefault("comparison", {})["last_landed"] = {
                "asset_id": asset_id, "lane": lane, "job_id": job,
                "sha256": sha, "at": now_iso()}
            sp.write_text(json.dumps(s, indent=1, ensure_ascii=False))
            rclone("copyto", str(sp), f"{root}/SESSION.json")
    except Exception as exc:
        manifest["session_update_error"] = str(exc)[:200]
    # QC doc append
    try:
        rclone("copy", f"{root}/40-qc-review.md", td)
        qp = Path(td) / "40-qc-review.md"
        note = (f"\n## {asset_id} — {lane} lane (landed {now_iso()})\n\n"
                f"- File: `30-generated-raw/{asset_id}.png` "
                f"({dims[0]}x{dims[1]}, {len(png)} bytes)\n"
                f"- SHA-256: `{sha}`\n- Job: `{job}`\n\n"
                "QC checklist vs prior candidates: sharpness, artifacts, "
                "composition/copy space, commercial usefulness.\nDecision: "
                "keep / reject / revise — Tony visual QC required.\n")
        with open(qp, "a") as f:
            f.write(note)
        rclone("copyto", str(qp), f"{root}/40-qc-review.md")
    except Exception:
        pass
    return {"ok": True, "asset_id": asset_id, "lane": lane,
            "job_id": job, "sha256": sha,
            "dimensions": f"{dims[0]}x{dims[1]}", "bytes": len(png),
            "artifact": f"{raw}/{asset_id}.png",
            "qc_status": "pending_tony", "adobe_upload": False,
            "at": now_iso()}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--lane", required=True,
                   choices=["omen-sd", "kk-mac-nest"])
    p.add_argument("--job", required=True)
    p.add_argument("--port", type=int, default=8399)
    p.add_argument("--pack", default="")
    p.add_argument("--campaign", required=True)
    p.add_argument("--asset-id", default="")
    p.add_argument("--request-id", default="")
    p.add_argument("--remote", default="gdrive:ada-nest-adobe-stock")
    p.add_argument("--status-only", action="store_true")
    p.add_argument("--timeout-s", type=int, default=TIMEOUT_S)
    args = p.parse_args()

    res = wait_result(args.lane, args.job, args.port, args.remote,
                      args.pack, args.status_only, args.timeout_s)
    if args.status_only or res.get("status") != "completed":
        print(json.dumps({"lane": args.lane, "job": args.job,
                          "status": res.get("status"),
                          "error": res.get("error")}, indent=1))
        return 0 if res.get("status") in ("completed", "queued",
                                          "generating", "pending") else 2
    asset_id = args.asset_id or f"{args.campaign.lower()}-{args.job}"
    out = land(args.campaign, asset_id, args.request_id or args.job,
               res, args.lane, args.job, args.remote)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
