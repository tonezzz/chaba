#!/usr/bin/env python3
"""Bounded read-only task adapter for the online KK-Mac LLM lane.

This is intentionally not a shell or code-execution bridge. It admits only
small text tasks, checks the heartbeat gate first, and calls the loopback
Ollama API through SSH. Callers still need an independent verifier.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

try:
    from .kk_mac_admission import snapshot
except ImportError:  # direct script execution
    from kk_mac_admission import snapshot

ALLOWED_TASKS = {
    "operator_brief",
    "summary",
    "structured_extract",
    "safe_route",
}
MAX_PROMPT_CHARS = 6000

# MEM-1043 live memory guard: the runner ships kk_mac_remote_guard.py to
# KK-Mac over ssh stdin; the guard enforces the approved floors ON the
# Mac (>=60% free before load, abort <50% during load+generation,
# unload only a model this task loaded). Set memory_guard=False only
# for legacy curl passthrough — never for admitted lane tasks.
REMOTE_GUARD_PATH = Path(__file__).with_name("kk_mac_remote_guard.py")
GUARD_ENTRY_FLOOR_PCT = 60.0
GUARD_ABORT_FLOOR_PCT = 50.0


def validate_task(task_class: str, prompt: str) -> None:
    if task_class not in ALLOWED_TASKS:
        raise ValueError(f"task class not admitted: {task_class}")
    if not prompt.strip():
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("prompt exceeds read-only lane limit")


def call_remote(
    prompt: str,
    *,
    host: str = "kk-mac",
    model: str = "qwen3:8b",
    memory_guard: bool = True,
    entry_floor_pct: float = GUARD_ENTRY_FLOOR_PCT,
    abort_floor_pct: float = GUARD_ABORT_FLOOR_PCT,
    unload_after: bool = True,
    ssh_run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    if not memory_guard:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }).encode()
        command = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
            "curl -fsS http://127.0.0.1:11434/api/generate "
            "-H 'Content-Type: application/json' --data-binary @-",
        ]
        result = ssh_run(command, input=payload, capture_output=True,
                         timeout=120)
        if result.returncode:
            raise RuntimeError((result.stderr or b"ssh/ollama failed")
                               .decode(errors="replace")[:500])
        try:
            return json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "KK-Mac returned non-JSON Ollama output") from exc

    inner = {
        "model": model,
        "prompt": prompt,
        "options": {"temperature": 0},
        "entry_floor_pct": entry_floor_pct,
        "abort_floor_pct": abort_floor_pct,
        "unload_after": unload_after,
        "request_timeout_s": 110,
        "poll_s": 1.0,
    }
    arg = base64.b64encode(json.dumps(inner).encode()).decode()
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
        "python3", "-", arg,
    ]
    source = REMOTE_GUARD_PATH.read_bytes()
    result = ssh_run(command, input=source, capture_output=True,
                     timeout=180)
    try:
        out = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "KK-Mac guard returned non-JSON output: "
            + (result.stderr or b"") .decode(errors="replace")[:300]
        ) from exc
    if result.returncode and not (
            isinstance(out, dict) and "ok" in out):
        raise RuntimeError(
            (result.stderr or b"ssh/guard failed").decode(
                errors="replace")[:500])
    return out


def run_task(task_class: str, prompt: str, **kwargs) -> dict:
    validate_task(task_class, prompt)
    gate = snapshot()
    if not gate["eligible"]:
        return {"ok": False, "admission": gate}
    response = call_remote(prompt, **kwargs)
    if response.get("ok") is False:
        # guard/policy decline — surface the verdict, never the payload
        gate = dict(gate)
        gate["reasons"] = list(gate.get("reasons") or []) + [
            f"guard:{response.get('verdict')}:"
            f"{response.get('reason') or ''}"[:200]]
        return {"ok": False, "admission": gate,
                "guard": response.get("memory"),
                "verdict": response.get("verdict"),
                "reason": response.get("reason")}
    return {
        "ok": True,
        "admission": gate,
        "model": kwargs.get("model", "qwen3:8b"),
        "task_class": task_class,
        "response": response.get("response", ""),
        "memory": response.get("memory"),
        "guard": response.get("guard"),
        "usage": {
            "eval_count": response.get("eval_count"),
            "eval_duration": response.get("eval_duration"),
            "load_duration": response.get("load_duration"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_class", choices=sorted(ALLOWED_TASKS))
    parser.add_argument("prompt")
    args = parser.parse_args()
    try:
        result = run_task(args.task_class, args.prompt)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
