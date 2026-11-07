#!/usr/bin/env python3
"""One-call campaign state receipt (MED-1103).

Replaces the 3-5 rclone calls agents make per status check: fetches
SESSION.json, lists 30-generated-raw/ + 35-comparison-run/, extracts
QC decision lines from 40-qc-review.md, and reports pending lane jobs.
Output is a compact JSON receipt.

Usage: campaign-status.py --campaign AS-... [--remote gdrive:ada-nest-adobe-stock]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone


def rclone(*args: str) -> str:
    r = subprocess.run(["rclone", *args], capture_output=True,
                       text=True, timeout=90)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300] or "rclone failed")
    return r.stdout


def fetch(remote: str, rel: str, dest: str) -> bool:
    try:
        rclone("copy", f"{remote}/campaigns/{CAMP}/" + rel, dest)
        return True
    except Exception:
        return False


def main() -> int:
    global CAMP
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", required=True)
    p.add_argument("--remote", default="gdrive:ada-nest-adobe-stock")
    args = p.parse_args()
    CAMP = args.campaign
    root = f"{args.remote}/campaigns/{CAMP}"

    session = {}
    try:
        out = subprocess.run(["rclone", "cat", f"{root}/SESSION.json"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            session = json.loads(out.stdout)
    except Exception:
        pass

    assets = []
    try:
        for line in rclone("lsf", f"{root}/30-generated-raw",
                           "--files-only").splitlines():
            x = line.strip()
            if x and not x.endswith(".manifest.json"):
                assets.append(x)
    except Exception:
        pass

    qc_decisions = []
    try:
        out = subprocess.run(["rclone", "cat", f"{root}/40-qc-review.md"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                if re.search(r"decision:\s*\S|Decision:\s*\S", line,
                             re.I):
                    qc_decisions.append(line.strip()[:120])
    except Exception:
        pass

    comp_files = []
    try:
        comp_files = [x.strip() for x in rclone(
            "lsf", f"{root}/35-comparison-run", "--files-only")
            .splitlines() if x.strip()]
    except Exception:
        pass

    comp = session.get("comparison") or {}
    receipt = {
        "campaign": CAMP,
        "at": datetime.now(timezone.utc).isoformat(),
        "status": session.get("status"),
        "stage": session.get("current_stage"),
        "asset_ids": session.get("asset_ids") or [],
        "generated_files": assets,
        "pending_decisions": session.get("pending_decisions") or [],
        "comparison": {
            "baseline": comp.get("baseline_asset_id"),
            "candidate": comp.get("candidate_asset_id"),
            "candidate_qc": comp.get("candidate_qc_decision"),
            "revision_qc": comp.get("revision_qc_decision"),
            "revision_lane": comp.get("revision_provider"),
            "revision_job": comp.get("revision_job"),
            "last_landed": comp.get("last_landed"),
        },
        "qc_decision_lines": qc_decisions[-6:],
        "comparison_run_files": comp_files,
        "adobe_upload": False,
    }
    print(json.dumps(receipt, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
