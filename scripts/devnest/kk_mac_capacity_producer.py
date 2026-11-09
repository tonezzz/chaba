#!/usr/bin/env python3
"""Refill the KK-Mac JevNest from an explicit inbox.

The producer never invents work. An upstream audit/report producer places
JSON task specs in gdrive:ada-nest/kk-llm/inbox/. This script stages at most
three valid specs when the KK admission gate is green and the queue is below
the configured depth.

Staging is atomic-by-marker (OPS-1002 atomic-3-3): the pack is copied,
verified with `rclone check`, and sealed with a manifest-hash `ready`
marker written last. Workers ignore packs without a valid marker, so an
interrupted staging run can no longer leave a claimable partial pack.
An incomplete unclaimed pack dir is retried (re-copied and re-sealed)
instead of counted as queue depth.
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

_REPO_ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "ada"))
import nest_pack_ready as npr

TASK_CLASSES = {"summary", "operator_brief", "structured_extract", "safe_route"}
TASK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
DEFAULT_REMOTE = "gdrive:ada-nest/kk-llm"
# OPS-1002 watermark — hard ceiling regardless of CLI args (the 10/5 args
# that overran the approved 3/3 spec were the trigger for the fix branch).
HARD_MAX_DEPTH = 3
HARD_MAX_NEW = 3


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


def inbox_task_id(filename: str) -> str | None:
    """Candidate task_id derived from the inbox filename — the write
    contract is `<task_id>.json`, so the filename alone decides whether
    the pack needs attention without a remote `cat`."""
    if not filename.endswith(".json"):
        return None
    candidate = filename[:-5]
    return candidate if TASK_RE.fullmatch(candidate) else None


def task_files(remote: str) -> list[str]:
    return sorted(
        x for x in rclone(
            "lsf", f"{remote}/inbox", "--files-only"
        ).splitlines()
        if x.endswith(".json")
    )


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


def pack_states(remote: str) -> dict[str, dict]:
    """One recursive listing -> {pack_name: state flags}.

    ready    — `ready` marker file present (staging sealed)
    claimed  — a worker claim file exists
    terminal — done or failed marker exists
    empty/partial dirs show up as all-False (staging debris, retryable).
    """
    entries = [
        x for x in rclone("lsf", f"{remote}/packs", "--recursive")
        .splitlines() if x.strip()
    ]
    states: dict[str, dict] = {}
    for line in entries:
        parts = line.split("/", 1)
        name = parts[0]
        rel = parts[1] if len(parts) > 1 else ""
        st = states.setdefault(
            name, {"ready": False, "claimed": False, "terminal": False})
        if rel == npr.READY_FILE:
            st["ready"] = True
        elif rel.startswith("claim/"):
            st["claimed"] = True
        elif rel in ("done", "failed"):
            st["terminal"] = True
    return states


def live_depth(states: dict[str, dict]) -> int:
    """Queue watermark counts packs a worker can see: sealed (ready) or
    claimed. Terminal packs are drained; bare/incomplete dirs are staging
    debris, not depth."""
    return sum(
        1 for st in states.values()
        if not st["terminal"] and (st["ready"] or st["claimed"])
    )


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
        if not pack_yml.is_file() or not (pack / "inputs" / "task.json").is_file():
            raise ValueError("pack build incomplete")
        remote_dir = f"{remote}/packs/{pack_name}"
        rclone(
            "copy", str(pack), remote_dir,
            "--exclude", "claim/**", "--exclude", "done",
            "--exclude", "failed", "--exclude", npr.READY_FILE,
        )
        npr.verify_and_mark(pack, remote_dir,
                            staged_by="kk_mac_capacity_producer",
                            rclone=rclone)
    return pack_name


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
    depth_clamped = max(1, min(max_depth, HARD_MAX_DEPTH))
    new_clamped = max(1, min(max_new, HARD_MAX_NEW))
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
        "retried": [],
        "skipped": [],
        "limits": {"max_depth": depth_clamped, "max_new": new_clamped,
                   "clamped": depth_clamped != max_depth
                   or new_clamped != max_new},
    }
    if not result["eligible"]:
        result["skipped"].append("admission_gate")
        return result
    if expired():
        result["skipped"].append("budget_exhausted")
        return result
    # one recursive listing yields queue depth, sealed-pack names, claim
    # and terminal state — rclone calls are the hang surface (~60s each)
    states = pack_states(remote)
    result["queue_before"] = live_depth(states)
    room = depth_clamped - result["queue_before"]
    if room <= 0:
        result["skipped"].append("queue_at_capacity")
        return result
    for filename in task_files(remote):
        if expired():
            result["skipped"].append("budget_exhausted")
            break
        if len(result["staged"]) >= min(new_clamped, room):
            break
        candidate = inbox_task_id(filename)
        if not candidate:
            result["skipped"].append(f"{filename}:bad_task_filename")
            continue
        pack_name = f"kk-mac-task-{candidate}"
        st = states.get(pack_name)
        retry = False
        if st:
            if st["terminal"]:
                result["skipped"].append(f"{filename}:terminal")
                continue
            if st["claimed"]:
                result["skipped"].append(f"{filename}:claimed")
                continue
            if st["ready"]:
                result["skipped"].append(f"{filename}:already_staged")
                continue
            retry = True  # dir exists, unsealed, unclaimed -> re-stage
        try:
            task = load_task(remote, filename)
            if task["task_id"] != candidate:
                result["skipped"].append(f"{filename}:task_id_mismatch")
                continue
            result["staged"].append(stage_task(
                task, remote=remote, template=template, dry_run=dry_run
            ))
            if retry:
                result["retried"].append(pack_name)
            states[pack_name] = {
                "ready": True, "claimed": False, "terminal": False}
        except Exception as exc:
            result["skipped"].append(f"{filename}:{type(exc).__name__}")
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
