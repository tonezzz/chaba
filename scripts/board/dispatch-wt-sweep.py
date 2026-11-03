#!/usr/bin/env python3
"""dispatch-wt-sweep.py — reap stale dispatch worktrees (card OPS-1036).

gc_worktree()/gc_session() remove a worktree only when its head is
provably merged — by design that NEVER reaps failed-run trees (dirty or
unmerged), so failure-heavy pilots leak ~200MB per attempt. This sweeper
is the bounded reaper for those: a dispatch worktree is removed only
when ALL hold:

  * it is older than --days (default 3) — forensic window preserved
  * no devin-task-<tid>* unit is active/activating — never reap in-flight
  * its task evidence is captured: the dispatch task dir exists and has
    events.jsonl (the full tool-call transcript — including write
    payloads, so uncommitted tree content is not lost)
  * --apply was passed (default is dry-run)

Removal uses `git worktree remove --force` — dirty trees are EXPECTED
here (a failed artifact-write leaves the agent's uncommitted write);
the evidence check above is what makes that safe. The session branch is
deleted with -D after the tree goes (unmerged by definition — the merged
case is gc_worktree's job, which runs earlier in the same lifecycle).

Usage:
  dispatch-wt-sweep.py            # dry-run report
  dispatch-wt-sweep.py --apply    # actually reap
  dispatch-wt-sweep.py --days 7 --dir ~/CascadeProjects
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def sh(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout)


def unit_active(task_id: str) -> bool:
    r = sh(["systemctl", "--user", "list-units", f"devin-task-{task_id}*",
            "--state=active,activating", "--no-legend", "--plain"],
           timeout=15)
    return bool(r.stdout.strip())


def evidence_dir(task_id: str) -> Path | None:
    d = Path.home() / ".local/share/devin-dispatch/tasks" / task_id
    if (d / "events.jsonl").is_file():
        return d
    return None


def repo_root(wt: Path) -> Path | None:
    r = sh(["git", "-C", str(wt), "rev-parse", "--git-common-dir"])
    if r.returncode != 0:
        return None
    common = Path(r.stdout.strip())
    if not common.is_absolute():
        common = (wt / common).resolve()
    # <root>/.git or a bare common dir both normalise to the repo root
    return common.parent if common.name == ".git" else common


def head_branch(wt: Path) -> str:
    r = sh(["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else ""


def sweep(base: Path, days: float, task_root: Path, apply: bool) -> int:
    now = time.time()
    cutoff = now - days * 86400
    rc = 0
    for wt in sorted(base.glob("dispatch-wt-*")):
        if not wt.is_dir():
            continue
        tid = wt.name[len("dispatch-wt-"):]
        age_h = (now - wt.stat().st_mtime) / 3600
        tag = f"{wt.name} (age {age_h:.0f}h)"

        if wt.stat().st_mtime > cutoff:
            print(f"  KEEP  {tag} — inside {days}d forensic window")
            continue
        if unit_active(tid):
            print(f"  KEEP  {tag} — devin-task-{tid}* still active")
            continue
        ev = evidence_dir(tid) if task_root is None else \
            (task_root / tid if (task_root / tid / "events.jsonl").is_file()
             else None)
        if ev is None:
            print(f"  KEEP  {tag} — no events.jsonl in task dir; "
                  f"evidence not captured, needs manual review")
            continue
        root = repo_root(wt)
        if root is None:
            print(f"  SKIP  {tag} — not a git worktree (unreadable)")
            continue
        if not apply:
            print(f"  REAP  {tag} — dry-run (evidence in {ev})")
            continue

        branch = head_branch(wt)
        r = sh(["git", "-C", str(root), "worktree", "remove", "--force",
                str(wt)], timeout=120)
        if r.returncode != 0:
            print(f"  FAIL  {tag} — {(r.stderr or r.stdout).strip()[:160]}")
            rc = 1
            continue
        line = f"  GONE  {tag}"
        if branch:
            b = sh(["git", "-C", str(root), "branch", "-D", branch],
                   timeout=30)
            line += (" + branch " + branch if b.returncode == 0
                     else f" (branch {branch} delete failed)")
        print(line)
        sh(["git", "-C", str(root), "worktree", "prune"], timeout=30)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=3.0,
                    help="forensic window in days (default 3)")
    ap.add_argument("--dir", type=Path,
                    default=Path.home() / "CascadeProjects",
                    help="directory holding dispatch-wt-* (default "
                         "~/CascadeProjects)")
    ap.add_argument("--task-root", type=Path, default=None,
                    help="override dispatch task dir root")
    ap.add_argument("--apply", action="store_true",
                    help="actually remove (default: dry-run report)")
    a = ap.parse_args()
    mode = "APPLY" if a.apply else "DRY-RUN"
    print(f"dispatch-wt-sweep [{mode}] dir={a.dir} days={a.days}")
    return sweep(a.dir, a.days, a.task_root, a.apply)


if __name__ == "__main__":
    sys.exit(main())
