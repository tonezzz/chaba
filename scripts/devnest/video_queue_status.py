#!/usr/bin/env python3
"""Read-only inventory for the two video Nest queues."""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import time
from collections import Counter

VIDEO = re.compile(r"(video|ltx|story|shot|panel|preview|docpilot|mps)", re.I)


def rclone(*args: str) -> list[str]:
    p = subprocess.run(
        ["rclone", *args], capture_output=True, text=True, timeout=180
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return [x.rstrip("/") for x in p.stdout.splitlines() if x.strip()]


def claim_age(remote: str, pack: str, worker: str) -> float | None:
    p = subprocess.run(
        ["rclone", "lsl", f"{remote}/packs/{pack}/claim/{worker}"],
        capture_output=True, text=True, timeout=30,
    )
    if p.returncode:
        return None
    parts = p.stdout.split()
    if len(parts) < 3:
        return None
    try:
        stamp = datetime.datetime.fromisoformat(
            f"{parts[1]}T{parts[2]}+00:00"
        )
        return max(0.0, time.time() - stamp.timestamp()) / 3600
    except ValueError:
        return None


def inventory(remote: str, stale_hours: float) -> dict:
    lines = rclone("lsf", f"{remote}/packs", "--recursive")
    packs: dict[str, set[str]] = {}
    for line in lines:
        parts = line.split("/", 1)
        if len(parts) == 2:
            packs.setdefault(parts[0], set()).add(parts[1])
    selected = {name: entries for name, entries in packs.items()
                if VIDEO.search(name)}
    states = Counter()
    claims = []
    stale_claims = []
    artifacts = 0
    for name, entries in selected.items():
        if "done" in entries:
            state = "done"
        elif "failed" in entries:
            state = "failed"
        else:
            state = "queued"
        states[state] += 1
        pack_claims = [
            entry.removeprefix("claim/")
            for entry in entries
            if entry.startswith("claim/") and entry != "claim/"
        ]
        for claim in pack_claims:
            row = {"pack": name, "worker": claim}
            age = claim_age(remote, name, claim)
            row["age_hours"] = round(age, 2) if age is not None else None
            (stale_claims if age is not None and age > stale_hours
             else claims).append(row)
        if any(entry.startswith(("out/", "shots/", "final/"))
               for entry in entries):
            artifacts += 1
    return {
        "remote": remote,
        "packages": len(selected),
        "states": dict(states),
        "active_claims": claims,
        "stale_claims": stale_claims,
        "artifact_packages": artifacts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--remote", action="append",
        default=["gdrive:ada-nest-kk-mac-video-pilot",
                 "gdrive:ada-nest"],
    )
    ap.add_argument("--stale-hours", type=float, default=2.0)
    args = ap.parse_args()
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "queues": [
            inventory(remote, args.stale_hours)
            for remote in dict.fromkeys(args.remote)
        ],
    }
    report["active_claims"] = sum(
        len(queue["active_claims"]) for queue in report["queues"]
    )
    report["stale_claims"] = sum(
        len(queue["stale_claims"]) for queue in report["queues"]
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
