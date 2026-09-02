#!/usr/bin/env python3
"""
Auto-fix the chaba-mcp-experiments worktree drift on tony-omen.

This script is intended to run on tony-dell. It will:
  1. Check that the chaba-mcp-experiments worktree is clean.
  2. Fetch origin in the worktree.
  3. Rebase chaba-mcp-experiments onto origin/master.
  4. Push the rebased branch with --force-with-lease.
  5. Remove the worktree and the local branch.
  6. Write a report.

If any step is unsafe (dirty worktree, rebase conflict, etc.), it aborts
and writes a failure report.
"""
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

EXPECTED_HOST = "tony-dell"
REMOTE_HOST = "tony-omen"
REPO_NAME = "chaba"
WORKTREE_NAME = "chaba-mcp-experiments"
BASE_DIR = Path("/home/tony/CascadeProjects")
REPO_DIR = BASE_DIR / REPO_NAME
WORKTREE_DIR = BASE_DIR / WORKTREE_NAME


def run_remote(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            REMOTE_HOST,
            cmd,
        ],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed on {REMOTE_HOST}: {cmd}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def step(label: str, cmd: str) -> str:
    print(f"[step] {label} ...", file=sys.stderr)
    result = run_remote(cmd)
    return result.stdout.strip()


def main():
    if os.uname().nodename != EXPECTED_HOST:
        print(f"Refusing: this script must run on {EXPECTED_HOST}.", file=sys.stderr)
        sys.exit(1)

    report = {
        "started_at": datetime.now().isoformat(),
        "target_host": REMOTE_HOST,
        "worktree": str(WORKTREE_DIR),
        "status": "running",
        "steps": [],
        "error": None,
    }

    try:
        # Pre-flight: SSH connectivity.
        report["steps"].append({"label": "SSH preflight", "status": "ok"})
        run_remote("hostname")

        # 1. Check worktree cleanliness.
        status_output = step(
            "Check worktree cleanliness",
            f"cd {shlex.quote(str(WORKTREE_DIR))} && git status --short",
        )
        if status_output:
            raise RuntimeError(
                f"Worktree {WORKTREE_NAME} has uncommitted changes:\n{status_output}"
            )

        # 2. Fetch origin.
        step(
            "Fetch origin",
            f"cd {shlex.quote(str(WORKTREE_DIR))} && git fetch origin",
        )

        # 3. Try rebase onto origin/master.
        rebase_result = run_remote(
            f"cd {shlex.quote(str(WORKTREE_DIR))} && git rebase origin/master",
            check=False,
        )
        if rebase_result.returncode != 0:
            # Abort the rebase to leave the worktree in a clean state.
            run_remote(
                f"cd {shlex.quote(str(WORKTREE_DIR))} && git rebase --abort",
                check=False,
            )
            raise RuntimeError(
                f"Rebase failed with conflicts or other issue:\n"
                f"stdout: {rebase_result.stdout}\nstderr: {rebase_result.stderr}"
            )

        # 4. Force-push the rebased branch.
        step(
            "Force-push rebased branch",
            f"cd {shlex.quote(str(WORKTREE_DIR))} && git push --force-with-lease",
        )

        # 5. Remove the worktree.
        step(
            "Remove worktree",
            f"cd {shlex.quote(str(REPO_DIR))} && git worktree remove {shlex.quote(str(WORKTREE_DIR))}",
        )

        # 6. Delete the local branch.
        step(
            "Delete local branch",
            f"cd {shlex.quote(str(REPO_DIR))} && git branch -d {WORKTREE_NAME}",
        )

        report["status"] = "completed"
        report["completed_at"] = datetime.now().isoformat()
        report["summary"] = (
            f"{WORKTREE_NAME} was rebased onto origin/master, force-pushed, "
            "and its local worktree and branch were removed on tony-omen."
        )
    except Exception as exc:
        report["status"] = "aborted"
        report["error"] = str(exc)
        print(f"[abort] {exc}", file=sys.stderr)

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    json_path = reports_dir / "2026-09-01-chaba-mcp-experiments-auto-fix.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Wrote {json_path}", file=sys.stderr)

    md_path = reports_dir / "2026-09-01-chaba-mcp-experiments-auto-fix.md"
    with open(md_path, "w") as f:
        f.write(f"# chaba-mcp-experiments Auto-Fix Report\n\n")
        f.write(f"- **Target host:** {report['target_host']}\n")
        f.write(f"- **Worktree:** {report['worktree']}\n")
        f.write(f"- **Started:** {report['started_at']}\n")
        f.write(f"- **Completed:** {report.get('completed_at', 'N/A')}\n")
        f.write(f"- **Status:** {report['status']}\n\n")
        f.write("## Steps\n\n")
        for s in report["steps"]:
            f.write(f"- **{s['label']}:** {s['status']}\n")
        if report.get("error"):
            f.write(f"\n## Error\n\n```\n{report['error']}\n```\n")
        if report["status"] == "completed":
            f.write(
                f"\n## Summary\n\n{report['summary']}\n"
                "\nThe remote branch `origin/chaba-mcp-experiments` still exists; "
                "the user can delete it from GitHub or open a PR from it.\n"
            )
    print(f"Wrote {md_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
