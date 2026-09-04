#!/usr/bin/env python3
"""Overnight focus review: generate health inbox drafts and update focus contracts."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NODE = os.environ.get('NODE_BIN') or shutil.which('node') or str(Path.home() / '.n' / 'bin' / 'node')
STATUS_FILE = Path("/home/tony/var/chaba/overnight-status.json")


def _truncate(text, limit=2000):
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"...{len(text) - limit} chars truncated...\n{text[-limit:]}"


def run(relative_args, steps, extra_env=None):
    if relative_args[0] == 'node':
        cmd = [NODE] + [str(REPO / a) for a in relative_args[1:]]
    else:
        cmd = [sys.executable, str(REPO / relative_args[0])] + relative_args[1:]
    print(f"[overnight] {relative_args[0]}")
    env = os.environ
    if extra_env:
        env = {**os.environ, **extra_env}
    result = subprocess.run(cmd, cwd=REPO, env=env, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    steps.append({
        "label": relative_args[0],
        "command": relative_args,
        "returncode": result.returncode,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
    })
    return result.returncode


def _write_status(started, rc, steps):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "started": started,
        "exit_code": rc,
        "status": "success" if rc == 0 else "failed",
        "steps": steps,
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2, default=str)


def main():
    started = datetime.now().isoformat(timespec="seconds")
    print(f"[overnight] starting at {started}")
    steps = []
    rc = 0
    if os.environ.get("SKIP_HEALTH") != "1":
        rc |= run(["scripts/mcp-health-to-inbox.py"], steps)
    rc |= run(["scripts/registry-drafts.py"], steps)
    rc |= run(["scripts/improvements-triage.py"], steps)
    rc |= run(["node", "scripts/ssot-validate-all.mjs"], steps)
    if rc:
        print("[overnight] aborting: SSOT validation failed", file=sys.stderr)
        _write_status(started, rc, steps)
        return rc
    rc |= run(["scripts/focus-dispatcher.py", "--sub-agent"], steps)
    rc |= run(["scripts/focus-dispatcher.py", "--advance"], steps)
    if os.environ.get("OVERNIGHT_PROCESS_READY") == "1":
        # Generate subagent contracts for Ready (Safe) items without committing/pushing.
        # The actual run_subagent calls are still manual; this just prepares contracts.
        rc |= run(["scripts/focus-dispatcher.py", "--process-all-ready"], steps,
                  extra_env={"FOCUS_DISPATCHER_COMMIT": "0", "FOCUS_DISPATCHER_PUSH": "0"})
    rc |= run(["node", "scripts/ssot-optimize.mjs"], steps)
    rc |= run(["node", "scripts/ssot-optimize-to-inbox.mjs"], steps)
    rc |= run(["scripts/process-remaining-focuses.py"], steps)
    if rc:
        print("[overnight] completed with errors")
    else:
        print("[overnight] completed")
    _write_status(started, rc, steps)
    return rc


if __name__ == "__main__":
    sys.exit(main())
