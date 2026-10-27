#!/usr/bin/env python3
"""L0 deterministic solver for worktree-safety: audits `git worktree list`
isolation invariants. Read-only git plumbing only."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args),
                          capture_output=True, text=True, timeout=30)


def _worktrees(cwd):
    r = _git(cwd, "worktree", "list", "--porcelain")
    wts, cur = [], {}
    for line in r.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": line.split(" ", 1)[1], "head": None,
                   "branch": None}
        elif line.startswith("HEAD "):
            cur["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            cur["branch"] = line.split(" ", 1)[1].replace(
                "refs/heads/", "")
        elif line == "" and cur:
            wts.append(cur)
            cur = {}
    return wts


def _default_branch(cwd):
    r = _git(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().split("/", 1)[1]
    for b in ("master", "main"):
        if _git(cwd, "rev-parse", "--verify", b).returncode == 0:
            return b
    return "master"


def collect(cwd):
    wts = _worktrees(cwd)
    default = _default_branch(cwd)
    paths = [w["path"] for w in wts]
    branches = [w["branch"] for w in wts if w.get("branch")]
    shadow = [b for b in branches if b.startswith("shadow/")]
    merged = _git(cwd, "branch", "--merged", default,
                  "--format=%(refname:short)")
    merged_set = {l.strip() for l in merged.stdout.splitlines() if l.strip()}
    inv = {
        "unique_paths": len(paths) == len(set(paths)),
        "unique_branches": len(branches) == len(set(branches)),
        "shadow_branches_present": len(shadow),
        "no_shadow_on_default": not any(
            w.get("branch") == default and w["path"].endswith("-shadow")
            for w in wts) and all(b != default for b in shadow),
        "no_shadow_merged": not any(b in merged_set for b in shadow),
    }
    ok = (inv["unique_paths"] and inv["unique_branches"]
          and inv["no_shadow_on_default"] and inv["no_shadow_merged"])
    return wts, inv, "pass" if ok else "fail", default


def main():
    task_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    wts, inv, verdict, default = collect(task_dir)
    art = {"host": os.uname().nodename,
           "collected_at": datetime.now(timezone.utc).isoformat(),
           "repo": os.path.abspath(task_dir),
           "default_branch": default,
           "worktrees": wts,
           "invariants": inv,
           "verdict": verdict,
           "read_only": True}
    out = os.path.join(task_dir, "evals/shadow/task/artifacts")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "worktree-safety.json"), "w") as f:
        json.dump(art, f, indent=1)
    print(json.dumps({"wrote": out + "/worktree-safety.json",
                      "worktrees": len(wts), "verdict": verdict}))


if __name__ == "__main__":
    main()
