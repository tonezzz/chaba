#!/usr/bin/env python3
"""Prune devin-dispatch sessions from sessions.db (housekeeping job).

Scope is deliberately narrow: only dispatch-era sessions older than N days
(default 14). Interactive sessions are never pruned. A dispatch session is
identified by:

  * title starting with the devin-dispatch preamble
    ("You are running unattended via devin-dispatch" / the resume variant), or
  * working_directory inside a dispatch-wt-<task_id> worktree that has a
    matching ~/.local/share/devin-dispatch/tasks/<task_id>/ dir, or
  * session id matching the `resume/<sid>` branch recorded in a resume task's
    meta.json.

Keep guards (a candidate is retained when any holds):
  * tasks/<id>/needs-input.txt exists (operator question pending),
  * a live session lock (session_locks/<sid>.lock with a live pid),
  * the dispatch worktree still exists and is dirty, has commits not merged
    into the repo base branch, or its git state cannot be resolved,
  * the worktree is gone but the recorded dispatch branch still holds commits
    not reachable from the repo base.

After deletes, the existing guarded vacuum is run — but only after the
devin-vacuum-when-closed.sh two-clear-checks logic passes (no
'devin-desktop|devin acp' process AND no fuser on sessions.db, twice
consecutively). When Devin keeps the DB open the vacuum is skipped; the next
run picks it up.

Every pruned session id+title is appended to ~/var/chaba/reports/timeline.jsonl
via scripts/lib/report.py so the cleanup is auditable.

Usage:
  session-prune.py [--days N] [--dry-run] [--db PATH] [--tasks-dir DIR]
                   [--no-vacuum] [--vacuum-wait SECONDS] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from lib.report import append_timeline  # noqa: E402

HOME = Path.home()
DEFAULT_DB = HOME / ".local/share/devin/cli/sessions.db"
DEFAULT_TASKS = HOME / ".local/share/devin-dispatch/tasks"
REPOS_CONF = HOME / ".local/share/devin-dispatch/repos.conf"
LOCK_DIR = HOME / ".local/share/devin/cli/session_locks"
WATCHDOG_FLAG = HOME / ".config/devin/watchdog-autorestart"
NODE = "devin-session-prune"
LAYER = "L1-producer"

DISPATCH_PREFIXES = (
    "You are running unattended via devin-dispatch",
    "You are resuming a session via devin-dispatch",
)
WT_RE = re.compile(r"^dispatch-wt-(.+)$")
# Child tables keyed by session_id; delete before the sessions row.
CHILD_TABLES = (
    "prompt_history", "message_nodes", "tool_call_state",
    "rendered_commits", "subagent_heads",
)
BASE_CANDIDATES = ("master", "main", "origin/master", "origin/main")


def run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True,
                              timeout=timeout, errors="replace")
    except Exception as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load_tasks(tasks_dir: Path) -> dict:
    """task_id -> {meta, dir, meta_error} for every dispatch task dir."""
    tasks = {}
    if not tasks_dir.is_dir():
        return tasks
    for d in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
        meta, err = {}, ""
        try:
            meta = json.loads((d / "meta.json").read_text())
        except Exception as exc:
            err = str(exc)
        tasks[d.name] = {"meta": meta, "dir": d, "meta_error": err}
    return tasks


def load_repos() -> dict:
    """repo name -> checkout path from devin-dispatch repos.conf."""
    repos = {}
    try:
        for line in REPOS_CONF.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] and not parts[0].startswith("#"):
                repos[parts[0]] = Path(parts[1])
    except OSError:
        pass
    return repos


def classify(row: dict, tasks: dict, resume_sids: dict) -> tuple[str | None, str | None]:
    """Return (task_id, via) when the session is dispatch-era, else (None, None)."""
    title = row.get("title") or ""
    if title.startswith(DISPATCH_PREFIXES):
        m = WT_RE.match(Path(row.get("cwd") or "").name)
        tid = m.group(1) if m and m.group(1) in tasks else None
        return tid, "title-prefix"
    m = WT_RE.match(Path(row.get("cwd") or "").name)
    if m and m.group(1) in tasks:
        return m.group(1), "dispatch-worktree"
    if row["id"] in resume_sids:
        return resume_sids[row["id"]], "resume-task"
    return None, None


def session_lock_active(session_id: str) -> bool:
    lock = LOCK_DIR / f"{session_id}.lock"
    try:
        pid = int(lock.read_text(errors="replace").strip())
    except Exception:
        return False
    return pid_alive(pid)


def worktree_branch(wt: Path, meta_branch: str) -> str:
    """Ref to ancestry-check: recorded dispatch branch first, then HEAD."""
    if meta_branch:
        p = run(["git", "-C", str(wt), "rev-parse", "--verify",
                 f"refs/heads/{meta_branch}"], timeout=10)
        if p.returncode == 0:
            return meta_branch
    p = run(["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
    head = p.stdout.strip()
    if p.returncode == 0 and head and head != "HEAD":
        return head
    return ""


def base_ref(repo_path: Path) -> str:
    for cand in BASE_CANDIDATES:
        if run(["git", "-C", str(repo_path), "rev-parse", "--verify", cand],
               timeout=10).returncode == 0:
            return cand
    return ""


def unmerged_count(repo_path: Path, ref: str) -> tuple[int | None, str]:
    """Commits on ref not reachable from base. (count, base) or (None, error)."""
    if not ref:
        return None, "no branch resolved"
    base = base_ref(repo_path)
    if not base:
        return None, "no base ref found"
    p = run(["git", "-C", str(repo_path), "rev-list", "--count",
             f"{base}..{ref}"], timeout=15)
    if p.returncode != 0:
        return None, (p.stderr or p.stdout).strip() or "rev-list failed"
    try:
        return int(p.stdout.strip()), base
    except ValueError:
        return None, "rev-list unparsable"


def keep_reason(row: dict, task_id: str | None, tasks: dict, repos: dict) -> str | None:
    """None = safe to prune; otherwise the guard that fired."""
    sid = row["id"]
    if session_lock_active(sid):
        return "active-lock"

    task = tasks.get(task_id) if task_id else None
    meta = (task or {}).get("meta") or {}
    if task and task.get("meta_error"):
        return "task-meta-unreadable"
    if task and (task["dir"] / "needs-input.txt").is_file():
        return "needs-input"

    is_resume = task_id is not None and str(meta.get("branch", "")).startswith("resume/")
    cwd = Path(row.get("cwd") or "")
    wt = Path(meta.get("worktree") or (cwd if WT_RE.match(cwd.name) else "")) \
        if (meta.get("worktree") or WT_RE.match(cwd.name)) else None

    if is_resume or (wt is not None and not WT_RE.match(wt.name)):
        # Resume tasks borrow an arbitrary cwd — never a dispatch worktree;
        # only needs-input/lock guards above apply.
        return None

    if wt is not None and wt.is_dir():
        p = run(["git", "-C", str(wt), "status", "--porcelain=v1"], timeout=15)
        if p.returncode != 0:
            return "worktree-git-unknown"
        if p.stdout.strip():
            return "worktree-dirty"
        ref = worktree_branch(wt, meta.get("branch") or "")
        n, base_or_err = unmerged_count(wt, ref)
        if n is None:
            return f"worktree-unresolved:{base_or_err}"
        if n > 0:
            return f"worktree-unmerged:{n}-not-in-{base_or_err}"
        return None

    # Worktree gone — fall back to the recorded branch in the source repo.
    repo = repos.get(meta.get("repo") or "")
    branch = meta.get("branch") or ""
    if repo and branch and repo.is_dir():
        n, base_or_err = unmerged_count(repo, branch)
        if n is None:
            if run(["git", "-C", str(repo), "rev-parse", "--verify",
                    f"refs/heads/{branch}"], timeout=10).returncode == 0:
                return f"branch-unresolved:{base_or_err}"
            return None  # branch dropped — nothing to preserve
        if n > 0:
            return f"branch-unmerged:{n}-not-in-{base_or_err}"
        return None

    if task is None:
        # Title-prefix-only match, task meta gone. If we located a dispatch
        # worktree it is also gone by now (wt.is_dir() was False above), so
        # nothing is left to protect. If no worktree was ever found (e.g. a
        # resume-era cwd) keep the row — can't prove the work landed.
        return None if wt is not None else "unverifiable-no-task-meta"
    return None


def quick_check(db: Path) -> str:
    """quick_check the DB.

    sessions.db is GBs on a busy HDD here — a live check takes many minutes.
    Snapshot via the sqlite backup API into tmpfs (consistent under WAL
    writers) and check that instead; identical corruption coverage at a
    fraction of the wall-clock cost. Falls back to a live check when the
    snapshot cannot be made (e.g. tmpfs too small).
    """
    import tempfile
    snap = Path(tempfile.mkdtemp(prefix="session-prune-")) / "snap.db"
    try:
        src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        dst = sqlite3.connect(str(snap))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    except Exception:
        snap = db  # fall back to checking the live file
    try:
        conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
            return "ok" if rows and rows[0][0] == "ok" else \
                "; ".join(str(r[0]) for r in rows[:10])
        finally:
            conn.close()
    finally:
        if snap != db:
            try:
                snap.unlink()
                snap.parent.rmdir()
            except OSError:
                pass


def delete_sessions(db: Path, ids: list[str]) -> None:
    conn = sqlite3.connect(str(db))
    try:
        with conn:
            for table in CHILD_TABLES:
                conn.execute(
                    f"DELETE FROM {table} WHERE session_id IN "
                    f"({','.join('?' * len(ids))})", ids)
            conn.execute(
                f"DELETE FROM sessions WHERE id IN ({','.join('?' * len(ids))})",
                ids)
    finally:
        conn.close()


def db_clear(db: Path) -> bool:
    """One clear check: no devin-desktop/acp process and no fuser on the DB."""
    if run(["pgrep", "-f", r"devin-desktop|devin acp"], timeout=10).stdout.strip():
        return False
    return not run(["fuser", str(db)], timeout=10).stdout.strip()


def wait_for_clear(db: Path, timeout_s: int, interval: int = 15,
                   needed: int = 2) -> bool:
    """devin-vacuum-when-closed.sh logic: `needed` consecutive clear checks."""
    deadline = time.monotonic() + timeout_s
    clear = 0
    while time.monotonic() < deadline:
        if db_clear(db):
            clear += 1
            if clear >= needed:
                return True
        else:
            clear = 0
        time.sleep(interval)
    return False


def find_vacuum() -> Path | None:
    for cand in (REPO / "scripts/devin/session/vacuum-devin-db.sh",
                 HOME / ".config/devin/scripts/vacuum-devin-db.sh"):
        if cand.is_file():
            return cand
    return None


def guarded_vacuum(db: Path, wait_s: int, vacuum: Path | None) -> dict:
    if vacuum is None:
        return {"ran": False, "reason": "vacuum script not found"}
    if not os.access(vacuum, os.X_OK):
        return {"ran": False, "reason": f"{vacuum} not executable"}
    if not wait_for_clear(db, wait_s):
        return {"ran": False, "reason": "devin/db still open after wait — skipped"}

    # Keep the watchdog from relaunching devin-desktop mid-vacuum; same
    # flag-rename dance as devin-vacuum-when-closed.sh.
    moved = None
    if WATCHDOG_FLAG.exists():
        moved = WATCHDOG_FLAG.with_name(
            f"{WATCHDOG_FLAG.name}.session-prune-disabled.{os.getpid()}")
        try:
            WATCHDOG_FLAG.rename(moved)
        except OSError:
            moved = None
    try:
        p = run(["bash", str(vacuum)], timeout=1800)
        tail = (p.stdout or "").strip().splitlines()[-5:]
        return {"ran": True, "rc": p.returncode,
                "output_tail": tail, "stderr": (p.stderr or "")[-500:]}
    finally:
        if moved is not None and moved.exists():
            try:
                moved.rename(WATCHDOG_FLAG)
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=14,
                    help="retention window; dispatch sessions older than this are candidates")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be pruned; no deletes, no vacuum, no timeline writes")
    ap.add_argument("--no-vacuum", action="store_true")
    ap.add_argument("--vacuum-wait", type=int, default=90,
                    help="max seconds to wait for two clear checks before skipping vacuum")
    ap.add_argument("--vacuum-script", type=Path, default=None)
    ap.add_argument("--skip-check", action="store_true",
                    help="bypass the pre-prune quick_check (not recommended)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    db = args.db.expanduser()
    if not db.is_file():
        print(f"error: {db} not found", file=sys.stderr)
        return 2

    qc = "skipped" if args.skip_check else quick_check(db)
    if qc != "ok":
        # A malformed DB must go through the documented .recover rebuild —
        # never prune it in place (2026-09-12 tony-omen lesson).
        print(f"error: quick_check failed: {qc}", file=sys.stderr)
        return 2

    cutoff = int(time.time()) - args.days * 86400
    tasks = load_tasks(args.tasks_dir.expanduser())
    resume_sids = {
        t["meta"]["branch"][len("resume/"):]: tid
        for tid, t in tasks.items()
        if str(t["meta"].get("branch", "")).startswith("resume/")
    }
    repos = load_repos()

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = [
            {"id": r[0], "title": r[1] or "", "last_activity_at": r[2],
             "cwd": r[3] or ""}
            for r in conn.execute(
                "SELECT id, title, last_activity_at, working_directory "
                "FROM sessions WHERE last_activity_at < ? "
                "ORDER BY last_activity_at ASC", (cutoff,))
        ]
    finally:
        conn.close()

    prune, keep = [], []
    for row in rows:
        task_id, via = classify(row, tasks, resume_sids)
        if via is None:
            continue  # interactive / non-dispatch — out of scope entirely
        reason = keep_reason(row, task_id, tasks, repos)
        rec = {**row, "task_id": task_id, "via": via}
        (keep if reason else prune).append({**rec, "reason": reason} if reason
                                           else rec)

    result = {"dry_run": args.dry_run, "days": args.days, "cutoff": cutoff,
              "old_sessions": len(rows), "dispatch_candidates": len(prune) + len(keep),
              "pruned": [], "kept": keep, "vacuum": {"ran": False, "reason": "not attempted"}}

    if args.dry_run:
        result["pruned"] = [{**r, "would_prune": True} for r in prune]
    else:
        log_ok = db == DEFAULT_DB  # don't record audit events for test copies
        for r in prune:
            try:
                delete_sessions(db, [r["id"]])
                result["pruned"].append(r)
                if log_ok:
                    append_timeline(NODE, LAYER, "ok",
                                    f"pruned dispatch session {r['id']} — "
                                    f"{(r['title'] or 'untitled')[:120]}")
            except Exception as exc:
                result.setdefault("errors", []).append(f"{r['id']}: {exc}")

        if not args.no_vacuum:
            result["vacuum"] = guarded_vacuum(
                db, args.vacuum_wait, args.vacuum_script or find_vacuum())

        status = "error" if result.get("errors") else "ok"
        if log_ok:
            vac = result["vacuum"]
            vac_s = f"ran rc={vac.get('rc')}" if vac.get("ran") else "skipped"
            append_timeline(
                NODE, LAYER, status,
                f"run complete: {len(result['pruned'])} pruned, {len(keep)} "
                f"kept, {len(rows)} sessions older than {args.days}d scanned; "
                f"vacuum={vac_s}")

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        mode = "DRY-RUN " if args.dry_run else ""
        print(f"{mode}scanned {len(rows)} sessions older than {args.days}d; "
              f"{len(prune) + len(keep)} dispatch-era")
        for r in (result["pruned"] if args.dry_run else prune):
            tag = "would-prune" if args.dry_run else "pruned"
            print(f"  {tag:12} {r['id']:24} {r['via']:18} "
              f"{time.strftime('%Y-%m-%d', time.localtime(r['last_activity_at']))} "
              f"{(r['title'] or 'untitled')[:70]}")
        for r in keep:
            print(f"  {'keep':12} {r['id']:24} {r['via']:18} "
              f"{time.strftime('%Y-%m-%d', time.localtime(r['last_activity_at']))} "
              f"{r['reason']}  {(r['title'] or 'untitled')[:50]}")
        v = result["vacuum"]
        print(f"vacuum: {'ran rc=' + str(v.get('rc')) if v.get('ran') else 'skipped (' + v.get('reason', '') + ')'}")
        for line in v.get("output_tail") or []:
            print(f"  {line}")
        for e in result.get("errors", []):
            print(f"  error: {e}")
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
