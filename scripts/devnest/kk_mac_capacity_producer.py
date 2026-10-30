#!/usr/bin/env python3
"""Refill the KK-Mac JevNest from an explicit inbox.

The producer never invents work. An upstream audit/report producer places
JSON task specs in gdrive:ada-nest-kk-llm/inbox/. This script stages at most
three valid specs when the KK admission gate is green and the queue is below
the configured depth.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from kk_mac_admission import snapshot

TASK_CLASSES = {"summary", "operator_brief", "structured_extract", "safe_route"}
TASK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def rclone(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["rclone", *args],
        input=input_text,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:300] or "rclone failed")
    return result.stdout


def queue_depth(remote: str) -> int:
    names = [x.rstrip("/") for x in
             rclone("lsf", f"{remote}/packs").splitlines() if x.strip()]
    depth = 0
    for name in names:
        entries = set(rclone(
            "lsf", f"{remote}/packs/{name}", "--max-depth", "1"
        ).splitlines())
        if "done" not in entries and not any(e.startswith("claim/") for e in entries):
            depth += 1
    return depth


def task_files(remote: str) -> list[str]:
    return [
        x for x in rclone(
            "lsf", f"{remote}/inbox", "--files-only"
        ).splitlines()
        if x.endswith(".json")
    ]


def load_task(remote: str, name: str) -> dict:
    task = json.loads(rclone("cat", f"{remote}/inbox/{name}"))
    if not isinstance(task, dict):
        raise ValueError("task must be a JSON object")
    task_id = str(task.get("task_id") or "")
    task_class = str(task.get("task_class") or "")
    prompt = str(task.get("prompt") or "")
    if not TASK_RE.fullmatch(task_id):
        raise ValueError("task_id is not a safe slug")
    if task_class not in TASK_CLASSES:
        raise ValueError(f"task_class not admitted: {task_class}")
    if not prompt or len(prompt) > 6000:
        raise ValueError("prompt missing or exceeds 6000 characters")
    return task


def stage_task(
    task: dict,
    *,
    remote: str,
    template: Path,
    dry_run: bool,
) -> str:
    task_id = task["task_id"]
    pack_name = f"kk-mac-task-{task_id}"
    if dry_run:
        return pack_name
    with tempfile.TemporaryDirectory(prefix="kk-mac-producer-") as tmp:
        pack = Path(tmp) / pack_name
        shutil.copytree(template, pack)
        pack_yml = pack / "pack.yml"
        pack_yml.write_text(
            pack_yml.read_text().replace("kk-mac-llm-pack", pack_name)
        )
        (pack / "inputs" / "task.json").write_text(
            json.dumps(task, indent=2, ensure_ascii=False) + "\n"
        )
        subprocess.run(
            ["python3", "scripts/ada/nest-pack-submit.py",
             str(pack), "--remote", remote],
            check=True,
            timeout=120,
        )
    return pack_name


def produce(
    *,
    remote: str = "gdrive:ada-nest-kk-llm",
    max_depth: int = 3,
    max_new: int = 3,
    template: Path | None = None,
    dry_run: bool = False,
) -> dict:
    template = template or (
        Path(__file__).resolve().parents[1] / "colab" / "packs" /
        "kk-mac-llm-pack"
    )
    gate = snapshot()
    if os.environ.get("DEVNEST_KK_MAC_ENABLED", "true").lower() != "true":
        gate = dict(gate)
        gate["eligible"] = False
        gate.setdefault("reasons", []).append("kk_disabled")
    result = {
        "eligible": bool(gate.get("eligible")),
        "gate": gate,
        "queue_before": None,
        "staged": [],
        "skipped": [],
    }
    if not result["eligible"]:
        result["skipped"].append("admission_gate")
        return result
    result["queue_before"] = queue_depth(remote)
    if result["queue_before"] >= max_depth:
        result["skipped"].append("queue_at_capacity")
        return result
    for filename in task_files(remote):
        if len(result["staged"]) >= min(
            max_new, max_depth - result["queue_before"]
        ):
            break
        try:
            task = load_task(remote, filename)
            pack_name = f"kk-mac-task-{task['task_id']}"
            existing = rclone("lsf", f"{remote}/packs", "--max-depth", "1")
            if f"{pack_name}/" in existing.splitlines():
                result["skipped"].append(f"{filename}:already_staged")
                continue
            result["staged"].append(stage_task(
                task, remote=remote, template=template, dry_run=dry_run
            ))
        except Exception as exc:
            result["skipped"].append(f"{filename}:{type(exc).__name__}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="gdrive:ada-nest-kk-llm")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-new", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(produce(
        remote=args.remote,
        max_depth=args.max_depth,
        max_new=args.max_new,
        dry_run=args.dry_run,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
