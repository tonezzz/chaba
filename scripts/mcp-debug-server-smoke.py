#!/usr/bin/env python3
"""Smoke test: ensure every tool listed in ssot.mcp-debug.yml is wired in server.py."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SSOT = REPO / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"
SERVER = REPO / "scripts" / "mcp_debug" / "server.py"


def main():
    import yaml
    with open(SSOT) as f:
        config = yaml.safe_load(f)
    expected = set(config.get("server", {}).get("tools", []))
    server_src = SERVER.read_text()
    # Tool schemas are declared as {"name": "mcp_...", ...}
    actual = set(re.findall(r'"name":\s*"(mcp_[a-z_]+)"', server_src))
    # Tool handlers appear as `elif name == "mcp_..."`
    handlers = set(re.findall(r'(?:if|elif) name == "(mcp_[a-z_]+)"', server_src))

    missing_in_server = expected - actual
    missing_handler = actual - handlers
    extra = actual - expected

    if missing_in_server:
        print(f"FAIL: SSOT tools not in server.py schema: {sorted(missing_in_server)}")
    if missing_handler:
        print(f"FAIL: tools in schema with no handler: {sorted(missing_handler)}")
    if extra:
        print(f"FAIL: server.py tools not in SSOT: {sorted(extra)}")
    if missing_in_server or missing_handler or extra:
        sys.exit(1)
    print(f"OK: {len(expected)} SSOT tools are wired in server.py with handlers")


if __name__ == "__main__":
    main()
