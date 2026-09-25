#!/usr/bin/env python3
"""Devin pre-cleanup evidence check.

Read-only preflight for docs/ssot/infrastructure/ssot.devin.maintenance.yml.
Captures the baseline, integrity, locks/writers, archive preservation, dispatch
state, and the dry-run list of sessions older than the host retention cutoff.
Writes a Markdown report under ~/.local/share/devin/cleanup-reports/.

Usage:
  devin-precleanup-check.py [--retention-days N] [--db PATH] [--report-dir DIR]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

HOME = Path.home()
DEFAULT_DB = HOME / ".local/share/devin/cli/sessions.db"
DEFAULT_REPORT_DIR = HOME / ".local/share/devin/cleanup-reports"
DISPATCH_TASKS = HOME / ".local/share/devin-dispatch/tasks"
WORKTREE_GLOB = str(HOME / "CascadeProjects/dispatch-wt-*")
RETENTION_BY_HOST = {"tony-dell": 7, "tony-omen": 3}
BACKUP_FREE_MULTIPLIER = 2


def run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            errors="replace",
        )
    except Exception as exc:  # missing binary, timeout, bus failure
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def fmt_bytes(n: int | None) -> str:
    if n is None:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n)
    for unit in units:
        if v < 1024 or unit == units[-1]:
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{n} B"


def iso(ts: int | float | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds")


def md_escape(value: object, limit: int = 100) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|")


def md_table(headers: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def pid_info(pid: int) -> dict:
    info = {"pid": pid, "alive": False, "cmd": ""}
    try:
        os.kill(pid, 0)
        info["alive"] = True
    except ProcessLookupError:
        return info
    except PermissionError:
        info["alive"] = True
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        info["cmd"] = re.sub(r"\s+", " ", raw.replace(b"\0", b" ").decode("utf-8", "replace")).strip()
    except Exception:
        pass
    return info


def pid_label(info: dict) -> str:
    pid = info.get("pid")
    if not pid:
        return "malformed"
    if not info.get("alive"):
        return f"stale pid {pid}"
    cmd = info.get("cmd") or ""
    kind = "devin" if "devin" in cmd.lower() else "other-process"
    return f"active pid {pid} ({kind})"


def read_locks(lock_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    active, stale, malformed = [], [], []
    for path in sorted(lock_dir.glob("*.lock")):
        session = path.stem
        try:
            pid = int(path.read_text(errors="replace").strip())
        except Exception:
            malformed.append({"session": session, "path": str(path), "pid": None, "alive": False, "cmd": ""})
            continue
        info = pid_info(pid)
        rec = {"session": session, "path": str(path), **info}
        (active if info["alive"] else stale).append(rec)
    return active, stale, malformed


def fuser_pids(db: Path) -> list[dict]:
    proc = run(["fuser", str(db)], timeout=10)
    pids = [int(x) for x in re.findall(r"\b\d+\b", proc.stdout + " " + proc.stderr)]
    return [pid_info(pid) for pid in sorted(set(pids))]


def devin_processes() -> list[str]:
    proc = run(["pgrep", "-af", r"devin-desktop|devin acp"], timeout=10)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def code_lock() -> dict:
    path = HOME / ".config/Devin/code.lock"
    rec = {"path": str(path), "exists": path.exists(), "pid": None, "alive": False, "cmd": ""}
    if not path.exists():
        return rec
    try:
        rec["pid"] = int(path.read_text(errors="replace").strip())
        rec.update(pid_info(rec["pid"]))
    except Exception:
        pass
    return rec


def unit_state(unit: str) -> dict:
    proc = run([
        "systemctl", "--user", "show", unit,
        "-p", "ActiveState", "-p", "UnitFileState", "-p", "NextElapseUSecRealtime",
    ], timeout=10)
    state = {"unit": unit, "available": proc.returncode == 0}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            state[k] = v
    if proc.returncode != 0:
        state["error"] = (proc.stderr or proc.stdout).strip()
    return state


def dispatch_units() -> tuple[list[str], str | None]:
    proc = run([
        "systemctl", "--user", "list-units", "--state=active,activating",
        "--no-legend", "devin-task-*",
    ], timeout=10)
    if proc.returncode != 0:
        return [], (proc.stderr or proc.stdout).strip()
    units = []
    for line in proc.stdout.splitlines():
        cols = line.split()
        if cols:
            units.append(cols[0].removesuffix(".service"))
    return units, None


def dispatch_tasks(active_units: list[str]) -> list[dict]:
    tasks = []
    if not DISPATCH_TASKS.is_dir():
        return tasks
    for task_dir in sorted(p for p in DISPATCH_TASKS.iterdir() if p.is_dir()):
        meta_path = task_dir / "meta.json"
        meta = {}
        meta_error = ""
        try:
            meta = json.loads(meta_path.read_text())
        except Exception as exc:
            meta_error = str(exc)
        task_id = task_dir.name
        exit_code = ""
        try:
            exit_code = (task_dir / "exit_code").read_text(errors="replace").strip()
        except Exception:
            pass
        units = [u for u in active_units if u == f"devin-task-{task_id}" or u.startswith(f"devin-task-{task_id}-fu")]
        transcript = task_dir / "transcript.json"
        result = meta.get("result") or ""
        if units:
            state = "active"
        elif exit_code:
            state = "success" if exit_code == "0" else f"exit-{exit_code}"
        elif result:
            state = str(result)
        elif transcript.exists():
            state = "unknown-transcript-only"
        else:
            state = "pending-or-missing-output"
        tasks.append({
            "id": task_id,
            "state": state,
            "active_units": units,
            "repo": meta.get("repo", ""),
            "worktree": meta.get("worktree", ""),
            "branch": meta.get("branch", ""),
            "exit_code": exit_code,
            "result": result,
            "transcript": transcript.exists(),
            "transcript_size": transcript.stat().st_size if transcript.exists() else 0,
            "fu_count": len(list(task_dir.glob("fu-*.txt"))),
            "meta_error": meta_error,
        })
    return tasks


def worktrees(tasks: list[dict]) -> list[dict]:
    by_path = {t.get("worktree"): t for t in tasks if t.get("worktree")}
    rows = []
    for wt in sorted(Path(p) for p in glob.glob(WORKTREE_GLOB)):
        task = by_path.get(str(wt))
        proc = run(["git", "-C", str(wt), "status", "--porcelain=v1"], timeout=15)
        if proc.returncode != 0:
            status = "unknown"
            detail = (proc.stderr or proc.stdout).strip()
        else:
            status = "dirty" if proc.stdout.strip() else "clean"
            detail = ""
        rows.append({
            "path": str(wt),
            "task": task["id"] if task else "unregistered",
            "task_state": task["state"] if task else "unknown",
            "git": status,
            "detail": detail,
        })
    return rows


def preservation_for(session_id: str) -> dict:
    candidates = [
        HOME / ".local/share/devin/summaries" / f"{session_id}.md",
        HOME / ".local/share/devin/cli/summaries" / f"history_{session_id}.md",
    ]
    globs = [
        str(HOME / ".local/share/devin/notebook-summaries" / f"{session_id}--*.md"),
        str(HOME / ".local/share/devin/notebook-summaries/raw" / f"{session_id}--*.md"),
        str(HOME / ".local/share/devin/notebook-summaries/compactions" / f"{session_id}-*.md"),
    ]
    found = []
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                found.append(str(path))
        except OSError:
            pass
    for pattern in globs:
        for name in glob.glob(pattern):
            try:
                if Path(name).is_file() and Path(name).stat().st_size > 0:
                    found.append(name)
            except OSError:
                pass
    return {"preserved": bool(found), "files": sorted(set(found))}


def db_report(db: Path, cutoff: int, include_hidden: bool, largest_limit: int, candidate_limit: int) -> dict:
    out = {"ok": False, "error": "", "quick_check": "not-run", "session_count": None,
           "hidden_count": None, "candidates": [], "candidate_count": 0,
           "largest": []}
    if not db.exists():
        out["error"] = f"missing DB: {db}"
        return out
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception as exc:
        out["error"] = f"open failed: {exc}"
        return out
    try:
        rows = conn.execute("PRAGMA quick_check").fetchall()
        out["quick_check"] = "ok" if rows and rows[0][0] == "ok" else "; ".join(str(r[0]) for r in rows[:10])
        if out["quick_check"] != "ok":
            out["error"] = "quick_check failed; do not prune in place"
            return out
        where = "last_activity_at < ?" + ("" if include_hidden else " AND hidden=0")
        out["session_count"] = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        out["hidden_count"] = conn.execute("SELECT COUNT(*) FROM sessions WHERE hidden != 0").fetchone()[0]
        out["candidate_count"] = conn.execute(
            f"SELECT COUNT(*) FROM sessions WHERE {where}", (cutoff,)
        ).fetchone()[0]
        out["candidates"] = [
            {"id": r[0], "title": r[1] or "", "last_activity_at": r[2], "hidden": r[3]}
            for r in conn.execute(
                f"SELECT id, title, last_activity_at, hidden FROM sessions WHERE {where} "
                "ORDER BY last_activity_at ASC LIMIT ?",
                (cutoff, candidate_limit),
            )
        ]
        out["largest"] = [
            {"session_id": r[0], "title": r[1] or "", "messages": r[2], "total_mb": r[3]}
            for r in conn.execute(
                "SELECT m.session_id, s.title, COUNT(*), "
                "ROUND(SUM(LENGTH(COALESCE(m.chat_message, ''))) / 1048576.0, 1) "
                "FROM message_nodes m JOIN sessions s ON m.session_id = s.id "
                "GROUP BY m.session_id ORDER BY 4 DESC LIMIT ?",
                (largest_limit,),
            )
        ]
        out["ok"] = True
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--retention-days", type=int, default=None)
    ap.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    ap.add_argument("--candidate-limit", type=int, default=500,
                    help="max dry-run rows to write to the report (count remains exact)")
    ap.add_argument("--largest-limit", type=int, default=10)
    ap.add_argument("--visible-only", action="store_true",
                    help="restrict the dry-run list to hidden=0; default matches prune-devin-sessions.sh and includes all sessions")
    ap.add_argument("--skip-integrity", action="store_true",
                    help="record the check as skipped; marks the run not ready for delete")
    ap.add_argument("--json", action="store_true", help="print machine-readable summary")
    args = ap.parse_args()

    host = socket.gethostname().split(".")[0]
    retention = args.retention_days if args.retention_days is not None else RETENTION_BY_HOST.get(host, 3)
    now = int(time.time())
    cutoff = now - retention * 86400
    db = args.db.expanduser()
    report_dir = args.report_dir.expanduser()
    generated = datetime.now().astimezone()

    disk = shutil.disk_usage(db.parent if db.parent.exists() else HOME)
    sizes = {suffix: (db.with_name(db.name + suffix).stat().st_size
                      if db.with_name(db.name + suffix).exists() else 0)
             for suffix in ("", "-wal", "-shm")}
    db_footprint = sum(sizes.values())

    if args.skip_integrity:
        data = {"ok": False, "error": "integrity check skipped", "quick_check": "skipped",
                "session_count": None, "hidden_count": None, "candidates": [],
                "candidate_count": 0, "largest": []}
    else:
        data = db_report(db, cutoff, not args.visible_only, args.largest_limit, args.candidate_limit)

    lock_active, lock_stale, lock_malformed = read_locks(db.parent / "session_locks")
    fusers = fuser_pids(db) if db.exists() else []
    processes = devin_processes()
    clock = code_lock()
    active_units, unit_error = dispatch_units()
    tasks = dispatch_tasks(active_units)
    trees = worktrees(tasks)

    candidates = []
    unpreserved = []
    for row in data["candidates"]:
        pres = preservation_for(row["id"])
        lock = next((x for x in lock_active if x["session"] == row["id"]), None)
        stale = next((x for x in lock_stale if x["session"] == row["id"]), None)
        rec = {**row, **pres,
               "lock": pid_label(lock) if lock else (pid_label(stale) if stale else "")}
        candidates.append(rec)
        if not rec["preserved"]:
            unpreserved.append(rec)

    active_tasks = [t for t in tasks if t["state"] == "active"]
    dirty_trees = [t for t in trees if t["git"] != "clean"]
    cleanup_timer = unit_state("devin-cleanup.timer")
    cleanup_service = unit_state("devin-cleanup.service")
    active_candidate_locks = [x for x in candidates if x["lock"].startswith("active pid")]
    free_for_backup = disk.free >= db_footprint * BACKUP_FREE_MULTIPLIER
    integrity_ok = data.get("quick_check") == "ok"
    vacuum_ready = bool(integrity_ok and not fusers and not lock_active and
                        not (clock.get("alive") and clock.get("pid")))
    no_backup_allowed = bool(integrity_ok and not unpreserved and free_for_backup)
    delete_ready = bool(integrity_ok and not unpreserved and not active_candidate_locks)

    warnings = []
    if not db.exists() or data.get("error"):
        warnings.append(data.get("error") or "DB missing")
    if not integrity_ok:
        warnings.append("integrity check did not pass")
    if unpreserved:
        warnings.append(f"{len(unpreserved)} candidate sessions lack local preservation")
    if fusers:
        warnings.append("sessions.db is open")
    if lock_active:
        warnings.append(f"{len(lock_active)} active session locks")
    if active_candidate_locks:
        warnings.append(f"{len(active_candidate_locks)} dry-run candidates have active locks")
    if cleanup_timer.get("ActiveState") != "active":
        warnings.append("devin-cleanup.timer is not active")
    if active_tasks:
        warnings.append(f"{len(active_tasks)} active dispatch tasks")
    if dirty_trees:
        warnings.append(f"{len(dirty_trees)} dispatch worktrees dirty/unknown")
    if not free_for_backup:
        warnings.append("free space is below 2x DB footprint")
    if os.environ.get("NO_BACKUP") == "1" and not no_backup_allowed:
        warnings.append("NO_BACKUP=1 is set but not permitted by this check")

    status = "fail" if (not db.exists() or not integrity_ok) else ("warn" if warnings else "ok")

    summary = {
        "host": host,
        "status": status,
        "generated_at": generated.isoformat(timespec="seconds"),
        "db": str(db),
        "retention_days": retention,
        "cutoff_epoch": cutoff,
        "cutoff_at": iso(cutoff),
        "disk_free_bytes": disk.free,
        "db_bytes": sizes[""],
        "wal_bytes": sizes["-wal"],
        "shm_bytes": sizes["-shm"],
        "quick_check": data.get("quick_check"),
        "session_count": data.get("session_count"),
        "hidden_count": data.get("hidden_count"),
        "candidate_count": data.get("candidate_count"),
        "candidate_rows_reported": len(candidates),
        "unpreserved_count": len(unpreserved),
        "active_candidate_lock_count": len(active_candidate_locks),
        "active_lock_count": len(lock_active),
        "stale_lock_count": len(lock_stale),
        "malformed_lock_count": len(lock_malformed),
        "fuser_pids": [p["pid"] for p in fusers],
        "devin_process_count": len(processes),
        "code_lock": clock,
        "active_dispatch_tasks": len(active_tasks),
        "dispatch_tasks": len(tasks),
        "dispatch_worktrees": len(trees),
        "dirty_worktrees": len(dirty_trees),
        "free_for_backup": free_for_backup,
        "delete_ready": delete_ready,
        "vacuum_ready": vacuum_ready,
        "no_backup_allowed": no_backup_allowed,
        "warnings": warnings,
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"devin-precleanup-{host}-{generated.strftime('%Y%m%d-%H%M%S')}.md"

    lines = [
        "# Devin pre-cleanup check",
        "",
        f"- Status: **{status.upper()}**",
        f"- Generated: {generated.isoformat(timespec='seconds')}",
        f"- Host: `{host}`",
        f"- Retention: `{retention}` days",
        f"- Cutoff: `{iso(cutoff)}` (`{cutoff}`)",
        f"- DB: `{db}`",
        f"- Dry-run scope: {'all sessions' if not args.visible_only else 'hidden=0 only'}",
        "",
        "## Baseline",
        "",
        md_table(["item", "value"], [
            ["filesystem free", fmt_bytes(disk.free)],
            ["sessions.db", fmt_bytes(sizes[""])],
            ["sessions.db-wal", fmt_bytes(sizes["-wal"])],
            ["sessions.db-shm", fmt_bytes(sizes["-shm"])],
            ["DB footprint", fmt_bytes(db_footprint)],
            ["sessions", data.get("session_count")],
            ["hidden sessions", data.get("hidden_count")],
            ["dry-run candidates", data.get("candidate_count")],
        ]),
        "",
        "## Integrity",
        "",
        f"- quick_check: `{data.get('quick_check')}`",
    ]
    if data.get("error"):
        lines += [f"- error: `{md_escape(data['error'], 300)}`",
                  "- action: stop; use the documented `.recover` rebuild path before any delete."]
    lines += [
        "",
        "## Writers and locks",
        "",
        md_table(["check", "result"], [
            ["code.lock", f"{clock['path']} — {pid_label(clock) if clock.get('pid') else ('present' if clock.get('exists') else 'absent')}"],
            ["fuser sessions.db", ", ".join(pid_label(p) for p in fusers) or "not open"],
            ["devin processes", len(processes)],
            ["active session locks", len(lock_active)],
            ["active dry-run candidate locks", len(active_candidate_locks)],
            ["stale session locks", len(lock_stale)],
            ["malformed session locks", len(lock_malformed)],
        ]),
    ]
    if processes:
        lines += ["", "### Devin process sample", ""]
        lines += [f"- `{md_escape(p, 180)}`" for p in processes[:20]]
    if lock_active:
        lines += ["", "### Active session locks", ""]
        lines += [f"- `{x['session']}` — {pid_label(x)}" for x in lock_active[:50]]
    lines += [
        "",
        "## Timers",
        "",
        md_table(["unit", "state", "enabled", "next"], [
            [u["unit"], u.get("ActiveState", "?"), u.get("UnitFileState", "?"),
             u.get("NextElapseUSecRealtime", u.get("error", "?"))]
            for u in [cleanup_timer, cleanup_service]
        ]),
        "",
        "## Dispatch safety",
        "",
        md_table(["item", "value"], [
            ["dispatch tasks", len(tasks)],
            ["active dispatch tasks", len(active_tasks)],
            ["dispatch worktrees", len(trees)],
            ["dirty/unknown worktrees", len(dirty_trees)],
            ["systemd unit scan", unit_error or "ok"],
        ]),
    ]
    if tasks:
        lines += ["", "### Dispatch tasks", "",
                  md_table(["task", "state", "repo", "exit", "worktree"],
                           [[md_escape(t["id"], 45), t["state"], md_escape(t["repo"], 20),
                             t["exit_code"] or t["result"] or "-", md_escape(t["worktree"], 55)]
                            for t in tasks[:100]])]
    if trees:
        lines += ["", "### Dispatch worktrees", "",
                  md_table(["worktree", "task", "task state", "git"],
                           [[md_escape(t["path"], 70), md_escape(t["task"], 40),
                             t["task_state"], t["git"]] for t in trees])]
    lines += [
        "",
        "## Archive / preservation",
        "",
        md_table(["item", "value"], [
            ["candidate sessions", data.get("candidate_count")],
            ["reported below", len(candidates)],
            ["preserved", len(candidates) - len(unpreserved)],
            ["missing preservation", len(unpreserved)],
        ]),
    ]
    if unpreserved:
        lines += ["", "### Candidates missing preservation", ""]
        lines += [f"- `{x['id']}` — {md_escape(x['title'], 80)} (last activity {iso(x['last_activity_at'])})"
                  for x in unpreserved[:200]]
    lines += [
        "",
        "## Backup decision",
        "",
        md_table(["item", "value"], [
            ["free >= 2x DB footprint", free_for_backup],
            ["all candidates preserved", not unpreserved],
            ["NO_BACKUP=1 permitted", no_backup_allowed],
            ["delete_ready", delete_ready],
            ["vacuum_ready", vacuum_ready],
        ]),
        "",
        "`NO_BACKUP=1` is permitted only when every dry-run candidate has local preservation evidence and free space is at least 2x the DB footprint.",
        "",
        "## Largest sessions",
        "",
        md_table(["session", "messages", "MB", "title"],
                 [[md_escape(x["session_id"], 30), x["messages"], x["total_mb"], md_escape(x["title"], 70)]
                  for x in data.get("largest", [])]),
        "",
        "## Dry-run candidates",
        "",
        md_table(["session", "last activity", "hidden", "lock", "preserved", "title"],
                 [[md_escape(x["id"], 30), iso(x["last_activity_at"]), x["hidden"],
                   md_escape(x["lock"], 45), "yes" if x["preserved"] else "NO",
                   md_escape(x["title"], 70)] for x in candidates]),
        "",
        "## Recommended next step",
        "",
    ]
    if status == "fail":
        lines.append("Do not prune. Run the documented SQLite `.recover` rebuild path, then rerun this check.")
    elif unpreserved:
        lines.append("Do not use `NO_BACKUP=1`. Archive/extract the missing sessions or create a verified backup before deleting rows.")
    elif not vacuum_ready:
        lines.append("Dry-run evidence is ready. Close Devin/ACP writers before VACUUM; DELETE may still be run only after reviewing the candidate list.")
    else:
        lines.append("Precheck passed. Proceed with the reviewed cleanup command if the candidate list matches the approved scope.")

    report_path.write_text("\n".join(lines) + "\n")
    latest = report_dir / f"devin-precleanup-{host}-latest.md"
    latest.write_text("\n".join(lines) + "\n")

    if args.json:
        print(json.dumps({**summary, "report": str(report_path)}, indent=2))
    else:
        print(f"status={status} report={report_path}")
        for warning in warnings:
            print(f"warn: {warning}")
    return 2 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
