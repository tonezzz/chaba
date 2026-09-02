#!/usr/bin/env python3
"""Validate that operational MCP server implementations exist on disk.

Reads the repository's own docs/ssot/infrastructure/ssot.mcp.yml, resolves any
per_host override for this machine, and confirms that the referenced
implementation file or script exists.
"""

import os
import socket
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SSOT_FILE = REPO_ROOT / "docs" / "ssot" / "infrastructure" / "ssot.mcp.yml"
SKIP_RUNNERS = {"npx", "node", "docker"}


def expand_path(token: str) -> str:
    return os.path.expandvars(os.path.expanduser(token))


def is_path(token: str) -> bool:
    token = expand_path(token)
    return token.startswith("/") or token.startswith("~")


def normalize_host(name: str) -> str:
    return name.lower().replace("-", "_")


def current_host() -> str:
    return normalize_host(socket.gethostname())


def get_path_to_check(implementation: str) -> str | None:
    """Extract the first absolute or ~/ path from an implementation string."""
    if not implementation or implementation.startswith(("http://", "https://")):
        return None

    for token in implementation.split():
        if is_path(token):
            return expand_path(token)
    return None


def merge_host_overrides(cfg: dict, host: str) -> dict:
    """Return a server config merged with the per_host block for `host`."""
    merged = dict(cfg)
    per_host = merged.pop("per_host", None)
    if isinstance(per_host, dict):
        for key in (host, host.replace("_", "-")):
            overrides = per_host.get(key)
            if isinstance(overrides, dict):
                for k, v in overrides.items():
                    if k == "env" and isinstance(v, dict) and isinstance(merged.get("env"), dict):
                        merged["env"] = {**merged["env"], **v}
                    else:
                        merged[k] = v
                break
    return merged


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

    host = current_host()
    missing: list[str] = []
    checked = 0

    for name, config in servers.items():
        if config.get("status") != "operational":
            continue

        resolved = merge_host_overrides(config, host)
        impl = resolved.get("implementation", "")
        runner = impl.split(None, 1)[0] if impl else ""

        if runner in SKIP_RUNNERS or impl.startswith(("http://", "https://")):
            continue

        checked += 1
        path = get_path_to_check(impl)
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

    print(f"OK: all {checked} operational MCP implementations are present on disk for host {host}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
