#!/usr/bin/env python3
"""Leak guard for the pattern library (OPS-0809, card pattern-library-coding-research).

Anti-leak rule: never mine benchmark-task commits. A benchmark task pins
`repo.ref` = the parent commit of the real fix; the fix commit(s) are the
ref's children in the source repo. Mining or retrieving a pattern derived
from a task's own fix commit leaks the answer into the arm under test.

This module computes the banned-commit set two ways:

  * auto: for each task.yaml, children of repo.ref found in a local clone
    (`git rev-list --all --children`), plus repo.ref itself.
  * extra: explicit repo:sha pairs (multi-commit fixes, squashed ranges).

CLI:
  python3 leak_guard.py --tasks-dir ~/evals/tasks \
      --repo terrology=~/evals/repos/terrology \
      --repo mddb-fork=~/CascadeProjects/mddb-fork \
      --out ~/evals/patterns/leak-guard.json
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # minimal fallback: enough for url/ref scraping
    yaml = None

SHORT = re.compile(r"^[0-9a-f]{7,40}$")


def load_task(path: Path) -> dict:
    text = path.read_text()
    if yaml:
        return yaml.safe_load(text)
    out = {"id": path.parent.name, "repo": {}}
    for k in ("url", "ref"):
        m = re.search(rf"^\s*{k}:\s*(\S+)", text, re.M)
        if m:
            out["repo"][k] = m.group(1).split()[0]
    return out


def children_of(repo_dir: Path, ref: str) -> set:
    """All direct children of `ref` across all refs in the clone."""
    try:
        out = subprocess.run(
            ["git", "rev-list", "--all", "--children"],
            cwd=repo_dir, capture_output=True, text=True, timeout=120,
        )
    except Exception:
        return set()
    kids = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts and parts[0].startswith(ref[:12]):
            kids.update(parts[1:])
    return kids


def resolve(repo_dir: Path, rev: str) -> str:
    r = subprocess.run(["git", "rev-parse", rev], cwd=repo_dir,
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else rev


def repo_name_for(url: str, repo_map: dict) -> str:
    base = url.rstrip("/").split("/")[-1].replace(".git", "")
    for name in sorted(repo_map, key=len, reverse=True):
        if name == base or name in url or name.startswith(base) \
                or base in name:
            return name
    return None


def build_guard(tasks_dir: Path, repo_map: dict, extra: list) -> dict:
    guard = {"_note": "banned commits per repo — never mine/retrieve these "
                      "for their task; auto-derived children of task repo.ref",
             "tasks": {}, "banned": {}}
    for ty in sorted(tasks_dir.glob("*/task.yaml")):
        t = load_task(ty)
        tid = t.get("id") or ty.parent.name
        repo = t.get("repo") or {}
        ref = repo.get("ref")
        url = repo.get("url", "")
        rname = repo_name_for(url, repo_map)
        banned = set()
        if ref:
            banned.add(ref[:12])
        if rname and ref:
            rdir = Path(repo_map[rname]).expanduser()
            for c in children_of(rdir, ref):
                banned.add(c[:12])
        guard["tasks"][tid] = {"repo": rname or url, "ref": ref,
                               "banned": sorted(banned)}
        if rname:
            guard["banned"].setdefault(rname, set()).update(banned)
    for pair in extra:
        rname, sha = pair.split(":", 1)
        guard["banned"].setdefault(rname, set()).add(sha[:12])
        guard.setdefault("extra", []).append(pair)
    guard["banned"] = {k: sorted(v) for k, v in guard["banned"].items()}
    return guard


def is_banned(guard: dict, repo: str, commit: str, task_id: str = None) -> bool:
    """Commit banned globally, or (task_id) banned for that task."""
    c = commit[:12]
    if c in guard.get("banned", {}).get(repo, []):
        return True
    if task_id:
        return c in guard.get("tasks", {}).get(task_id, {}).get("banned", [])
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True, type=Path)
    ap.add_argument("--repo", action="append", default=[],
                    help="name=/path/to/clone (repeatable)")
    ap.add_argument("--extra", action="append", default=[],
                    help="repo:sha extra banned commit (repeatable)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    repo_map = dict(p.split("=", 1) for p in args.repo)
    guard = build_guard(args.tasks_dir.expanduser(), repo_map, args.extra)
    text = json.dumps(guard, indent=1)
    if args.out:
        args.out.write_text(text + "\n")
        print(f"wrote {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
