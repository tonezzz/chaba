"""Shared staged-drop patch resolution for tests/ada/*.

Drops under integrations/ada-voice/ are unified diffs staged for the
ada-voice repo; each card's test applies them to a scratch copy of the
checkout (ADA_PI env or ~/CascadeProjects/ada-voice). But drops SHIP:
once a drop merges upstream its patch no longer applies forward — it
reverse-applies (or diverges, when the merged code later drifted). A
bare `git apply` therefore rots on every landed drop and red-holds
unrelated merges (observed 2026-10-16: drops 6/7/8 merged into ada-voice
while their tests still demanded forward-apply).

Resolution, per patch:

  applied/applies — `git apply` succeeds: drop still pending upstream;
                    the scratch file carries the staged change.
  merged          — `git apply -R --check` succeeds: the exact diff is
                    already in the checkout (repo-of-record copy); the
                    test exercises the live file as-is.
  diverged        — neither direction applies. If any sibling patch in
                    the drop merged, this is post-merge drift (warn +
                    test live); if none did, the pending drop's base
                    rotted and apply-guards should fail (re-dispatch).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def apply_patch(patch: Path, cwd) -> str:
    """Apply `patch` in `cwd` if it still goes on forward; return the
    tri-state. 'merged'/'diverged' leave the tree untouched — the live
    file is what's tested."""
    r = subprocess.run(["git", "apply", "--check", str(patch)],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run(["git", "apply", str(patch)], cwd=cwd, check=True)
        return "applied"
    if subprocess.run(["git", "apply", "-R", "--check", str(patch)],
                      cwd=cwd, capture_output=True).returncode == 0:
        return "merged"
    print(f"  warn: {Path(patch).name} diverged from ada-voice — "
          "testing the live file", file=sys.stderr)
    return "diverged"


def check_patch(patch: Path, cwd) -> str:
    """Same tri-state, read-only: 'applies' | 'merged' | 'diverged'."""
    if subprocess.run(["git", "apply", "--check", str(patch)],
                      cwd=cwd, capture_output=True).returncode == 0:
        return "applies"
    if subprocess.run(["git", "apply", "-R", "--check", str(patch)],
                      cwd=cwd, capture_output=True).returncode == 0:
        return "merged"
    return "diverged"


def drop_guard_ok(states) -> bool:
    """Verdict for one drop's set of patch states: fail only when a
    patch diverged AND nothing in the drop merged — i.e. a pending drop
    whose base rotted. All-applied = healthy pending drop; any 'merged'
    = the drop shipped, residual divergence is post-merge drift."""
    return "diverged" not in states or "merged" in states
