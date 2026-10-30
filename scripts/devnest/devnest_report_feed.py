#!/usr/bin/env python3
"""Turn recent durable DevNest reports into bounded KK-Mac review tasks.

This is an upstream producer, not a filler generator. It only reads allowlisted
report files that changed within the configured window and records a remote
source marker so each report is submitted once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

REMOTE = "gdrive:ada-nest-devnest"
EXCLUDED = {"kk-mac", "kk_mac"}
EXTENSIONS = {".json", ".jsonl", ".md", ".txt"}


def rclone(*args: str, input_text: str | None = None) -> str:
    p = subprocess.run(
        ["rclone", *args], input=input_text, text=True,
        capture_output=True, timeout=60,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return p.stdout


def seen(remote: str, key: str) -> bool:
    try:
        return bool(rclone("lsf", f"{remote}/sources/{key}.seen").strip())
    except RuntimeError:
        return False


def recent_files(roots: list[Path], max_age_s: int) -> list[Path]:
    cutoff = time.time() - max_age_s
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in EXTENSIONS
                and path.stat().st_mtime >= cutoff
                and not any(part in EXCLUDED for part in path.parts)
            ):
                files.append(path)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def make_task(path: Path, repo_root: Path) -> tuple[str, dict]:
    rel = path.resolve().relative_to(repo_root.resolve())
    digest = hashlib.sha256(
        f"{rel}:{path.stat().st_mtime_ns}".encode()
    ).hexdigest()[:12]
    task_id = f"report-review-{digest}"
    # Keep the complete prompt below the KK package's 6000-character bound.
    evidence = path.read_text(errors="replace")[:4000]
    task = {
        "task_id": task_id,
        "lane": "kk_mac_local",
        "task_class": "summary",
        "model": "qwen3:8b",
        "prompt": (
            f"Summarize this durable DevNest report for an operator. "
            f"State the main finding and one next action. Do not invent facts. "
            f"Source: {rel}\n\n{evidence}"
        ),
        "expect": {},
        "source": str(rel),
    }
    return task_id, task


def produce(
    roots: list[Path],
    repo_root: Path,
    remote: str = REMOTE,
    max_age_s: int = 86400,
    max_new: int = 3,
) -> dict:
    result = {"submitted": [], "skipped": [], "rejected": []}
    for path in recent_files(roots, max_age_s):
        if len(result["submitted"]) >= max_new:
            break
        try:
            key, task = make_task(path, repo_root)
            if seen(remote, key):
                result["skipped"].append(f"{path.name}:seen")
                continue
            rclone(
                "rcat", f"{remote}/inbox/{key}.json",
                input_text=json.dumps(task) + "\n",
            )
            rclone(
                "rcat", f"{remote}/sources/{key}.seen",
                input_text=json.dumps({"source": str(path)}) + "\n",
            )
            result["submitted"].append({"task_id": key, "source": str(path)})
        except Exception as exc:
            result["rejected"].append(f"{path}:{type(exc).__name__}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default="/home/tony/CascadeProjects/chaba")
    ap.add_argument(
        "--root", action="append", default=["/home/tony/CascadeProjects/chaba/reports"]
    )
    ap.add_argument("--max-age-hours", type=float, default=24)
    ap.add_argument("--max-new", type=int, default=3)
    args = ap.parse_args()
    print(json.dumps(produce(
        [Path(x) for x in args.root],
        Path(args.repo_root),
        max_age_s=int(args.max_age_hours * 3600),
        max_new=args.max_new,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
