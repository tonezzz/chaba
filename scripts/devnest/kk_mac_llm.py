#!/usr/bin/env python3
"""Bounded read-only task adapter for the online KK-Mac LLM lane.

This is intentionally not a shell or code-execution bridge. It admits only
small text tasks, checks the heartbeat gate first, and calls the loopback
Ollama API through SSH. Callers still need an independent verifier.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
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
LOCAL_HOSTS = frozenset({"local", "localhost", "127.0.0.1", "::1"})
OLLAMA_LOCAL_URL = "http://127.0.0.1:11434"


def is_local_host(host: str) -> bool:
    """True when the LLM target is this machine's own Ollama — the
    dedicated lane worker runs on KK-Mac itself, so the same executor
    contract serves both the ssh path (fleet runners) and the local path
    (on-host launchd worker) without a second implementation."""
    return str(host or "").strip().lower() in LOCAL_HOSTS


def validate_task(task_class: str, prompt: str) -> None:
    if task_class not in ALLOWED_TASKS:
        raise ValueError(f"task class not admitted: {task_class}")
    if not prompt.strip():
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("prompt exceeds read-only lane limit")


def _generate_payload(model: str, prompt: str, format: str | None,
                      think: bool | None) -> bytes:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # bounded lane: no chain-of-thought burn — qwen3 thinking is
        # what stalled the first 2026-10-30 packs
        "think": False if think is None else bool(think),
        "options": {"temperature": 0},
    }
    if format:
        body["format"] = format
    return json.dumps(body).encode()


def _call_local(payload: bytes, url: str,
                urlopen: Callable = urllib.request.urlopen) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=300) as response:
            return json.loads(response.read())
    except Exception as exc:
        raise RuntimeError(f"local ollama failed:{type(exc).__name__}:"
                           f"{exc}"[:400]) from exc


def call_remote(
    prompt: str,
    *,
    host: str = "kk-mac",
    model: str = "qwen3:8b",
    format: str | None = None,
    think: bool | None = None,
    local_url: str = OLLAMA_LOCAL_URL,
    ssh_run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    urlopen: Callable = urllib.request.urlopen,
) -> dict:
    payload = _generate_payload(model, prompt, format, think)
    if is_local_host(host):
        return _call_local(payload, local_url, urlopen=urlopen)
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host,
        "curl -fsS http://127.0.0.1:11434/api/generate "
        "-H 'Content-Type: application/json' --data-binary @-",
    ]
    result = ssh_run(command, input=payload, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError((result.stderr or b"ssh/ollama failed").decode(
            errors="replace"
        )[:500])
    try:
        return json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("KK-Mac returned non-JSON Ollama output") from exc


def run_task(task_class: str, prompt: str, **kwargs) -> dict:
    validate_task(task_class, prompt)
    gate = snapshot()
    if not gate["eligible"]:
        return {"ok": False, "admission": gate}
    response = call_remote(prompt, **kwargs)
    return {
        "ok": True,
        "admission": gate,
        "model": kwargs.get("model", "qwen3:8b"),
        "task_class": task_class,
        "response": response.get("response", ""),
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
