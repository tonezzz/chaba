#!/usr/bin/env python3
"""Annotate the kk-mac Ollama model name in opencode.json with the live gate.

Reads the authoritative admission snapshot from the LiteLLM shim on idc03
(GET :11447/health) and shows the reason + heartbeat age in the OpenChamber
model picker *before* a prompt is sent. The model stays selectable — fail
loud, not a fallback: nothing is rerouted and no model is hidden.

Env:
  OPENCODE_CONFIG_PATH  config to annotate (default ~/.config/opencode/opencode.json)
  KK_SHIM_SSH_HOST      host running the shim (default idc03)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

MODEL = "ollama-qwen25vl7b-kkmac"
BASE_NAME = MODEL
CONFIG_PATH = os.environ.get(
    "OPENCODE_CONFIG_PATH",
    os.path.expanduser("~/.config/opencode/opencode.json"),
)
SHIM_HOST = os.environ.get("KK_SHIM_SSH_HOST", "idc03")


def shim_snapshot() -> dict:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", SHIM_HOST,
           "curl -s --max-time 5 http://127.0.0.1:11447/health"]
    last = ""
    for attempt in range(2):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if not result.returncode:
            return json.loads(result.stdout)["admission"]
        last = result.stderr.strip()[:200]
        if attempt == 0:
            time.sleep(1)
    raise RuntimeError(f"shim health unreachable via {SHIM_HOST}: {last}")


def desired_name(snap: dict) -> tuple[str, str]:
    if snap.get("eligible"):
        return BASE_NAME, "eligible"
    reason = (snap.get("reasons") or ["unknown"])[0]
    age = snap.get("heartbeat_age_s")
    when = f"last beat {round(age)}s ago" if age is not None else "no heartbeat"
    return f"{BASE_NAME} — kk-mac {reason} ({when})", "blocked"


def annotate(path: str, name: str) -> bool:
    """Replace only the name line of this model's entry. Returns True on change."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()
    in_model = False
    for i, line in enumerate(lines):
        if f'"{MODEL}"' in line and "{" in line:
            in_model = True
            continue
        if in_model:
            if '"name"' in line:
                indent = line[:len(line) - len(line.lstrip())]
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                replacement = indent + '"name": ' + json.dumps(name) + "," + newline
                if line != replacement:
                    lines[i] = replacement
                    tmp = f"{path}.tmp"
                    with open(tmp, "w", encoding="utf-8") as out:
                        out.writelines(lines)
                    os.replace(tmp, path)
                    return True
                return False
            if line.strip() == "},":
                raise RuntimeError(f"no name field found for {MODEL} in {path}")
    if not in_model:
        raise RuntimeError(f"model {MODEL} not found in {path}")
    return False


def main() -> None:
    try:
        snap = shim_snapshot()
        name, status = desired_name(snap)
    except Exception as exc:
        name = f"{BASE_NAME} — kk-mac status unknown (gate unreachable)"
        status = "unknown"
        print(f"gate check failed: {exc}", file=sys.stderr)
    changed = annotate(CONFIG_PATH, name)
    print(f"{status}: {'updated' if changed else 'unchanged'} — {name}")


if __name__ == "__main__":
    main()
