#!/usr/bin/env python3
"""Print the status of the last overnight focus review run."""
import json
import sys
from datetime import datetime
from pathlib import Path

STATUS_FILE = Path("/home/tony/var/chaba/overnight-status.json")


def main():
    if not STATUS_FILE.exists():
        print(f"No overnight status file found at {STATUS_FILE}")
        return 1

    with open(STATUS_FILE) as f:
        status = json.load(f)

    print(f"Overnight review status: {status.get('status', 'unknown')}")
    print(f"Started:  {status.get('started', 'unknown')}")
    print(f"Finished: {status.get('timestamp', 'unknown')}")
    print(f"Exit code: {status.get('exit_code', 'unknown')}")

    steps = status.get("steps", [])
    if steps:
        print("\nSteps:")
        for step in steps:
            rc = step.get("returncode")
            marker = "OK" if rc == 0 else f"FAIL({rc})"
            print(f"  [{marker}] {step.get('label', step.get('command', '?'))}")
            if step.get("stderr"):
                for line in step["stderr"].splitlines()[:5]:
                    print(f"      {line[:120]}")
    return 0 if status.get("exit_code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
