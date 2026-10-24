#!/usr/bin/env python3
"""P5 mine-back: every verified fix becomes a pattern.

After a bench arm (or any agent fix) is verified by the task's held-out
gate, distill it into a pattern record and push it to the code-patterns
collection + local mined jsonl. The leak guard still applies: a fix that
IS a benchmark-task commit is refused (it belongs to the eval, not the
library).

Inputs:
  --repo/--commit        source of the fix
  --task-id/--arm/--score  provenance (which bench verified it)
  --trigger/--transform/--class/--lang  the distilled pattern
  --guard                leak-guard.json (refusal checked)
  --out                  append the record to this jsonl
  --push                 also upsert to mddb code-patterns
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from push_pattern import banned, push, to_document  # noqa: E402


def diff_summary(repo: Path, commit: str) -> str:
    r = subprocess.run(["git", "show", "--stat", "--format=%s", commit],
                       cwd=repo, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--repo-name", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--task-id")
    ap.add_argument("--arm", type=int)
    ap.add_argument("--score", type=float)
    ap.add_argument("--key", required=True)
    ap.add_argument("--trigger", required=True)
    ap.add_argument("--transform", required=True)
    ap.add_argument("--cls", required=True)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--guard", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--mddb", default="http://100.102.134.91:11023/v1")
    args = ap.parse_args()

    rec = {
        "key": args.key, "repo": args.repo_name, "commit": args.commit[:12],
        "class": args.cls, "trigger": args.trigger,
        "transform": args.transform, "lang": args.lang,
        "evidence": (f"verified fix arm{args.arm} score={args.score} "
                     f"on {args.task_id}" if args.task_id else "verified"),
        "mined_back": True,
        "diff_summary": diff_summary(args.repo.expanduser(), args.commit),
    }
    if banned(rec, args.guard):
        print(json.dumps({"mined_back": False, "refused":
                          "benchmark-task commit (leak guard)"}))
        return 1
    if args.out:
        with args.out.expanduser().open("a") as f:
            f.write(json.dumps(rec) + "\n")
    if args.push:
        push(to_document(rec), args.mddb)
    print(json.dumps({"mined_back": True, "key": args.key,
                      "pushed": bool(args.push)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
