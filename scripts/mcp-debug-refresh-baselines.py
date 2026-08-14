#!/usr/bin/env python3
"""Refresh mcp-debug efficiency baselines by running mcp_stats on both hosts."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

SSOT = Path(__file__).parent.parent / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"
SERVER = Path(__file__).parent / "mcp-debug-server.py"
COMMANDS = ["systemctl list-units", "df -h", "ps"]
HOSTS = ["tony_omen", "tony_dell"]


def mcp_stats(host, command):
    proc = subprocess.Popen(
        ["python3", str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "mcp_stats",
                "arguments": {"host": host, "command": command},
            },
        },
    ]
    for r in reqs:
        proc.stdin.write(json.dumps(r) + "\n")
    proc.stdin.close()

    results = {}
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2:
            results = json.loads(msg["result"]["content"][0]["text"])
            break

    rc = proc.wait()
    if rc != 0:
        print(f"mcp-debug-server exited with code {rc}", file=sys.stderr)
    return results


def main():
    parser = argparse.ArgumentParser(description="Refresh mcp-debug baselines")
    parser.add_argument(
        "--update-ssot",
        type=lambda x: x.lower() == "true",
        default=False,
        help="Update ssot.mcp-debug.yml with new baselines (default: false)",
    )
    args = parser.parse_args()

    all_results = {cmd: {} for cmd in COMMANDS}
    for command in COMMANDS:
        for host in HOSTS:
            all_results[command][host] = mcp_stats(host, command)

    if not args.update_ssot:
        print(json.dumps(all_results, indent=2))
        return

    with open(SSOT) as f:
        doc = yaml.safe_load(f)

    for command in COMMANDS:
        omen = all_results[command]["tony_omen"]
        cmd_cfg = doc["efficiency"]["commands"][command]
        cmd_cfg["raw_words"] = omen["raw_words"]
        cmd_cfg["compact_words"] = omen["compact_words"]
        cmd_cfg["savings_pct"] = omen["savings_pct"]
        cmd_cfg["raw_chars"] = omen["raw_chars"]
        cmd_cfg["compact_chars"] = omen["compact_chars"]
        cmd_cfg["savings_pct_chars"] = omen["savings_pct_chars"]
        cmd_cfg["recommended"] = omen["savings_pct_chars"] > 0

    doc["workflow"]["recommended"] = [
        c for c in COMMANDS if doc["efficiency"]["commands"][c]["recommended"]
    ]
    doc["workflow"]["not_recommended"] = [
        c for c in COMMANDS if not doc["efficiency"]["commands"][c]["recommended"]
    ]

    with open(SSOT, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False)

    print("Updated:", SSOT)
    print("Recommended:", doc["workflow"]["recommended"])
    print("Not recommended:", doc["workflow"]["not_recommended"])


if __name__ == "__main__":
    main()
