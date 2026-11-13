#!/usr/bin/env python3
"""Refill the KK-Mac JevNest from an explicit inbox.

The producer never invents work. An upstream audit/report producer places
JSON task specs in gdrive:ada-nest/kk-llm/inbox/. This script stages at most
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
import time
from pathlib import Path

if __package__:
    from .kk_mac_admission import snapshot
else:
    from kk_mac_admission import snapshot

TASK_CLASSES = {"summary", "operator_brief", "structured_extract", "safe_route"}
TASK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
DEFAULT_REMOTE = "gdrive:ada-nest/kk-llm"


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
    entries = rclone(
        "lsf", f"{remote}/packs", "--recursive"
    ).splitlines()
    packs = {line.split("/", 1)[0] for line in entries if line.strip()}
    terminal = {
        line.split("/", 1)[0]
        for line in entries
        if line.endswith("/done") or line.endswith("/failed")
    }
    return len(packs - terminal)


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
        submitter = Path(__file__).resolve().parents[1] / "ada" / "nest-pack-submit.py"
        subprocess.run(
            ["python3", str(submitter),
             str(pack), "--remote", remote],
            check=True,
            timeout=120,
        )
    return pack_name


def pack_listing(remote: str) -> tuple[set[str], set[str]]:
    """One recursive lsf -> (live pack dir names, terminal pack names).
    A pack only counts once its pack.yml has landed — a dir left behind
    by a failed rclone copy is empty and must not wedge its inbox spec
    or occupy a queue slot."""
    entries = [
        x for x in rclone("lsf", f"{remote}/packs", "--recursive")
        .splitlines() if x.strip()
    ]
    dirs = {x.split("/", 1)[0] for x in entries if x.endswith("/pack.yml")}
    terminal = {
        x.split("/", 1)[0] for x in entries
        if x.endswith("/done") or x.endswith("/failed")
    }
    return dirs, terminal


def archive_spec(remote: str, filename: str, dest: str) -> None:
    """Move an inbox spec out of the scan path. Best-effort: the pack
    decision is already made, so a failed move only costs a redundant
    check next run."""
    rclone(
        "moveto", f"{remote}/inbox/{filename}",
        f"{remote}/inbox/{dest}/{filename}",
    )


def produce(
    *,
    remote: str = DEFAULT_REMOTE,
    max_depth: int = 3,
    max_new: int = 3,
    template: Path | None = None,
    dry_run: bool = False,
    budget_s: float = 90.0,
) -> dict:
    started = time.monotonic()

    def expired() -> bool:
        return time.monotonic() - started >= budget_s
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
    if expired():
        result["skipped"].append("budget_exhausted")
        return result
    # one recursive listing yields both queue depth and staged-pack names;
    # rclone calls are the hang surface (each can block up to 60s)
    dirs, terminal = pack_listing(remote)
    result["queue_before"] = len(dirs - terminal)
    if result["queue_before"] >= max_depth:
        result["skipped"].append("queue_at_capacity")
        return result
    existing_packs = {x.rstrip("/") for x in dirs}
    for filename in task_files(remote):
        if expired():
            result["skipped"].append("budget_exhausted")
            break
        if len(result["staged"]) >= min(
            max_new, max_depth - result["queue_before"]
        ):
            break
        # Cheap reject first: inbox filenames are task_id slugs, so an
        # already-staged spec costs zero rclone cats. Only unstaged
        # specs pay the load_task round-trip. Staged specs are archived
        # to inbox/done so the backlog drains itself over a few runs.
        if f"kk-mac-task-{filename[:-5]}" in existing_packs:
            result["skipped"].append(f"{filename}:already_staged")
            if not dry_run:
                try:
                    archive_spec(remote, filename, "done")
                except Exception:
                    pass
            continue
        try:
            task = load_task(remote, filename)
        except ValueError as exc:
            # Invalid spec — quarantine it so it stops costing an
            # rclone cat every run. ValueError covers bad JSON
            # (JSONDecodeError) and every validation failure; rclone
            # errors raise RuntimeError and stay retryable.
            result["skipped"].append(f"{filename}:{type(exc).__name__}")
            if not dry_run:
                try:
                    archive_spec(remote, filename, "quarantine")
                except Exception:
                    pass
            continue
        except Exception as exc:
            result["skipped"].append(f"{filename}:{type(exc).__name__}")
            continue
        pack_name = f"kk-mac-task-{task['task_id']}"
        if pack_name in existing_packs:
            result["skipped"].append(f"{filename}:already_staged")
            if not dry_run:
                try:
                    archive_spec(remote, filename, "done")
                except Exception:
                    pass
            continue
        try:
            result["staged"].append(stage_task(
                task, remote=remote, template=template, dry_run=dry_run
            ))
        except Exception as exc:
            result["skipped"].append(f"{filename}:{type(exc).__name__}")
            continue
        existing_packs.add(pack_name)
        if not dry_run:
            try:
                archive_spec(remote, filename, "done")
            except Exception:
                pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-new", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--budget-s", type=float, default=90.0,
                        help="overall wall-clock budget; rclone calls can "
                             "each block ~60s so the loop must self-limit")
    args = parser.parse_args()
    print(json.dumps(produce(
        remote=args.remote,
        max_depth=args.max_depth,
        max_new=args.max_new,
        dry_run=args.dry_run,
        budget_s=args.budget_s,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
