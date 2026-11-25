#!/usr/bin/env python3
"""taskdir-prune.py — GC ~/.local/share/devin-dispatch/tasks/<id>/ dirs.

Dispatch task dirs accumulate forever on hosts without a prune path
(card devin-taskdir-gc-dispatch-hosts: idc02 had 917 dirs). Two cases:

  * finished dirs — exit_code present. Removed when the exit_code mtime
    is older than --days (default 45). 45d >= the longest devin-usage.py
    reporting window (30d) plus margin; per-task metrics are appended to
    a durable JSONL ledger before deletion so the window can shrink later
    without losing fleet-usage history.

  * unfinished dirs — no exit_code (task died before writing it).
    Removed only when ALL hold:
      - last activity inside the dir is older than --stale-days (14d)
      - no needs-input.txt pending (operator question unanswered)
      - no live `devin-task-<id>`/`devin-task-<id>-fu*` systemd --user
        unit in active/activating state

Every run appends one summary line to ~/var/chaba/reports/timeline.jsonl
via scripts/lib/report.py so sweeps are auditable.

Usage:
  taskdir-prune.py [--days N] [--stale-days N] [--tasks-dir DIR]
                   [--ledger PATH] [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_here = Path(__file__).resolve()
REPO = _here.parents[2] if len(_here.parents) > 2 else _here.parent
sys.path.insert(0, str(REPO / "scripts"))
try:
    from lib.report import append_timeline  # noqa: E402
except Exception:  # standalone copy (e.g. /tmp test run) — reporting optional
    def append_timeline(*_a, **_kw):  # type: ignore
        return None

HOME = Path.home()
DEFAULT_TASKS = HOME / ".local/share/devin-dispatch/tasks"
DEFAULT_LEDGER = HOME / ".local/share/devin-dispatch/taskdir-usage.jsonl"
NODE = "devin-taskdir-prune"
LAYER = "L1-producer"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True,
                              timeout=timeout, errors="replace")
    except Exception as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def dir_last_activity(path: Path) -> float:
    """Newest mtime of the dir itself and its top-level entries."""
    latest = path.stat().st_mtime
    try:
        for e in os.scandir(path):
            try:
                latest = max(latest, e.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return latest


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def task_metrics(task_dir: Path) -> dict | None:
    """Extract the devin-usage.py fields from transcript.json + meta.json."""
    try:
        t = json.loads((task_dir / "transcript.json").read_text())
        m = json.loads((task_dir / "meta.json").read_text())
    except Exception:
        return None
    fm = t.get("final_metrics") or {}
    return {
        "task": task_dir.name,
        "session": t.get("session_id"),
        "model": (t.get("agent") or {}).get("model_name"),
        "prompt": fm.get("total_prompt_tokens", 0),
        "cached": fm.get("total_cached_tokens", 0),
        "completion": fm.get("total_completion_tokens", 0),
        "steps": fm.get("total_steps", 0),
        "result": m.get("result"),
        "finished_at": m.get("finished_at") or m.get("started_at"),
    }


def ledger_seen(ledger: Path) -> set[str]:
    seen = set()
    try:
        with open(ledger, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line).get("task", ""))
                except Exception:
                    pass
    except OSError:
        pass
    return seen


def ledger_append(ledger: Path, rec: dict) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def live_task_units(tasks_dir: Path) -> set[str]:
    """Task ids with an active/activating devin-task-<id>* unit."""
    r = run(["systemctl", "--user", "list-units", "--all", "--no-legend",
             "devin-task-*"])
    live = set()
    if r.returncode != 0:
        return live
    ids = {p.name for p in tasks_dir.iterdir() if p.is_dir()}
    for line in r.stdout.splitlines():
        parts = line.split()
        # Columns: UNIT LOAD ACTIVE SUB DESCRIPTION — ACTIVE is field 3.
        if len(parts) < 3:
            continue
        unit, state = parts[0], parts[2]
        if not unit.startswith("devin-task-") or \
                state not in ("active", "activating", "reloading"):
            continue
        rest = unit[len("devin-task-"):]
        for tid in ids:
            if rest == tid or rest.startswith(tid + "-fu"):
                live.add(tid)
    return live


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=45,
                    help="retention for finished (exit_code) dirs; must stay "
                         ">= the longest devin-usage.py reporting window")
    ap.add_argument("--stale-days", type=int, default=14,
                    help="age before an unfinished (no exit_code) dir is a "
                         "GC candidate")
    ap.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER,
                    help="durable per-task metrics JSONL appended before "
                         "a finished dir is deleted ('none' disables)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tasks_dir = args.tasks_dir.expanduser()
    result = {"dry_run": args.dry_run, "days": args.days,
              "stale_days": args.stale_days, "scanned": 0,
              "finished_pruned": [], "stale_pruned": [], "kept": [],
              "ledger_appended": 0, "freed_bytes": 0}
    if not tasks_dir.is_dir():
        result["note"] = f"no tasks dir: {tasks_dir}"
        print(json.dumps(result, indent=2) if args.json
              else f"no tasks dir: {tasks_dir}")
        return 0

    now = datetime.now().timestamp()
    finished_cut = now - args.days * 86400
    stale_cut = now - args.stale_days * 86400
    ledger = None if str(args.ledger) == "none" else args.ledger.expanduser()
    seen = ledger_seen(ledger) if ledger else set()
    live = live_task_units(tasks_dir)

    for d in sorted(tasks_dir.iterdir()):
        if not d.is_dir():
            continue
        result["scanned"] += 1
        ec = d / "exit_code"
        if ec.exists():
            try:
                finished_at = ec.stat().st_mtime
            except OSError:
                finished_at = dir_last_activity(d)
            if finished_at >= finished_cut:
                result["kept"].append({"task": d.name, "reason": "retention"})
                continue
            if args.dry_run:
                result["finished_pruned"].append(d.name)
                continue
            # Durable metrics ledger before the dir disappears.
            if ledger:
                rec = task_metrics(d)
                if rec and rec["task"] not in seen:
                    rec["host"] = os.uname().nodename
                    rec["pruned_at"] = now_iso()
                    ledger_append(ledger, rec)
                    seen.add(rec["task"])
                    result["ledger_appended"] += 1
            size = dir_size(d)
            shutil.rmtree(d, ignore_errors=True)
            result["freed_bytes"] += size
            result["finished_pruned"].append(d.name)
            continue

        # No exit_code — the task died before finishing. Conservative path.
        if (d / "needs-input.txt").exists():
            result["kept"].append({"task": d.name, "reason": "needs-input"})
            continue
        if d.name in live:
            result["kept"].append({"task": d.name, "reason": "live-unit"})
            continue
        if dir_last_activity(d) >= stale_cut:
            result["kept"].append({"task": d.name, "reason": "recent"})
            continue
        if args.dry_run:
            result["stale_pruned"].append(d.name)
            continue
        size = dir_size(d)
        shutil.rmtree(d, ignore_errors=True)
        result["freed_bytes"] += size
        result["stale_pruned"].append(d.name)

    summary = (f"scanned {result['scanned']}: pruned "
               f"{len(result['finished_pruned'])} finished + "
               f"{len(result['stale_pruned'])} stale-unfinished, kept "
               f"{len(result['kept'])}, freed "
               f"{result['freed_bytes'] / 1e6:.1f}MB"
               + (" (dry-run)" if args.dry_run else ""))
    result["summary"] = summary
    if not args.dry_run and tasks_dir == DEFAULT_TASKS:
        try:
            append_timeline(NODE, LAYER, "ok", summary)
        except Exception:
            pass
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(("DRY-RUN " if args.dry_run else "") + summary)
        for n in result["finished_pruned"][:20]:
            print(f"  - finished: {n}")
        for n in result["stale_pruned"][:20]:
            print(f"  - stale:    {n}")
        if len(result["finished_pruned"]) > 20 or \
                len(result["stale_pruned"]) > 20:
            print("  ... (truncated; --json for full list)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
