#!/usr/bin/env python3
"""Render the Ada calendar-provider registry SSOT to runtime JSON.

Reads the machine-readable `calendar:` block from
docs/ssot/apps/ssot.apps.ada-calendar.yml and writes it to
~/.config/ada/calendar.json (ADA_CALENDAR_FILE default) so ada-pi
services can load it without a YAML dependency.

Usage:
  render-calendar-providers.py                 # render locally
  render-calendar-providers.py --host mn01     # render + scp to a host
  render-calendar-providers.py --check         # diff current file vs rendered
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-calendar.yml"
DEFAULT_OUT = Path.home() / ".config/ada/calendar.json"


def render() -> dict:
    data = yaml.safe_load(SSOT.read_text())
    calendar = data.get("calendar")
    if not isinstance(calendar, dict) or not calendar.get("providers"):
        raise SystemExit(f"{SSOT}: no 'calendar.providers' map found")
    return {"source": str(SSOT), "calendar": calendar}


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
        if target.read_text() == text:
            print(f"OK {target} is in sync")
            return 0
        print(f"DRIFT {target}")
        print("\n".join(difflib.unified_diff(
            target.read_text().splitlines(), text.splitlines(), lineterm=""
        )))
        return 1

    if args.host:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(text)
            tmp = f.name
        remote = "~/.config/ada/calendar.json"
        subprocess.run(["ssh", args.host, "mkdir -p ~/.config/ada"], check=True)
        subprocess.run(["scp", "-q", tmp, f"{args.host}:{remote}"], check=True)
        Path(tmp).unlink()
        print(f"rendered {len(rendered['calendar']['providers'])} providers -> {args.host}:{remote}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"rendered {len(rendered['calendar']['providers'])} providers -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
