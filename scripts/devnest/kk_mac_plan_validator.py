#!/usr/bin/env python3
"""Validate a KK-Mac planner artifact before it can create new tasks.

The planner is allowed to suggest work; only this deterministic validator may
write candidate specs to the shared DevNest inbox.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess

ALLOWED = {"summary", "operator_brief", "structured_extract", "safe_route"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
FORBIDDEN = re.compile(r"\b(package_plan|planner|credential|secret|publish|delete|shell)\b", re.I)


def rclone(*args: str, input_text: str | None = None) -> str:
    p = subprocess.run(
        ["rclone", *args], input=input_text, text=True,
        capture_output=True, timeout=60,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[:300] or "rclone failed")
    return p.stdout


def validate(pack: str, output: str) -> list[dict]:
    task = json.loads(rclone("cat", f"{pack}/inputs/task.json"))
    result = json.loads(rclone("cat", f"{pack}/out/result.json"))
    if result.get("verified") is not True:
        raise ValueError("planner artifact is not independently verified")
    parsed = result.get("parsed")
    source_id = task.get("source_id")
    if not isinstance(parsed, dict) or parsed.get("source_id") != source_id:
        raise ValueError("source_id mismatch")
    candidates = parsed.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        raise ValueError("candidate count must be 1..3")
    out = []
    for i, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        task_class = candidate.get("task_class")
        prompt = str(candidate.get("prompt", "")).strip()
        if task_class not in ALLOWED or not prompt or len(prompt) > 6000:
            raise ValueError("candidate contract invalid")
        if FORBIDDEN.search(prompt) or FORBIDDEN.search(str(task_class)):
            raise ValueError("candidate contains forbidden planner/action text")
        task_id = f"{source_id}-followup-{i}"
        if not SLUG.fullmatch(task_id):
            raise ValueError("candidate task ID unsafe")
        out.append({
            "task_id": task_id,
            "lane": "kk_mac_local",
            "task_class": task_class,
            "model": "qwen3:8b",
            "prompt": prompt,
            "expect": {},
            "source_id": source_id,
            "planner_validated": True,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack")
    ap.add_argument("--remote", default="gdrive:ada-nest-devnest")
    args = ap.parse_args()
    try:
        candidates = validate(args.pack, args.remote)
        for task in candidates:
            rclone(
                "rcat", f"{args.remote}/inbox/{task['task_id']}.json",
                input_text=json.dumps(task) + "\n",
            )
        print(json.dumps({"validated": len(candidates)}))
        return 0
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"validated": 0, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
