#!/usr/bin/env python3
"""Refresh mcp-debug efficiency baselines by running mcp_savings and updating SSOT."""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SSOT = REPO / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"


def _section_yaml(key, data):
    """Dump a single top-level section, returning text that starts with key:."""
    return yaml.safe_dump({key: data}, sort_keys=False, allow_unicode=True, width=120,
                          default_flow_style=False)


def _replace_section(text, key, new_section):
    """Replace a top-level YAML section using a regex that anchors on the next top-level key."""
    # Match from `key:` at start of line until the next top-level key or end of file.
    pattern = rf"^{re.escape(key)}:.*?^(?=(?:[a-zA-Z0-9_]+):|\Z)"
    return re.sub(pattern, new_section, text, count=1, flags=re.MULTILINE | re.DOTALL)


def main():
    parser = argparse.ArgumentParser(description="Refresh mcp-debug baselines")
    parser.add_argument(
        "--update-ssot",
        type=lambda x: x.lower() == "true",
        default=False,
        help="Update ssot.mcp-debug.yml with new baselines (default: false)",
    )
    args = parser.parse_args()

    # Import here so the package can find the local SSOT.
    sys.path.insert(0, str(REPO / "scripts"))
    from mcp_debug.tools import mcp_savings

    savings = mcp_savings([])
    if not savings.get("ok"):
        print("mcp_savings failed", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(savings, indent=2, default=str))

    if not args.update_ssot:
        return

    # Reorganise per-host output into per-command structures.
    by_command = {}
    for host, hdata in savings.get("hosts", {}).items():
        for command, s in hdata.get("commands", {}).items():
            by_command.setdefault(command, {})[host] = s

    commands_cfg = {}
    for command, hosts in by_command.items():
        baseline = hosts.get("tony_omen") or list(hosts.values())[0]
        savings_pcts = [h.get("savings_pct_chars", 0) for h in hosts.values()]
        recommended = all(p > 0 for p in savings_pcts)

        commands_cfg[command] = {
            "raw_words": baseline["raw_words"],
            "compact_words": baseline["compact_words"],
            "savings_pct": baseline["savings_pct"],
            "raw_chars": baseline["raw_chars"],
            "compact_chars": baseline["compact_chars"],
            "savings_pct_chars": baseline["savings_pct_chars"],
            "recommended": recommended,
            "hosts": {
                h: {
                    "raw_words": s["raw_words"],
                    "compact_words": s["compact_words"],
                    "savings_pct": s["savings_pct"],
                    "raw_chars": s["raw_chars"],
                    "compact_chars": s["compact_chars"],
                    "savings_pct_chars": s["savings_pct_chars"],
                }
                for h, s in hosts.items()
            },
        }

    efficiency = {
        "tracked_by": "mcp_stats",
        "note": f"per-host baselines generated on {datetime.now().strftime('%Y-%m-%d')} via mcp_savings",
        "commands": commands_cfg,
    }

    workflow = {
        "recommended": [c for c, d in commands_cfg.items() if d.get("recommended")],
        "not_recommended": [c for c, d in commands_cfg.items() if not d.get("recommended")],
    }

    ssot_text = SSOT.read_text()
    ssot_text = _replace_section(ssot_text, "efficiency", _section_yaml("efficiency", efficiency))
    ssot_text = _replace_section(ssot_text, "workflow", _section_yaml("workflow", workflow))

    with open(SSOT, "w") as f:
        f.write(ssot_text)

    print("Updated:", SSOT)
    print("Recommended:", workflow["recommended"])
    print("Not recommended:", workflow["not_recommended"])


if __name__ == "__main__":
    main()
