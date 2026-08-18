#!/usr/bin/env python3
"""Overnight focus review: generate health inbox drafts and update focus contracts."""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(relative_args):
    cmd = [sys.executable, str(REPO / relative_args[0])] + relative_args[1:]
    print(f"[overnight] {relative_args[0]}")
    result = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def main():
    now = datetime.now().isoformat(timespec="seconds")
    print(f"[overnight] starting at {now}")
    rc = 0
    if os.environ.get("SKIP_HEALTH") != "1":
        rc |= run(["scripts/mcp-health-to-inbox.py"])
    rc |= run(["scripts/registry-drafts.py"])
    rc |= run(["node", "scripts/ssot-validate-all.mjs"])
    if rc:
        print("[overnight] aborting: SSOT validation failed", file=sys.stderr)
        return rc
    rc |= run(["scripts/focus-dispatcher.py", "--sub-agent"])
    rc |= run(["scripts/process-remaining-focuses.py"])
    if rc:
        print("[overnight] completed with errors")
    else:
        print("[overnight] completed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
