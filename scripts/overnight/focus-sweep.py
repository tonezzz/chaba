"""Overnight focus sweep.

- Park active foci with no recorded activity for 7 days.
- Close (complete) foci whose subtasks are all completed.
- Warn if there are more than one active branch focus or more than one active shared focus.
- Report worktrees that are clean but not the main worktree.

Modifies `docs/ssot/ssot.focus.current.active.yml` in-place.  Backup the file
before running if you want full auditability.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path("/home/tony/CascadeProjects/chaba-tony-dell")
ACTIVE_FILE = REPO / "docs/ssot/ssot.focus.current.active.yml"

DAYS_TO_PARK = 7


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def save_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def all_subtasks_done(item: dict) -> bool:
    for sub in item.get("subtasks", []):
        status = sub.get("status", "")
        if status != "completed":
            return False
    return True


def sweep():
    today = dt.date.today()
    data = load_yaml(ACTIVE_FILE)
    sections = data.get("sections", [])
    report = []

    active_branch_count = 0
    active_shared_count = 0
    parked = 0
    completed = 0
    warnings = []

    for section in sections:
        title = section.get("title", "")
        if "Branch" in title or "Shared" in title:
            for item in section.get("items", []):
                status = item.get("status", "")
                started = item.get("started", "")
                parked_at = item.get("parked", "")

                # Count active foci
                if status == "active":
                    if "Branch" in title:
                        active_branch_count += 1
                    elif "Shared" in title:
                        active_shared_count += 1

                # Close if all subtasks are done
                if status in ("active", "parked") and all_subtasks_done(item):
                    item["status"] = "completed"
                    item["completed"] = today.isoformat()
                    for sub in item.get("subtasks", []):
                        if sub.get("status") == "not_started":
                            sub["status"] = "completed"
                            sub["completed_at"] = today.isoformat()
                    completed += 1
                    report.append(f"completed: {item.get('label')}")
                    continue

                # Park if no recent activity
                last_date = parse_date(parked_at) or parse_date(started)
                if status == "active" and last_date:
                    age = (today - last_date).days
                    if age >= DAYS_TO_PARK:
                        item["status"] = "parked"
                        item["parked"] = today.isoformat()
                        item["previous_status"] = "active"
                        parked += 1
                        report.append(f"parked ({age}d): {item.get('label')}")

    if active_branch_count > 1:
        warnings.append(f"{active_branch_count} active branch foci (limit 1)")
    if active_shared_count > 1:
        warnings.append(f"{active_shared_count} active shared foci (limit 1)")

    save_yaml(ACTIVE_FILE, data)

    # Worktree audit
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO), "worktree", "list"],
            text=True,
        )
        worktrees = [line.strip() for line in out.strip().splitlines() if line.strip()]
    except subprocess.CalledProcessError as e:
        worktrees = [f"worktree list failed: {e}"]

    print("--- Focus Sweep Report ---")
    print(f"Completed: {completed}")
    print(f"Parked: {parked}")
    print(f"Warnings: {warnings}")
    for r in report:
        print(f"  - {r}")
    for w in warnings:
        print(f"  ! {w}")
    print("\nWorktrees:")
    for w in worktrees:
        print(f"  - {w}")

    return 0


if __name__ == "__main__":
    sys.exit(sweep())
