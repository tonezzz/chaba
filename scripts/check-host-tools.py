#!/usr/bin/env python3
"""Verify that a host has the expected network/system tools from ssot.host-tools.yml.

The runner checks presence, optionally installs missing tools, and always ends
with a cleanup step that removes any temporary files created on the remote host.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

SSOT_PATH = Path(__file__).parent.parent / "docs" / "ssot" / "infrastructure" / "ssot.host-tools.yml"


def _ssh(host: str, command: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        capture_output=True,
        text=True,
        check=check,
    )


def _collect_tools(data: dict[str, Any], priority: str) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for category, items in data.get("tools", {}).items():
        for tool in items:
            p = tool.get("priority", "useful")
            if priority == "all":
                tools.append(tool)
            elif priority == p:
                tools.append(tool)
            elif priority == "useful" and p in ("essential", "useful"):
                tools.append(tool)
            elif priority == "essential" and p == "essential":
                tools.append(tool)
    return tools


def _install_cmd(template: str, package: str) -> str:
    return template.replace("<package>", shlex.quote(package))


def _main() -> int:
    parser = argparse.ArgumentParser(description="Check host tools against SSOT")
    parser.add_argument("host", help="Target host (ssh name, e.g. tony-dell, mn01)")
    parser.add_argument(
        "--install-missing",
        action="store_true",
        help="Install missing tools using the host's package manager",
    )
    parser.add_argument(
        "--priority",
        choices=["essential", "useful", "optional", "all"],
        default="essential",
        help="Which priority of tools to check",
    )
    parser.add_argument("--ssot", type=Path, default=SSOT_PATH, help="Path to ssot.host-tools.yml")
    parser.add_argument(
        "--keep-report",
        action="store_true",
        help="Keep the local temporary JSON report instead of removing it",
    )
    args = parser.parse_args()

    data = yaml.safe_load(args.ssot.read_text())
    host_id = args.host.replace("-", "_")
    host_cfg = data.get("hosts", {}).get(host_id)
    if not host_cfg:
        print(f"Host {args.host!r} not in {args.ssot}", file=sys.stderr)
        return 1

    os_name = host_cfg.get("os", "linux")
    pkg_mgr = host_cfg.get("package_manager", "apt")
    runner = data.get("runner", {})
    install_template = runner.get("install_commands", {}).get(pkg_mgr)
    cleanup_paths = runner.get("cleanup", {}).get("paths", [])

    tools = _collect_tools(data, args.priority)
    if not tools:
        print(f"No tools match priority {args.priority!r}", file=sys.stderr)
        return 1

    local_report = Path(tempfile.gettempdir()) / f"host-tools-report-{args.host}.json"
    local_files: list[Path] = [local_report]

    result: dict[str, Any] = {
        "host": args.host,
        "priority": args.priority,
        "checked": [],
        "missing": [],
        "installed_now": [],
        "verify_failed": [],
    }

    try:
        for tool in tools:
            name = tool["name"]
            pkg = tool.get("package", {}).get(os_name) or tool.get("package", {}).get("linux")
            record = {"name": name, "package": pkg}

            check_cmd = tool.get("check", f"command -v {shlex.quote(name)}")
            which = _ssh(args.host, check_cmd)
            installed = which.returncode == 0 and which.stdout.strip()

            if not installed:
                result["missing"].append(record)
                if args.install_missing and pkg and install_template:
                    install = _install_cmd(install_template, pkg)
                    inst = _ssh(args.host, install)
                    if inst.returncode == 0:
                        # Re-check
                        which2 = _ssh(args.host, check_cmd)
                        if which2.returncode == 0 and which2.stdout.strip():
                            result["installed_now"].append(record)
                            result["missing"] = [m for m in result["missing"] if m["name"] != name]
                            installed = True
                        else:
                            result["verify_failed"].append({"name": name, "error": f"installed but not in PATH: {which2.stderr.strip()}"})
                    else:
                        result["verify_failed"].append({"name": name, "error": f"install failed: {inst.stderr.strip()}"})
                if not installed:
                    continue

            result["checked"].append(record)
            verify_cmd = tool.get("verify", f"{name} --version 2>&1 | head -1")
            vr = _ssh(args.host, verify_cmd)
            if vr.returncode != 0:
                result["verify_failed"].append({"name": name, "error": vr.stderr.strip() or vr.stdout.strip()})

        local_report.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))

    finally:
        # Remote cleanup: remove any artifacts the runner may have left behind.
        if cleanup_paths:
            globs = " ".join(shlex.quote(p) for p in cleanup_paths)
            _ssh(args.host, f"rm -f {globs}")

        # Local cleanup: remove the temporary report unless requested.
        if not args.keep_report:
            for p in local_files:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    return 1 if result["missing"] or result["verify_failed"] else 0


if __name__ == "__main__":
    sys.exit(_main())
