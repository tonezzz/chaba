#!/usr/bin/env python3
"""Render the Ada memory-bank registry SSOT to runtime JSON.

Reads the machine-readable `banks:` block from
docs/ssot/apps/ssot.apps.ada-memory-banks.yml and writes it to
~/.config/ada/memory-banks.json (ADA_MEMORY_BANKS_FILE default) so ada-pi
services can load it without a YAML dependency.

Usage:
  render-memory-banks.py                 # render locally
  render-memory-banks.py --host mn01     # render + scp to a host
  render-memory-banks.py --check         # diff current file vs rendered
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"
DEFAULT_OUT = Path.home() / ".config/ada/memory-banks.json"


def render() -> dict:
    data = yaml.safe_load(SSOT.read_text())
    banks = data.get("banks")
    if not isinstance(banks, dict) or not banks:
        raise SystemExit(f"{SSOT}: no 'banks' map found")
    return {
        "source": str(SSOT),
        "banks": banks,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", help="render locally then scp to this SSH host")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT, help="local output path")
    ap.add_argument("--check", action="store_true", help="diff current file vs rendered, exit 1 on drift")
    args = ap.parse_args()

    rendered = render()
    text = json.dumps(rendered, indent=2, sort_keys=True) + "\n"

    if args.check:
        target = args.output
        if not target.exists():
            print(f"MISSING {target}")
            return 1
        current = target.read_text()
        if current == text:
            print(f"OK {target} is in sync")
            return 0
        print(f"DRIFT {target}")
        for line in _diff(current, text):
            print(line)
        return 1

    if args.host:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(text)
            tmp = f.name
        remote = "~/.config/ada/memory-banks.json"
        subprocess.run(
            ["ssh", args.host, "mkdir -p ~/.config/ada"], check=True
        )
        subprocess.run(["scp", "-q", tmp, f"{args.host}:{remote}"], check=True)
        Path(tmp).unlink()
        print(f"rendered {len(rendered['banks'])} banks -> {args.host}:{remote}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"rendered {len(rendered['banks'])} banks -> {args.output}")
    return 0


def _diff(old: str, new: str) -> list[str]:
    import difflib
    return list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""))


if __name__ == "__main__":
    sys.exit(main())
