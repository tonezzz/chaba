#!/usr/bin/env python3
"""Shared 'ready' marker contract for nest-pack staging (OPS-1002,
card devnest-capacity-aware-dispatch).

Problem: a pack staged by `rclone copy` is visible file-by-file — a
worker (or a producer retry scanning the queue) can observe a
half-staged directory and claim it, or a producer killed mid-copy can
leave a silent partial pack (observed 2026-10-31:
kk-mac-task-report-review-a8ff708e96d4, empty dir claimed by nobody,
queue accounting counted it as a pack).

Contract:
  1. Stager copies the complete pack dir, runs `rclone check --one-way`
     to prove every file landed, then writes `<pack>/ready` LAST:
       {"v": 1, "manifest_sha256": <sha256 over "relpath\\tsize" lines>,
        "files": <count>, "staged_at": <epoch>, "staged_by": <name>}
  2. Workers only claim a pack whose `ready` marker parses and whose
     manifest hash matches the pack's current remote file set. Absent
     or invalid -> the pack is not claimable on ready-required remotes.
  3. Manifest excludes worker-written/transient entries (ready, done,
     failed, claim/**, out/**) so post-claim writes never invalidate it.

The marker is deliberately content-addressed, not a timestamp: a
`rclone copy` that silently dropped files, or a later mutation of the
pack dir, invalidates the hash — not just a crashed staging run.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

READY_FILE = "ready"
MARKER_VERSION = 1

# Entries that must not participate in the manifest — anything a worker
# or a second staging pass may legitimately add/remove after `ready`.
TRANSIENT_FILES = {"ready", "done", "failed"}
TRANSIENT_PREFIXES = ("claim/", "out/")


def manifest_hash(entries: dict[str, int]) -> str:
    """sha256 over sorted "relpath\\tsize" lines for the stable file set."""
    items = [
        (rel, int(size)) for rel, size in entries.items()
        if rel not in TRANSIENT_FILES
        and not rel.startswith(TRANSIENT_PREFIXES)
    ]
    payload = "\n".join(f"{rel}\t{size}" for rel, size in sorted(items))
    return hashlib.sha256(payload.encode()).hexdigest()


def local_manifest(root: str | Path) -> dict[str, int]:
    """{relpath: size} for every file under a local pack dir."""
    root = Path(root)
    out = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = path.stat().st_size
    return out


def make_marker(entries: dict[str, int], staged_by: str) -> dict:
    return {
        "v": MARKER_VERSION,
        "manifest_sha256": manifest_hash(entries),
        "files": sum(
            1 for rel in entries
            if rel not in TRANSIENT_FILES
            and not rel.startswith(TRANSIENT_PREFIXES)),
        "staged_at": int(time.time()),
        "staged_by": staged_by,
    }


def marker_text(entries: dict[str, int], staged_by: str) -> str:
    return json.dumps(make_marker(entries, staged_by),
                      sort_keys=True) + "\n"


def parse_marker(text: str) -> dict | None:
    try:
        marker = json.loads(text or "")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict):
        return None
    if marker.get("v") != MARKER_VERSION:
        return None
    if not isinstance(marker.get("manifest_sha256"), str):
        return None
    return marker


def marker_valid(marker: dict | None,
                 remote_entries: dict[str, int]) -> tuple[bool, str]:
    """(ok, reason). remote_entries: {relpath: size} current remote set."""
    if marker is None:
        return False, "ready_marker_unparseable"
    want = marker.get("manifest_sha256")
    have = manifest_hash(remote_entries)
    if want != have:
        return False, f"manifest_mismatch:{have[:12]}!={str(want)[:12]}"
    return True, "ok"


def remote_manifest(rclone, remote_dir: str) -> dict[str, int]:
    """{relpath: size} of a remote pack dir via one `lsf --format sp`
    listing (dirs report size -1 and are dropped). `rclone` is the
    caller's callable with signature (*args, input_text=None) -> stdout."""
    entries = {}
    for line in rclone(
            "lsf", remote_dir, "--recursive", "--format", "sp"
    ).splitlines():
        if not line.strip():
            continue
        size_s, _, rel = line.partition(";")
        rel = rel.strip()
        if not rel or rel.endswith("/"):
            continue
        try:
            entries[rel] = int(size_s.strip())
        except ValueError:
            continue
    return entries


def verify_and_mark(local_dir: str | Path, remote_dir: str,
                    staged_by: str, rclone) -> dict:
    """Post-copy staging seal: `rclone check --one-way` proves every local
    file landed on the remote, then the `ready` marker — carrying a
    manifest of the REMOTE file set (extras from a prior interrupted copy
    are excluded, so retry-staging a partial dir converges instead of
    mismatching) — is written last. Returns the marker dict."""
    rclone("check", str(local_dir), remote_dir, "--one-way")
    entries = remote_manifest(rclone, remote_dir)
    marker = make_marker(entries, staged_by)
    rclone("rcat", f"{remote_dir.rstrip('/')}/{READY_FILE}",
           input_text=json.dumps(marker, sort_keys=True) + "\n")
    return marker
