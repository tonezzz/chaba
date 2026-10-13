#!/usr/bin/env python3
"""Render the Ada calendar-provider registry SSOT to runtime JSON.

Reads the machine-readable `calendar:` block from
docs/ssot/apps/ssot.apps.ada-calendar.yml and writes it to
~/.config/ada/calendar.json (ADA_CALENDAR_FILE default) so ada-pi
services can load it without a YAML dependency.

Lane rendering (--instance): member lanes keep their own registry file
(calendar-<instance>.json via ADA_CALENDAR_FILE in the lane env). The
`calendar.lanes` map declares the file name + default write provider per
lane; --instance filters `providers:` to the entries whose `instances:`
list names the lane, so a member lane's file carries only her providers
(own-identity + any shared read-providers).

Usage:
  render-calendar-providers.py                    # render calendar.json (all providers)
  render-calendar-providers.py --instance kk      # render calendar-kk.json (kk providers only)
  render-calendar-providers.py --host idc03       # render + scp to a host
  render-calendar-providers.py --instance kk --host idc03
  render-calendar-providers.py --check            # diff current file vs rendered
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
CONFIG_DIR = Path.home() / ".config/ada"
DEFAULT_OUT = CONFIG_DIR / "calendar.json"


def load() -> dict:
    data = yaml.safe_load(SSOT.read_text())
    calendar = data.get("calendar")
    if not isinstance(calendar, dict) or not calendar.get("providers"):
        raise SystemExit(f"{SSOT}: no 'calendar.providers' map found")
    return calendar


def render(calendar: dict, instance: str | None = None) -> dict:
    """Registry JSON for one file. `lanes` is a render-time key and is
    stripped from the output; with --instance the provider map is filtered
    to that lane and `write:` resolves from lanes.<instance>.write."""
    lanes = calendar.get("lanes") or {}
    out = {k: v for k, v in calendar.items() if k != "lanes"}
    if instance:
        lane = lanes.get(instance) or {}
        providers = {
            name: p for name, p in (out.get("providers") or {}).items()
            if instance in (p.get("instances") or [])
        }
        if not providers:
            raise SystemExit(f"no providers declare instances: [{instance}] — nothing to render")
        write = lane.get("write")
        if write is not None and write not in providers:
            raise SystemExit(f"lanes.{instance}.write={write} names no provider in the lane set")
        out["providers"] = providers
        out["write"] = write if write is not None else (
            out.get("write") if out.get("write") in providers else None)
    return {"source": str(SSOT), "calendar": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", help="render the per-lane file for this ADA_INSTANCE_ID "
                                       "(providers filtered to the lane; default: all providers -> calendar.json)")
    ap.add_argument("--host", help="render locally then scp to this SSH host")
    ap.add_argument("--output", type=Path, help="local output path (default: ~/.config/ada/<lanes file or calendar[-instance].json>)")
    ap.add_argument("--check", action="store_true", help="diff current file vs rendered, exit 1 on drift")
    args = ap.parse_args()

    calendar = load()
    rendered = render(calendar, instance=args.instance)

    if args.output:
        out = args.output
    elif args.instance:
        lane_file = ((calendar.get("lanes") or {}).get(args.instance) or {}).get("file") \
            or f"calendar-{args.instance}.json"
        out = CONFIG_DIR / lane_file
    else:
        out = DEFAULT_OUT

    text = json.dumps(rendered, indent=2, sort_keys=True) + "\n"

    if args.check:
        target = out
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
        remote = f"~/.config/ada/{out.name}"
        subprocess.run(["ssh", args.host, "mkdir -p ~/.config/ada"], check=True)
        subprocess.run(["scp", "-q", tmp, f"{args.host}:{remote}"], check=True)
        Path(tmp).unlink()
        print(f"rendered {len(rendered['calendar']['providers'])} providers -> {args.host}:{remote}")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"rendered {len(rendered['calendar']['providers'])} providers -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
