#!/usr/bin/env python3
"""Apply a bench_profiles tool surface to a dev-lane ada env file.

The bench counterpart to render-tool-profiles.py: persons.<x>.tools is
the production profile; bench_profiles.<name> (same SSOT file) is a
named experiment surface for a -dev lane. This script renders the same
managed block format and merges it into the target env file on the
profile's host, then restarts the instance service.

Usage:
  kk-bench-env.py --list                       # show bench_profiles
  kk-bench-env.py --profile kk-cms-only        # render to stdout (dry)
  kk-bench-env.py --profile kk-cms-only --apply  # write env + restart
  kk-bench-env.py --profile kk-parity --apply    # restore parity surface
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-persons.yml"
BLOCK_BEGIN = "# >>> chaba-rendered: ada-tool-profile"
BLOCK_END = "# <<< chaba-rendered: ada-tool-profile"
_MANAGED_VARS = ("ADA_INCLUDED_TOOLS", "ADA_EXCLUDED_TOOLS")


def load_bench_profiles() -> dict[str, dict]:
    data = yaml.safe_load(SSOT.read_text())
    return data.get("bench_profiles") or {}


def render_block(name: str, prof: dict) -> str:
    lines = [f"{BLOCK_BEGIN} (bench_profiles.{name} @ {SSOT.name})"]
    inc = [str(t) for t in prof.get("include") or []]
    exc = [str(t) for t in prof.get("exclude") or []]
    if inc:
        lines.append("ADA_INCLUDED_TOOLS=" + ",".join(inc))
    if exc:
        lines.append("ADA_EXCLUDED_TOOLS=" + ",".join(exc))
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def merge_block(text: str, block: str) -> str:
    """Replace/append the managed block; retire hand-written copies of the
    managed vars that sit outside it (last block wins under systemd)."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(BLOCK_BEGIN):
            skipping = True
            continue
        if stripped.startswith(BLOCK_END):
            skipping = False
            continue
        if not skipping and any(stripped.startswith(v + "=")
                               for v in _MANAGED_VARS):
            out.append(f"# migrated to managed block below: {stripped}\n")
            continue
        if not skipping:
            out.append(line)
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    return "".join(out) + ("\n" if out and out[-1].strip() else "") + block


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    args = ap.parse_args()

    profiles = load_bench_profiles()
    if args.list:
        for name, prof in profiles.items():
            inc = prof.get("include") or []
            print(f"{name}: {prof.get('env_file')}@{prof.get('host')} "
                  f"({len(inc)} tools)")
        return 0

    if not args.profile or args.profile not in profiles:
        print("pick a profile:", ", ".join(sorted(profiles)),
              file=sys.stderr)
        return 2
    prof = profiles[args.profile]
    block = render_block(args.profile, prof)

    if not args.apply:
        sys.stdout.write(block)
        return 0

    host = prof.get("host") or "idc03"
    env_file = prof["env_file"]
    service = f"ada-{prof.get('instance') or args.profile}.service"

    # fetch current env, merge locally, write back, restart
    cur = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host,
         f"cat ~/.config/secrets/{env_file}"],
        capture_output=True, text=True, check=True).stdout
    merged = merge_block(cur, block)
    if merged == cur:
        print(f"UNCHANGED {env_file}")
    else:
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write(merged)
        subprocess.run(["scp", "-o", "BatchMode=yes", tmp.name,
                        f"{host}:~/.config/secrets/{env_file}"],
                       check=True)
        print(f"UPDATED {env_file} on {host}")
    if not args.no_restart:
        subprocess.run(["ssh", "-o", "BatchMode=yes", host,
                        f"systemctl --user restart {service} && sleep 2 "
                        f"&& systemctl --user is-active {service}"],
                       check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
