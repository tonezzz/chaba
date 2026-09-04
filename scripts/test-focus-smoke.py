#!/usr/bin/env python3
"""Smoke tests for the focus system.

Read-only: no SSOT state is modified. Exits 0 on success, 1 on failure.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO / "venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"


def env_with_pythonpath():
    """Return an environment with the repo scripts dir on PYTHONPATH."""
    pp = os.environ.get("PYTHONPATH", "")
    sep = os.pathsep
    scripts = str(REPO / "scripts")
    return {**os.environ, "PYTHONPATH": f"{scripts}{sep + pp if pp else ''}"}


def run(args, **kwargs):
    """Run a command in the repo and return (rc, stdout, stderr)."""
    defaults = {"cwd": REPO, "capture_output": True, "text": True}
    defaults.update(kwargs)
    result = subprocess.run(args, **defaults)
    return result.returncode, result.stdout, result.stderr


def test_direct_status():
    code, out, err = run(
        [PYTHON, "-c", "from mcp_debug.focus import mcp_focus; "
                       "import json; print(json.dumps(mcp_focus('', 'status')))"],
        env=env_with_pythonpath(),
    )
    if code != 0:
        print(f"FAIL: direct mcp_focus('','status') import crashed\n{err}")
        return False
    try:
        doc = json.loads(out)
    except json.JSONDecodeError as e:
        print(f"FAIL: direct mcp_focus status returned invalid JSON: {e}\n{out}")
        return False
    if not doc.get("ok"):
        print(f"FAIL: direct mcp_focus status returned ok=False\n{out}")
        return False
    print(f"PASS: direct mcp_focus status (active keys: {list(doc.get('active', {}).keys())})")
    return True


def test_stdio_server():
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
    req += json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "mcp_focus_status", "arguments": {}},
    }) + "\n"

    code, out, err = run(
        [PYTHON, str(REPO / "scripts" / "mcp_focus" / "server.py")],
        input=req,
    )
    if code != 0:
        print(f"FAIL: mcp_focus server crashed\n{err}")
        return False
    lines = [l for l in out.splitlines() if l.strip()]
    if len(lines) < 2:
        print(f"FAIL: mcp_focus server did not return two JSON-RPC responses\n{out}")
        return False
    for i, line in enumerate(lines, start=1):
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"FAIL: response {i} is not valid JSON: {e}\n{line}")
            return False
        if "error" in doc:
            print(f"FAIL: response {i} contains an error\n{line}")
            return False
    print("PASS: mcp_focus stdio server initialize + mcp_focus_status")
    return True


def test_dispatcher_safe_dispatch_dry_run():
    code, out, err = run(
        [PYTHON, str(REPO / "scripts" / "focus-dispatcher.py"),
         "--safe-dispatch", "--dry-run"],
    )
    if code != 0:
        print(f"FAIL: focus-dispatcher --safe-dispatch --dry-run exited {code}\n{err}")
        return False
    print("PASS: focus-dispatcher --safe-dispatch --dry-run")
    return True


def test_dispatcher_process_ready_dry_run():
    code, out, err = run(
        [PYTHON, str(REPO / "scripts" / "focus-dispatcher.py"),
         "--process-ready", "--dry-run"],
    )
    if code != 0:
        print(f"FAIL: focus-dispatcher --process-ready --dry-run exited {code}\n{err}")
        return False
    print("PASS: focus-dispatcher --process-ready --dry-run")
    return True


def test_dispatcher_auto_dispatch_dry_run():
    code, out, err = run(
        [PYTHON, str(REPO / "scripts" / "focus-dispatcher.py"),
         "--auto-dispatch", "--dry-run"],
    )
    if code != 0:
        print(f"FAIL: focus-dispatcher --auto-dispatch --dry-run exited {code}\n{err}")
        return False
    print("PASS: focus-dispatcher --auto-dispatch --dry-run")
    return True


def test_dispatcher_process_all_ready_dry_run():
    code, out, err = run(
        [PYTHON, str(REPO / "scripts" / "focus-dispatcher.py"),
         "--process-all-ready", "--dry-run"],
    )
    if code != 0:
        print(f"FAIL: focus-dispatcher --process-all-ready --dry-run exited {code}\n{err}")
        return False
    print("PASS: focus-dispatcher --process-all-ready --dry-run")
    return True


def main():
    tests = [
        test_direct_status,
        test_stdio_server,
        test_dispatcher_safe_dispatch_dry_run,
        test_dispatcher_process_ready_dry_run,
        test_dispatcher_auto_dispatch_dry_run,
        test_dispatcher_process_all_ready_dry_run,
    ]
    passed = sum(1 for t in tests if t())
    total = len(tests)
    print(f"\n{passed}/{total} smoke tests passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
