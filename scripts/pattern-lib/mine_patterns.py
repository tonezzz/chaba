#!/usr/bin/env python3
"""Leak-safe git-history pattern miner (P1).

Scans a repo's history for fix-class commits and emits candidate records
(jsonl, same schema as ~/evals/patterns/mine-*.jsonl). Commits in the leak
guard's banned set are skipped — benchmark-task fixes are never mined.

Usage:
  python3 mine_patterns.py --repo-name mddb-fork --repo-dir ~/CascadeProjects/mddb-fork \
      --guard ~/evals/patterns/leak-guard.json --since 2025-06-01 \
      [--class-map 'replication=replication'] --out mine-mddb-2.jsonl
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FIX_SUBJECT = re.compile(r"^(fix|bugfix|hotfix)[(:/\s]|.*\bfix\b", re.I)
TEST_FILE = re.compile(r"(^|/)(test[s]?/|.*_test\.|test_.*\.py$|.*_test\.go$)")


def git(repo: Path, *args) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=120)
    return r.stdout


def commits(repo: Path, since: str = None, max_n: int = 400) -> list:
    args = ["log", "--format=%H%x1f%s", f"--max-count={max_n}"]
    if since:
        args.append(f"--since={since}")
    out = git(repo, *args)
    return [l.split("\x1f", 1) for l in out.splitlines() if "\x1f" in l]


def changed_files(repo: Path, sha: str) -> list:
    out = git(repo, "show", "--name-only", "--format=", sha)
    return [l.strip() for l in out.splitlines() if l.strip()]


def stat(repo: Path, sha: str) -> str:
    return git(repo, "show", "--stat", "--format=", sha).strip().splitlines()[-1].strip()


def classify(subject: str, files: list, class_map: dict) -> str:
    for token, cls in class_map.items():
        if token in subject or any(token in f for f in files):
            return cls
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-name", required=True)
    ap.add_argument("--repo-dir", required=True, type=Path)
    ap.add_argument("--guard", type=Path, help="leak-guard.json")
    ap.add_argument("--since")
    ap.add_argument("--class-map", action="append", default=[],
                    help="token=class (matched on subject or file path)")
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    banned = set()
    if args.guard and args.guard.exists():
        g = json.loads(args.guard.read_text())
        banned = set(g.get("banned", {}).get(args.repo_name, []))
    class_map = dict(p.split("=", 1) for p in args.class_map)

    rows, skipped = [], []
    for sha, subject in commits(args.repo_dir.expanduser(), args.since, args.max):
        if not FIX_SUBJECT.match(subject):
            continue
        if any(b.startswith(sha[:len(b)]) or sha.startswith(b[:len(sha)])
               for b in banned):
            skipped.append(sha[:12])
            continue
        files = changed_files(args.repo_dir, sha)
        tests = [f for f in files if TEST_FILE.search(f)]
        code = [f for f in files if f not in tests]
        rows.append({
            "repo": args.repo_name, "commit": sha[:7], "subject": subject,
            "class": classify(subject, files, class_map),
            "has_test_pair": bool(tests),
            "code_files": code, "test_files": tests,
            "stat": stat(args.repo_dir, sha),
        })

    text = "\n".join(json.dumps(r) for r in rows)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)
    print(f"# {len(rows)} candidates, {len(skipped)} banned skipped "
          f"({', '.join(skipped) or 'none'})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
