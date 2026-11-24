#!/usr/bin/env python3
"""Read-only inventory/status for the video Nest queues (OPS-1042).

Inventories EVERY pack under each queue's ``packs/`` root — nothing is
filtered out — and classifies it on two axes:

  state   (vocabulary of docs/kb/video-queue-claim-lifecycle-procedure.md):
    done      durable ``done`` marker present
    failed    terminal ``failed`` marker present
    retired   ``retired`` marker present (historical/support, never rerun)
    running   fresh claim (< --stale-hours) owned by a live worker
    stale     claim older than the lease TTL — claimed but expired,
              needs reconciliation before release (the card spec's
              "claimed" state)
    queued    no claim, no terminal marker

  kind
    render    pack name matches the video-lane pattern
    support   everything else (evals, benches, infra, doc ops) — the
              card spec's "support/other" bucket

State precedence is done > failed > retired > claims > queued: a pack
that finished and was later retired still reports ``done`` (its markers
list keeps ``retired`` visible). The tool is strictly read-only: it
never claims, releases, or mutates anything.

Remote note: the card spec writes the pilot root as
``gdrive:ada-nest-kk-mac-video-pilot``; the real rclone path is
``gdrive:ada-nest/kk-mac-video-pilot`` (there is no top-level
``ada-nest-kk-mac-video-pilot`` Drive dir — verified 2026-11-24).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter

# Video-lane pack names. Kept deliberately broad — a missed render pack
# hides work; a false-positive only relabels kind, never state.
VIDEO = re.compile(
    r"(video|ltx|story|shot|panel|preview|docpilot|doc-vo|doc-v2|"
    r"mps|mlx|vimax|i2v|goldenhour|nasa|embed|vo-)",
    re.I,
)

TERMINAL = ("done", "failed", "retired")

# fleet hosts keep rclone in ~/.local/bin which non-login shells don't
# have on PATH — same resolution as scripts/ada/nest-worker.py
RCLONE = shutil.which("rclone") or os.path.expanduser(
    "~/.local/bin/rclone")


def rclone(*args: str) -> list[str]:
    p = subprocess.run(
        [RCLONE, *args], capture_output=True, text=True, timeout=180
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return [x.rstrip("/") for x in p.stdout.splitlines() if x.strip()]


def claim_age(remote: str, pack: str, worker: str) -> float | None:
    p = subprocess.run(
        [RCLONE, "lsl", f"{remote}/packs/{pack}/claim/{worker}"],
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


def marker_state(entries: set[str]) -> str:
    """Terminal-state check; claims are layered on by the caller."""
    markers = {e for e in entries if "/" not in e}
    if "done" in markers:
        return "done"
    if "failed" in markers:
        return "failed"
    if "retired" in markers:
        return "retired"
    return ""


def inventory(remote: str, stale_hours: float) -> dict:
    lines = rclone("lsf", f"{remote}/packs", "--recursive")
    packs: dict[str, set[str]] = {}
    for line in lines:
        parts = line.split("/", 1)
        if len(parts) == 2:
            packs.setdefault(parts[0], set()).add(parts[1])
        elif parts[0]:
            # empty pack dir (half-staged) — keep visible
            packs.setdefault(parts[0], set())

    states: Counter = Counter()
    kinds: Counter = Counter()
    detail = []
    active_claims = []
    stale_claims = []
    residual_claims = 0
    artifact_packages = 0
    for name in sorted(packs):
        entries = packs[name]
        kind = "render" if VIDEO.search(name) else "support"
        state = marker_state(entries)
        pack_claims = []
        for entry in entries:
            if entry.startswith("claim/") and entry != "claim/":
                worker = entry.removeprefix("claim/")
                row = {"worker": worker}
                age = claim_age(remote, name, worker)
                row["age_hours"] = round(age, 2) if age is not None else None
                row["stale"] = (age is None
                                or age > stale_hours)
                pack_claims.append(row)
        # Claims only matter on non-terminal packs — a claim file left
        # behind on a done/failed/retired pack is residue, not work.
        if state in ("done", "failed", "retired"):
            residual_claims += len(pack_claims)
        else:
            for row in pack_claims:
                (stale_claims if row["stale"]
                 else active_claims).append({"pack": name, **row})
            if pack_claims:
                state = ("running" if any(not c["stale"]
                                          for c in pack_claims)
                         else "stale")
        if not state:
            state = "queued"
        states[state] += 1
        kinds[kind] += 1
        markers = sorted(
            e for e in entries
            if "/" not in e and e in TERMINAL + ("fallback",))
        artifacts = sorted(
            e.split("/", 1)[0] for e in entries
            if e.startswith(("out/", "shots/", "final/"))
        )
        if artifacts or any(e.startswith("out/") for e in entries):
            artifact_packages += 1
        detail.append({
            "pack": name,
            "kind": kind,
            "state": state,
            "claims": pack_claims,
            "markers": markers,
            "artifacts": artifacts,
        })
    return {
        "remote": remote,
        "packages": len(packs),
        "kinds": dict(kinds),
        "states": dict(states),
        "active_claims": active_claims,
        "stale_claims": stale_claims,
        "residual_claims": residual_claims,
        "artifact_packages": artifact_packages,
        "pack_detail": detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--remote", action="append",
        default=[os.environ.get("KK_MAC_VIDEO_PILOT_REMOTE",
                                "gdrive:ada-nest/kk-mac-video-pilot"),
                 "gdrive:ada-nest"],
    )
    ap.add_argument("--stale-hours", type=float, default=2.0)
    args = ap.parse_args()
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "stale_hours": args.stale_hours,
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
    report["residual_claims"] = sum(
        queue["residual_claims"] for queue in report["queues"]
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
