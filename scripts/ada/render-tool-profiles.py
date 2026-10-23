#!/usr/bin/env python3
"""Render per-persona Ada tool profiles into instance env files.

Source:  docs/ssot/apps/ssot.apps.ada-persons.yml — persons.<key>.tools
Output:  a managed block in ~/.config/secrets/<env_file> on the instance
         host (ADA_INCLUDED_TOOLS keep-list / ADA_EXCLUDED_TOOLS drop-list)
Lint:    warns on declared tools in NEITHER list and on names that do
         not resolve to ada-voice's declared surface or alias table —
         the anti-rot tripwire for tool merges/renames.

Usage:
  render-tool-profiles.py                      # render all profiles to stdout
  render-tool-profiles.py --lint               # coverage/stale warnings only
  render-tool-profiles.py --host idc03 --apply # merge managed blocks on a host
  render-tool-profiles.py --local --apply      # merge into local env files
  render-tool-profiles.py --host idc03 --check # exit 1 when a block drifts
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-persons.yml"
ADA_PI = Path(os.environ.get("ADA_PI_REPO") or "~/CascadeProjects/ada-voice").expanduser()
BLOCK_BEGIN = "# >>> chaba-rendered: ada-tool-profile"
BLOCK_END = "# <<< chaba-rendered: ada-tool-profile"
_MANAGED_VARS = ("ADA_INCLUDED_TOOLS", "ADA_EXCLUDED_TOOLS")


def load_profiles() -> dict[str, dict]:
    data = yaml.safe_load(SSOT.read_text())
    out = {}
    for key, person in (data.get("persons") or {}).items():
        tools = (person or {}).get("tools") or {}
        if not isinstance(tools, dict):
            continue
        instance = tools.get("instance") or key
        include = [str(t) for t in (tools.get("include") or [])]
        exclude = [str(t) for t in (tools.get("exclude") or [])]
        if not include and not exclude:
            continue
        out[key] = {
            "instance": instance,
            "env_file": tools.get("env_file") or f"ada-{instance}.env",
            "host": tools.get("host"),
            "include": include,
            "exclude": exclude,
        }
    return out


def render_block(person: str, prof: dict) -> str:
    lines = [
        f"{BLOCK_BEGIN} (persons.{person} @ {SSOT.name})",
        "# edit the SSOT profile, not this file — reapplied by deploy-ada.sh",
    ]
    if prof["include"]:
        lines.append("ADA_INCLUDED_TOOLS=" + ",".join(prof["include"]))
    if prof["exclude"]:
        lines.append("ADA_EXCLUDED_TOOLS=" + ",".join(prof["exclude"]))
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def merge_env(current: str, block: str) -> str:
    """Replace/append the managed block; retire hand-written copies of the
    managed vars that sit outside it (last block wins under systemd)."""
    out, in_block, seen_block = [], False, False
    for line in current.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if stripped.startswith(BLOCK_BEGIN):
            in_block, seen_block = True, True
            out.append(block)
            continue
        if in_block:
            if stripped.startswith(BLOCK_END):
                in_block = False
            continue
        if any(stripped.startswith(f"{v}=") for v in _MANAGED_VARS):
            out.append(f"# migrated to managed block below: {stripped}\n")
            continue
        out.append(line)
    if not seen_block:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(block)
    return "".join(out)


def ada_surface() -> tuple[set[str], dict[str, str]] | None:
    """Declared tool names + runner aliases, via ada-voice's tool-lint census."""
    tl = ADA_PI / "scripts/tool-lint.py"
    if not tl.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ada_tool_lint", tl)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    surf = mod.collect_surface(ADA_PI)
    return set(surf["declared"]), dict(surf["aliases"])


def lint(profiles: dict[str, dict]) -> list[str]:
    """Declared tools in neither include nor exclude -> warning; names
    that resolve only through the alias table or not at all -> warning."""
    warns: list[str] = []
    try:
        surface = ada_surface()
    except Exception as exc:
        return [f"tool-surface census failed ({exc}) — coverage not checked"]
    if surface is None:
        return [f"no ada-voice checkout at {ADA_PI} — coverage not checked"]
    declared, aliases = surface
    for person, prof in profiles.items():
        inst = prof["instance"]
        inc, exc = set(prof["include"]), set(prof["exclude"])
        for n in sorted((inc | exc) - declared):
            seat = aliases.get(n)
            hint = f" (alias of {seat} — list the declared seat)" if seat else ""
            where = "include" if n in inc else "exclude"
            warns.append(f"{inst}: {where} name '{n}' is not a declared tool{hint}")
        for n in sorted(declared - inc - exc):
            warns.append(f"{inst}: declared tool '{n}' in neither include nor exclude")
    return warns


_SECRETISH = ("KEY", "TOKEN", "SECRET", "PASS", "CRED")


def _redact(line: str) -> str:
    """Mask env values that look secret — diffs get echoed into deploy logs."""
    if "=" in line and any(s in line.split("=", 1)[0].upper() for s in _SECRETISH):
        return line.split("=", 1)[0] + "=<redacted>"
    return line


def _remote_env_path(prof: dict) -> str:
    return f"~/.config/secrets/{prof['env_file']}"


def _read_env(host: str | None, prof: dict) -> str | None:
    if host is None:
        p = Path.home() / ".config/secrets" / prof["env_file"]
        return p.read_text() if p.is_file() else None
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
         host, f"cat {_remote_env_path(prof)} 2>/dev/null"],
        capture_output=True, text=True)
    return r.stdout if r.returncode == 0 and r.stdout else None


def _write_env(host: str | None, prof: dict, text: str) -> None:
    """Write via tmp+cat so the env file keeps its inode/perms/owner."""
    if host is None:
        p = Path.home() / ".config/secrets" / prof["env_file"]
        p.write_text(text)
        return
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(text)
        tmp = f.name
    try:
        remote_tmp = ("/tmp/." + prof["env_file"].replace("/", "__")
                      + ".rendered")
        subprocess.run(["scp", "-q", tmp, f"{host}:{remote_tmp}"], check=True)
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", host,
             f"cat {remote_tmp} > {_remote_env_path(prof)} && rm {remote_tmp}"],
            check=True)
    finally:
        Path(tmp).unlink(missing_ok=True)


def apply_profiles(host: str | None, profiles: dict[str, dict], check: bool) -> int:
    changed = 0
    for person, prof in profiles.items():
        if host is not None and prof.get("host") != host:
            continue
        current = _read_env(host, prof)
        where = host or "local"
        if current is None:
            print(f"SKIP {person}/{prof['env_file']} on {where}: env file not found")
            continue
        merged = merge_env(current, render_block(person, prof))
        if merged == current:
            print(f"UNCHANGED {person}/{prof['env_file']} on {where}")
            continue
        if check:
            print(f"DRIFT {person}/{prof['env_file']} on {where}")
            for line in difflib.unified_diff(
                    [_redact(l) for l in current.splitlines()],
                    [_redact(l) for l in merged.splitlines()], lineterm=""):
                print(line)
            changed += 1
            continue
        _write_env(host, prof, merged)
        print(f"UPDATED {person}/{prof['env_file']} on {where} "
              f"(staged — applies on next service restart)")
        changed += 1
    return 1 if (check and changed) else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", help="target host (profiles with a matching host: field)")
    ap.add_argument("--local", action="store_true", help="apply to local ~/.config/secrets/")
    ap.add_argument("--apply", action="store_true", help="merge managed blocks (also runs lint)")
    ap.add_argument("--check", action="store_true", help="diff only — exit 1 on drift")
    ap.add_argument("--lint", action="store_true", help="print coverage warnings only")
    ap.add_argument("--instance", help="restrict to one profile instance")
    args = ap.parse_args()

    profiles = load_profiles()
    if args.instance:
        profiles = {k: v for k, v in profiles.items()
                    if v["instance"] == args.instance}
    if not profiles:
        print("no tool profiles declared in", SSOT)
        return 0

    warns = lint(profiles) if (args.lint or args.apply or args.check) else []
    for w in warns:
        print(f"warn {w}", file=sys.stderr)

    if args.lint:
        return 0

    if args.apply or args.check:
        target = None if args.local else args.host
        if target is None and not args.local:
            ap.error("--apply/--check needs --host or --local")
        return apply_profiles(target, profiles, args.check)

    for person, prof in profiles.items():
        print(f"# persons.{person} -> {_remote_env_path(prof)} on {prof.get('host') or '?'}")
        print(render_block(person, prof))
    return 0


if __name__ == "__main__":
    sys.exit(main())
