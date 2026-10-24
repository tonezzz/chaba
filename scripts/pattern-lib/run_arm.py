#!/usr/bin/env python3
"""P4 bench arm driver: prepare workspace -> run arm -> verify -> record.

Arms:
  0  agent alone
  1  agent + pattern hint (static: hint text from --hint or task tN-hint)
  2  deterministic codemod (pattern key -> registry script)
  3  router: retrieve -> codemod-if-confident -> hint -> agent

Every arm runs the SAME verify/score.py with the task's held-out tests —
identical gate, comparable pass/cost/latency. Results append to a jsonl
record file for the results table.

Usage:
  python3 run_arm.py --task-id m1-mddb-follower-health --tasks-dir ~/evals/tasks \
      --repos ~/evals/repos --workspace-base ~/evals/workspaces-pat \
      --arm 3 --model litellm/gemini-3.5-flash-lite \
      --router ~/evals/patterns/router.py --registry codemods.json \
      --guard ~/evals/patterns/leak-guard.json --results results.jsonl
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from router import HINT_BLOCK, run_agent, run_verify  # noqa: E402


def sh(args, cwd=None, timeout=300):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def prepare_workspace(repo_url: str, ref: str, cache_dir: Path, dest: Path):
    """Clone repo@ref into dest, using a shared local mirror cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    mirror = cache_dir / f"{name}.git"
    if not mirror.exists():
        src = repo_url
        # prefer a same-named local clone when given a path
        if Path(repo_url).expanduser().exists():
            src = str(Path(repo_url).expanduser())
        r = sh(["git", "clone", "--bare", src, str(mirror)], timeout=600)
        if r.returncode != 0 and not mirror.exists():
            # lost a create race with a parallel run — reuse it
            raise RuntimeError("mirror clone failed: " + r.stderr[-300:])
    else:
        sh(["git", "fetch", "--all", "--prune"], cwd=mirror, timeout=300)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        sh(["rm", "-rf", str(dest)])
    r = sh(["git", "clone", str(mirror), str(dest)], timeout=300)
    if r.returncode != 0:
        raise RuntimeError("clone failed: " + r.stderr[-300:])
    r = sh(["git", "checkout", ref], cwd=dest, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("checkout failed: " + r.stderr[-300:])
    return dest


def record(results_path: Path, row: dict):
    with results_path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--tasks-dir", required=True, type=Path)
    ap.add_argument("--workspace-base", required=True, type=Path)
    ap.add_argument("--repo-cache", type=Path,
                    default=Path("~/evals/.repo-cache"))
    ap.add_argument("--repo-dir", type=Path,
                    help="local clone override for repo.url")
    ap.add_argument("--arm", required=True, type=int, choices=[0, 1, 2, 3])
    ap.add_argument("--model", default="litellm/gemini-3.5-flash-lite")
    ap.add_argument("--router", type=Path, default=HERE / "router.py")
    ap.add_argument("--registry", type=Path)
    ap.add_argument("--guard", type=Path)
    ap.add_argument("--codemod", type=Path, help="arm2: explicit codemod")
    ap.add_argument("--hint", type=Path, help="arm1: hint text file")
    ap.add_argument("--results", type=Path)
    ap.add_argument("--agent-timeout", type=int, default=1500)
    args = ap.parse_args()

    task_dir = args.tasks_dir.expanduser() / args.task_id
    task = yaml.safe_load((task_dir / "task.yaml").read_text())
    prompt = task["prompt"]
    ref = task["repo"]["ref"]
    url = str(args.repo_dir.expanduser()) if args.repo_dir else task["repo"]["url"]
    score_py = task_dir / task["verify"]["score"]

    ws = (args.workspace_base.expanduser() /
          f"{time.strftime('%Y%m%d_%H%M%S')}_{args.task_id}_arm{args.arm}")
    prepare_workspace(url, ref, args.repo_cache.expanduser(), ws)
    (ws / ".task-prompt.txt").write_text(prompt)
    prompt_file = ws / ".task-prompt.txt"

    # verify env — same managed .venv-verify the harness creates
    verify_py = None
    deps = (task.get("verify") or {}).get("deps") or []
    if deps:
        uv = str(Path.home() / ".local/bin/uv")
        venv = ws / ".venv-verify"
        r = sh([uv, "venv", str(venv)], timeout=120)
        if r.returncode == 0:
            vp = venv / "bin/python"
            sh([uv, "pip", "install", "--python", str(vp), *deps],
               timeout=600)
            verify_py = str(vp)
        else:
            print("warn: venv-verify failed: " + r.stderr[-200:],
                  file=sys.stderr)

    row = {"task": args.task_id, "arm": args.arm, "model": args.model,
           "ws": str(ws), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    t0 = time.time()

    if args.arm == 2:
        if not args.codemod:
            print("arm2 needs --codemod", file=sys.stderr)
            return 2
        r = sh([sys.executable, str(args.codemod), str(ws)], timeout=120)
        row["path"] = "codemod"
        row["detail"] = (r.stdout or r.stderr).strip()[:200]
    elif args.arm == 3:
        cmd = [sys.executable, str(args.router), str(prompt_file),
               "--workspace", str(ws), "--model", args.model,
               "--task-id", args.task_id]
        if args.registry:
            cmd += ["--registry", str(args.registry)]
        if args.guard:
            cmd += ["--guard", str(args.guard)]
        r = sh(cmd, timeout=args.agent_timeout + 60)
        row["path"] = "router"
        row["router_out"] = r.stdout.strip()[-600:]
    else:
        if args.arm == 1 and args.hint:
            prompt += args.hint.read_text()
        row["path"] = "agent" + ("+hint" if args.arm == 1 else "")
        row.update(run_agent(prompt, str(ws), args.model,
                             args.agent_timeout))

    # verify — same gate for every arm
    v = run_verify(str(score_py), str(task_dir), str(ws), py=verify_py)
    row["verify"] = v
    row["score"] = v.get("score")
    row["latency_s"] = round(time.time() - t0, 1)
    print(json.dumps(row, indent=1))
    if args.results:
        record(args.results.expanduser(), row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
