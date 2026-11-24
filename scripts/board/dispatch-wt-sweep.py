#!/usr/bin/env python3
"""dispatch-wt-sweep.py — reap stale dispatch worktrees (card OPS-1036).

gc_worktree()/gc_session() remove a worktree only when its head is
provably merged — by design that NEVER reaps failed-run trees (dirty or
unmerged), so failure-heavy pilots leak ~200MB per attempt. This sweeper
is the bounded reaper for those: a dispatch worktree is removed only
when ALL hold:

  * it is older than --days (default 3) — forensic window preserved
  * no devin-task-<tid>* unit is active/activating — never reap in-flight
    (systemd --user on Linux, launchd gui/<uid> jobs on darwin — the
    same task-unit names runner-agent registers on each runtime)
  * its task evidence is captured: the dispatch task dir exists with
    any durable run record — meta.json (every executor), events.jsonl
    (opencode transcript — including write payloads, so uncommitted
    tree content is not lost), usage.json, verdict.json, or exit_code
  * --apply was passed (default is dry-run)

Removal uses `git worktree remove --force` — dirty trees are EXPECTED
here (a failed artifact-write leaves the agent's uncommitted write);
the evidence check above is what makes that safe. The session branch is
deleted with -D after the tree goes (unmerged by definition — the merged
case is gc_worktree's job, which runs earlier in the same lifecycle).

Salvage-before-reap (card dispatch-runner-resilience): the evidence dir
preserves the transcript, not git history — a failed run's COMMITTED
work sits only on the local dispatch branch, and -D deletes it forever.
Before reaping, the worktree head is checked against origin
(remote-tracking refs after a fresh fetch — one fetch per repo root
per run): commits already on origin reap as before; anything else is
pushed to a recoverable `wip/dispatch/<task-id>` ref first and the
pushed ref is logged to the card's comms. When origin can't be reached
or the push fails, the tree is KEPT — an unproven head is never
silently lost.

Scheduled path (card OPS-1036): runner-agent's wt_sweep_pass invokes
sweep(..., apply=True) once per RUNNER_WT_SWEEP_S (default 24h) on every
runner host — no separate unit needed, the pass rides the already-
declared runner-agent.timer/LaunchAgent. DISPATCH_WT_SWEEP=0 disables.

Usage:
  dispatch-wt-sweep.py            # dry-run report
  dispatch-wt-sweep.py --apply    # actually reap
  dispatch-wt-sweep.py --days 7 --dir ~/CascadeProjects
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Any one of these in the task dir proves the dispatch machinery ran and
# left durable records — the card's named set (events.jsonl, usage.json,
# verdict.json) plus the legacy/meta equivalents.
EVIDENCE_FILES = ("meta.json", "events.jsonl", "usage.json",
                  "verdict.json", "exit_code")


def sh(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout)


def _launchd_active(task_id: str) -> bool:
    """macOS twin of the systemctl probe — conservative by design.

    runner-agent registers task jobs as gui/<uid>/devin-task-<tid>
    (plus -fuN followups) launchd jobs bootstrapped from plists under
    RUNNER_STATE/launchd/ (~/.local/share/runner-agent/launchd/). A job
    counts as live while `launchctl print` shows a pid or
    state=running — the same predicate runner-agent._launchd_active
    uses. No launchctl -> we cannot prove in-flight safety -> True
    (keep), matching the sweeper's keep-on-doubt rule."""
    if shutil.which("launchctl") is None:
        return True
    base = f"devin-task-{task_id}"
    cands = {base}
    ldir = Path.home() / ".local/share/runner-agent/launchd"
    try:
        for p in ldir.glob(f"{base}*.plist"):
            name = p.name[:-len(".plist")]
            if name == base or re.fullmatch(
                    re.escape(base) + r"-fu\d+", name):
                cands.add(name)
    except OSError:
        pass
    for unit in sorted(cands):
        r = sh(["launchctl", "print", f"gui/{os.getuid()}/{unit}"],
               timeout=15)
        if r.returncode != 0:
            continue
        out = r.stdout or ""
        m = re.search(r"(?m)^\s*pid\s*=\s*(\d+)", out)
        if m and int(m.group(1)) > 0:
            return True
        m = re.search(r"(?m)^\s*state\s*=\s*(\S+)", out)
        if m and m.group(1) == "running":
            return True
    return False


def unit_active(task_id: str) -> bool:
    if sys.platform == "darwin":
        return _launchd_active(task_id)
    r = sh(["systemctl", "--user", "list-units", f"devin-task-{task_id}*",
            "--state=active,activating", "--no-legend", "--plain"],
           timeout=15)
    return bool(r.stdout.strip())


def evidence_dir(task_id: str) -> Path | None:
    d = Path.home() / ".local/share/devin-dispatch/tasks" / task_id
    if any((d / f).is_file() for f in EVIDENCE_FILES):
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
    out = r.stdout.strip() if r.returncode == 0 else ""
    return "" if out == "HEAD" else out  # detached tree — no branch


def head_sha(wt: Path) -> str:
    r = sh(["git", "-C", str(wt), "rev-parse", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else ""


def on_origin(root: Path, sha: str, fetched: set | None = None) -> bool:
    """Every commit at sha reachable from an origin remote-tracking ref.
    Fetch first so the view is fresh; a failed fetch still leaves the
    last-fetched refs, which are proof enough — a commit that WAS on
    origin is still there (wip/base refs are never force-rewound).
    `fetched` (when given) dedupes the fetch across worktrees sharing
    one repo root — a failed fetch is recorded too, so a dead origin
    costs one timeout per repo, not one per tree."""
    if fetched is None or root not in fetched:
        sh(["git", "-C", str(root), "fetch", "-q", "--prune", "origin"],
           timeout=90)
        if fetched is not None:
            fetched.add(root)
    r = sh(["git", "-C", str(root), "branch", "-r", "--contains", sha])
    return any(ln.strip().startswith("origin/")
               for ln in r.stdout.splitlines())


def salvage_ref(tid: str) -> str:
    return f"refs/heads/wip/dispatch/{tid}"


def salvage_push(root: Path, sha: str, tid: str) -> str:
    """Push the doomed head to the wip/ salvage namespace on origin —
    returns the pushed ref, '' when origin refused/unreachable. The
    forced update is safe: the namespace is salvage-only and the worst
    case rewrites an older salvage of the same task."""
    ref = salvage_ref(tid)
    r = sh(["git", "-C", str(root), "push", "-q", "origin",
            f"+{sha}:{ref}"], timeout=120)
    return ref if r.returncode == 0 else ""


def card_for_task(task_root: Path | None, tid: str) -> str:
    d = task_root or (Path.home()
                      / ".local/share/devin-dispatch/tasks")
    try:
        meta = json.loads((d / tid / "meta.json").read_text())
        return str(meta.get("card") or "")
    except Exception:
        return ""


def note_salvage(cid: str, text: str) -> None:
    """Best-effort card comms for a salvage push — a dead api never
    blocks the reap."""
    if not cid:
        return
    api = os.environ.get(
        "BOARD_API",
        os.environ.get(
            "RUNNER_API",
            "https://idc03.taila0626a.ts.net:10000")).rstrip("/")
    try:
        req = urllib.request.Request(
            f"{api}/comment",
            data=json.dumps({"id": cid, "from": "chaba",
                             "text": text[:500]}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def sweep(base: Path, days: float, task_root: Path, apply: bool) -> int:
    if os.environ.get("DISPATCH_WT_SWEEP", "1") == "0":
        print("dispatch-wt-sweep disabled: DISPATCH_WT_SWEEP=0")
        return 0
    now = time.time()
    cutoff = now - days * 86400
    rc = 0
    fetched: set = set()
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
            (task_root / tid
             if any((task_root / tid / f).is_file()
                    for f in EVIDENCE_FILES)
             else None)
        if ev is None:
            print(f"  KEEP  {tag} — no task evidence ({'/'.join(EVIDENCE_FILES)}); "
                  f"evidence not captured, needs manual review")
            continue
        root = repo_root(wt)
        if root is None:
            print(f"  SKIP  {tag} — not a git worktree (unreadable)")
            continue
        # Salvage gate (dispatch-runner-resilience): committed-but-
        # unpushed work must land on origin before the -D delete below
        # can take it. unpushed=None means 'can't even read HEAD' — the
        # same non-git case the old code reaped blindly; keep it.
        sha = head_sha(wt)
        unpushed = None if not sha else not on_origin(root, sha, fetched)
        if unpushed is None:
            print(f"  KEEP  {tag} — HEAD unreadable; not reaping blind")
            continue
        if not apply:
            print(f"  REAP  {tag} — dry-run (evidence in {ev})"
                  + (f"; would salvage-push {sha[:8]} to "
                     f"{salvage_ref(tid)}" if unpushed else ""))
            continue
        if unpushed:
            ref = salvage_push(root, sha, tid)
            if not ref:
                print(f"  KEEP  {tag} — head {sha[:8]} not on origin "
                      "and salvage push failed (origin unreachable?)")
                continue
            note = (f"dispatch-wt-sweep salvaged unpushed commits "
                    f"before reap: {wt.name} head {sha[:8]} → "
                    f"origin {ref}")
            print(f"  PUSH  {tag} — {note}")
            note_salvage(card_for_task(task_root, tid), note)

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
