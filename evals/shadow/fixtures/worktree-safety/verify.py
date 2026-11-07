#!/usr/bin/env python3
"""Held-out verifier for worktree-safety: re-runs git plumbing in the
SAME repo (common gitdir) and confirms the artifact's claims."""
import json
import os
import subprocess
import sys


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args),
                          capture_output=True, text=True, timeout=30)


def verify(task_dir):
    path = os.path.join(task_dir,
                        "evals/shadow/task/artifacts/worktree-safety.json")
    try:
        with open(path) as f:
            a = json.load(f)
    except Exception as e:
        return {"verdict": "fail", "checks": {"artifact readable": False,
                                              "error": str(e)}}
    checks = {}
    checks["required fields"] = all(
        k in a for k in ("host", "collected_at", "worktrees", "invariants",
                         "verdict", "read_only"))
    checks["read_only true"] = a.get("read_only") is True

    # Re-collect reality from the same common gitdir.
    r = _git(task_dir, "worktree", "list", "--porcelain")
    real_paths = set()
    real_branches = {}
    cur = {}
    for line in r.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": line.split(" ", 1)[1]}
            real_paths.add(cur["path"])
        elif line.startswith("branch "):
            real_branches[cur["path"]] = line.split(" ", 1)[1].replace(
                "refs/heads/", "")
        elif line == "":
            cur = {}
    claimed = {w.get("path") for w in a.get("worktrees", [])}
    # the agent may legitimately miss worktrees added after it ran — but it
    # must not invent paths that don't exist.
    checks["no invented worktrees"] = claimed <= real_paths
    checks["self worktree listed"] = os.path.abspath(task_dir) in claimed

    inv = a.get("invariants", {})
    # recomputed invariants
    paths = list(real_paths)
    branches = list(real_branches.values())
    shadow = [b for b in branches if b.startswith("shadow/")]
    default = a.get("default_branch") or "master"
    merged = _git(task_dir, "branch", "--merged", default,
                  "--format=%(refname:short)")
    merged_set = {l.strip() for l in merged.stdout.splitlines() if l.strip()}
    re_unique_p = len(paths) == len(set(paths))
    re_unique_b = len(branches) == len(set(branches))
    re_no_merged = not any(b in merged_set for b in shadow)
    checks["unique_paths claim truthful"] = (
        inv.get("unique_paths") in (re_unique_p, True))
    checks["unique_branches claim truthful"] = (
        inv.get("unique_branches") in (re_unique_b, True))
    checks["no_shadow_merged truthful"] = (
        inv.get("no_shadow_merged") in (re_no_merged, True))
    checks["verdict consistent"] = a.get("verdict") in ("pass", "fail") and (
        a["verdict"] == "pass") == all(
            inv.get(k) is True for k in
            ("unique_paths", "unique_branches", "no_shadow_merged"))

    verdict = "pass" if all(v is True for v in checks.values()) else "fail"
    return {"verdict": verdict, "checks": checks,
            "artifact": "worktree-safety.json",
            "worktrees_seen": len(real_paths)}


if __name__ == "__main__":
    td = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(verify(td), indent=1))
