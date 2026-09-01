#!/usr/bin/env python3
"""
Phase 1 of the Dev-system regression focus: collect a read-only inventory
of branches and worktrees for all /home/tony/CascadeProjects/chaba* repos.

This script is intended to run on tony-dell. It can inventory the local
host or any reachable remote host via SSH (e.g. --target-host tony-omen).
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

EXPECTED_HOST = "tony-dell"


def run_git(repo: Path, *args, target_host: str | None = None) -> str:
    if target_host:
        # Run git commands over SSH on the target host.
        cmd = (
            f"cd {shlex.quote(str(repo))} && git "
            + " ".join(shlex.quote(a) for a in args)
        )
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", target_host, cmd],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    return result.stdout.strip()


def discover_repos(base: Path, target_host: str | None = None) -> list[Path]:
    if target_host:
        # List top-level directories and filter for chaba* .git repos.
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                target_host,
                f"ls -1 {shlex.quote(str(base))} 2>/dev/null",
            ],
            capture_output=True,
            text=True,
        )
        candidates = [base / name for name in result.stdout.splitlines() if name.startswith("chaba")]
        valid = []
        for candidate in candidates:
            check = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=5",
                    target_host,
                    f"test -d {shlex.quote(str(candidate / '.git'))} && echo yes",
                ],
                capture_output=True,
                text=True,
            )
            if check.stdout.strip() == "yes":
                valid.append(candidate)
        return sorted(valid)
    else:
        return sorted(
            p for p in base.iterdir()
            if p.is_dir() and p.name.startswith("chaba") and (p / ".git").exists()
        )


def main():
    parser = argparse.ArgumentParser(
        description="Collect branch/worktree inventory on tony-dell, optionally over SSH"
    )
    parser.add_argument("--base-dir", default="/home/tony/CascadeProjects", help="Parent of chaba* repos")
    parser.add_argument("--target-host", default=None, help="Remote host to inventory via SSH (default: local)")
    parser.add_argument("--force", action="store_true", help="Skip hostname check")
    args = parser.parse_args()

    local_host = os.uname().nodename
    if local_host != EXPECTED_HOST and not args.force and not args.target_host:
        print(f"Refusing: hostname is {local_host!r}, expected {EXPECTED_HOST!r}. Use --force to override.", file=sys.stderr)
        sys.exit(1)

    base = Path(args.base_dir)
    if not args.target_host and not base.exists():
        print(f"Base directory does not exist: {base}", file=sys.stderr)
        sys.exit(1)

    target = args.target_host or local_host
    repos = discover_repos(base, target_host=args.target_host)

    if not repos:
        print(f"No chaba* git repositories found on {target}.", file=sys.stderr)
        sys.exit(0)

    data = {
        "generated_at": datetime.now().isoformat(),
        "host": target,
        "base_dir": str(base),
        "repos": [],
    }

    for repo in repos:
        print(f"Collecting {repo.name} on {target} ...", file=sys.stderr)
        entry = {
            "name": repo.name,
            "path": str(repo),
            "branches_local": run_git(repo, "branch", "-vv", target_host=args.target_host).splitlines(),
            "branches_remote": run_git(repo, "branch", "-r", "-vv", target_host=args.target_host).splitlines(),
            "worktrees": run_git(repo, "worktree", "list", target_host=args.target_host).splitlines(),
            "head_commit": run_git(repo, "log", "-1", "--format=%h %s (%ci)", target_host=args.target_host),
        }
        data["repos"].append(entry)

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    suffix = f"-{target}" if args.target_host else ""
    json_path = reports_dir / f"2026-09-01-branch-worktree-sprawl{suffix}.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {json_path}", file=sys.stderr)

    md_path = reports_dir / f"2026-09-01-branch-worktree-sprawl{suffix}.md"
    with open(md_path, "w") as f:
        f.write(f"# Branch/Worktree Sprawl Report ({target})\n\n")
        f.write(f"- **Generated:** {data['generated_at']}\n")
        f.write(f"- **Host:** {data['host']}\n")
        f.write(f"- **Base directory:** {data['base_dir']}\n")
        f.write(f"- **Repos scanned:** {len(data['repos'])}\n\n")

        f.write("## Summary\n\n")
        f.write("| Repo | Local branches | Remote branches | Worktrees | HEAD |\n")
        f.write("|------|----------------|-----------------|-----------|------|\n")
        for r in data["repos"]:
            f.write(f"| {r['name']} | {len(r['branches_local'])} | {len(r['branches_remote'])} | {len(r['worktrees'])} | {r['head_commit']} |\n")
        f.write("\n")

        f.write("## Local branches\n\n")
        for r in data["repos"]:
            f.write(f"### {r['name']}\n\n")
            if r["branches_local"]:
                for b in r["branches_local"]:
                    f.write(f"- {b}\n")
            else:
                f.write("_No local branches._\n")
            f.write("\n")

        f.write("## Remote branches\n\n")
        for r in data["repos"]:
            f.write(f"### {r['name']}\n\n")
            if r["branches_remote"]:
                for b in r["branches_remote"]:
                    f.write(f"- {b}\n")
            else:
                f.write("_No remote branches._\n")
            f.write("\n")

        f.write("## Worktrees\n\n")
        for r in data["repos"]:
            f.write(f"### {r['name']}\n\n")
            if r["worktrees"]:
                for w in r["worktrees"]:
                    f.write(f"- {w}\n")
            else:
                f.write("_No linked worktrees._\n")
            f.write("\n")

    print(f"Wrote {md_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
