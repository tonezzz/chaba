#!/usr/bin/env python3
"""Validate that operational MCP server implementations exist on disk.

Reads docs/ssot/infrastructure/ssot.mcp.yml, finds every server marked
status: operational, and confirms that the referenced implementation file
or script exists. This guard prevents source files from being deleted or
moved without updating the SSOT.
"""

import os
import re
import sys
from pathlib import Path

import yaml

SSOT_FILE = Path("/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.mcp.yml")
SKIP_RUNNERS = {"npx", "node", "docker"}  # paths after these runners are package/image names, not filesystem files


def expand_user(path: str) -> str:
    return os.path.expanduser(path).replace("$HOME", os.environ.get("HOME", "/home/tony"))


def path_to_check(implementation: str) -> str | None:
    """Extract the first absolute or ~/ path from an implementation string."""
    if not implementation or implementation.startswith(("http://", "https://")):
        return None

    # Try to find the first token that looks like a filesystem path.
    for token in implementation.split():
        token = expand_user(token)
        if token.startswith("/") or token.startswith("~"):
            return token
        # npx package names sometimes have a leading @ or contain a slash but
        # are not filesystem paths; we skip npx lines entirely.
    return None


def main() -> int:
    if not SSOT_FILE.exists():
        print(f"ERROR: SSOT file not found: {SSOT_FILE}")
        return 1

    with open(SSOT_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    servers = data.get("servers", {})
    if not servers:
        print(f"ERROR: No 'servers' section in {SSOT_FILE}")
        return 1

    missing: list[str] = []
    for name, config in servers.items():
        if config.get("status") != "operational":
            continue

        impl = config.get("implementation", "")
        runner = impl.split(None, 1)[0] if impl else ""

        if runner in SKIP_RUNNERS or impl.startswith(("http://", "https://")):
            continue

        path = path_to_check(impl)
        if not path:
            missing.append(f"{name}: no filesystem path found in implementation: {impl}")
            continue

        if not Path(path).exists():
            missing.append(f"{name}: implementation not found: {path}")

    if missing:
        print("MCP source validation FAILED")
        print("Operational servers with missing implementation files:")
        for item in missing:
            print(f"  - {item}")
        return 1

    checked = sum(
        1
        for c in servers.values()
        if c.get("status") == "operational" and not c.get("implementation", "").startswith(("http://", "https://"))
    )
    print(f"OK: all {checked} operational MCP implementations are present on disk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
