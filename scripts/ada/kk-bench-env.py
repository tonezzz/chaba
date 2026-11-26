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
  kk-bench-env.py --profile kk-cms-only --check  # compare, exit 1 on drift
  kk-bench-env.py --profile kk-cms-only --apply  # backup, write, verify, restart
  kk-bench-env.py --profile kk-parity --apply    # restore parity surface

Apply safety (2026-11-24):
  - refuses any profile whose env_file is not a *-dev env on kk-dev
  - shows a secret-free tool-level diff before writing
  - keeps a timestamped remote backup (last 5) before every write
  - reads the env back after writing and verifies the managed block
  - restarts the service and checks /api/health on the declared port
  - on ANY failure restores the backup and restarts the old surface
    (--no-auto-restore disables this for debugging only)
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

SSOT = Path(__file__).resolve().parents[2] / "docs/ssot/apps/ssot.apps.ada-persons.yml"
BLOCK_BEGIN = "# >>> chaba-rendered: ada-tool-profile"
BLOCK_END = "# <<< chaba-rendered: ada-tool-profile"
KNOB_BEGIN = "# >>> chaba-rendered: ada-env-knobs"
KNOB_END = "# <<< chaba-rendered: ada-env-knobs"
_MANAGED_VARS = ("ADA_INCLUDED_TOOLS", "ADA_EXCLUDED_TOOLS")
_BACKUP_KEEP = 5
_HEALTH_PATH = "/api/health"
_HEALTH_WAIT_S = 45  # dev startup has been observed to take ~10s


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


def render_knobs_block(name: str, prof: dict) -> str:
    """Render the second managed block: non-tool env knobs for the lane.

    Session prime injects past-session context even when every memory tool
    is stripped, so a bench profile can declare e.g.
    `env_knobs: {ADA_SESSION_PRIME: "0"}` to make the "CMS-only" claim real.
    """
    knobs = prof.get("env_knobs") or {}
    if not knobs:
        return ""
    lines = [f"{KNOB_BEGIN} (bench_profiles.{name} @ {SSOT.name})"]
    for key in sorted(knobs):
        lines.append(f"{key}={knobs[key]}")
    lines.append(KNOB_END)
    return "\n".join(lines) + "\n"


def managed_text(text: str) -> str:
    """Both managed blocks, in file order, or '' when neither exists."""
    out = extract_block(text)
    knobs = ""
    lines: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(KNOB_BEGIN):
            inside, lines = True, [line]
            continue
        if inside:
            lines.append(line)
            if stripped.startswith(KNOB_END):
                knobs = "".join(lines)
                break
    return out + knobs


def desired_text(tool_block: str, knob_block: str) -> str:
    return tool_block + knob_block


def merge_knobs_block(text: str, block: str) -> str:
    """Replace/append the env-knob block; retire hand-written copies."""
    knob_keys: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            knob_keys.append(stripped.split("=", 1)[0])
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(KNOB_BEGIN):
            skipping = True
            continue
        if stripped.startswith(KNOB_END):
            skipping = False
            continue
        if not skipping and any(stripped.startswith(k + "=") for k in knob_keys):
            out.append(f"# migrated to managed block below: {stripped}\n")
            continue
        if not skipping:
            out.append(line)
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    if not block:
        return "".join(out)
    return "".join(out) + ("\n" if out and out[-1].strip() else "") + block


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


def extract_block(text: str) -> str:
    """Return the complete managed block from an env file, or ''."""
    lines: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(BLOCK_BEGIN):
            inside, lines = True, [line]
            continue
        if inside:
            lines.append(line)
            if stripped.startswith(BLOCK_END):
                break
    if lines and lines[-1].strip().startswith(BLOCK_END):
        return "".join(lines)
    return ""


def parse_block(block: str) -> tuple[set[str], set[str], str]:
    """Tool sets + profile label from a managed block (no secret values)."""
    inc: set[str] = set()
    exc: set[str] = set()
    label = ""
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(BLOCK_BEGIN):
            label = stripped[len(BLOCK_BEGIN):].strip()
        elif stripped.startswith("ADA_INCLUDED_TOOLS="):
            inc = {x for x in stripped.split("=", 1)[1].split(",") if x}
        elif stripped.startswith("ADA_EXCLUDED_TOOLS="):
            exc = {x for x in stripped.split("=", 1)[1].split(",") if x}
    return inc, exc, label


def block_status(current: str, desired: str) -> bool:
    """True iff BOTH live managed blocks match the declared profile."""
    return managed_text(current) == desired


def parse_knobs(text: str) -> dict[str, str]:
    """Only the env-knob block's KEY=value lines — not tool-list vars."""
    out: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(KNOB_BEGIN):
            inside = True
            continue
        if inside and stripped.startswith(KNOB_END):
            break
        if inside and "=" in stripped and not stripped.startswith("#"):
            key, value = stripped.split("=", 1)
            out[key] = value
    return out


def describe_changes(current: str, desired: str) -> str:
    """Secret-free description of tool-list and env-knob changes."""
    if current == desired:
        return "unchanged"
    ci, ce, cl = parse_block(current)
    di, de, dl = parse_block(desired)
    out = []
    if cl != dl:
        out.append(f"profile: {cl or '(none)'} -> {dl}")
    for title, old, new in (("included", ci, di), ("excluded", ce, de)):
        added, removed = sorted(new - old), sorted(old - new)
        if added:
            out.append(f"{title} +: {', '.join(added)}")
        if removed:
            out.append(f"{title} -: {', '.join(removed)}")
    co, dn = parse_knobs(current), parse_knobs(desired)
    if co != dn:
        changes = [f"{k}={dn[k]}" if k in dn else f"{k}=removed"
                   for k in sorted(set(co) | set(dn))
                   if co.get(k) != dn.get(k)]
        out.append("env knobs: " + ", ".join(changes))
    return "; ".join(out) or "block text changed (tool lists identical)"


def assert_dev_profile(name: str, prof: dict) -> None:
    """Defence in depth: bench profiles must never target a prod env."""
    env_file = str(prof.get("env_file") or "")
    if not env_file.endswith("-dev.env"):
        raise SystemExit(
            f"refusing {name}: env_file {env_file!r} is not a *-dev env")
    if prof.get("instance") != "kk-dev":
        raise SystemExit(
            f"refusing {name}: instance {prof.get('instance')!r} is not kk-dev")


def _ssh(host: str, command: str, *, capture: bool = True):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, command],
                          check=True, capture_output=capture, text=True)


def _home_path(filename: str) -> str:
    """Path for an ssh *shell* command: $HOME expands, name is quoted."""
    return f"$HOME/.config/secrets/{shlex.quote(filename)}"


def _scp_path(env_file: str) -> str:
    """Path for scp: the remote side expands ~ in the destination."""
    return f"~/.config/secrets/{env_file}"


def remote_read(host: str, env_file: str) -> str:
    return _ssh(host, f"cat {_home_path(env_file)}").stdout


def remote_backup(host: str, env_file: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{env_file}.bak.{stamp}"
    _ssh(host, f"cp -p -- {_home_path(env_file)} {_home_path(backup)}",
         capture=False)
    _ssh(host,
         f"ls -1t $HOME/.config/secrets/{shlex.quote(env_file)}.bak.* "
         f"2>/dev/null | tail -n +{_BACKUP_KEEP + 1} | xargs -r rm -f --",
         capture=False)
    return backup


def remote_write(host: str, env_file: str, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write(content)
        tmpname = tmp.name
    try:
        subprocess.run(["scp", "-o", "BatchMode=yes", tmpname,
                        f"{host}:{_scp_path(env_file)}"], check=True)
    finally:
        Path(tmpname).unlink(missing_ok=True)


def remote_restore(host: str, env_file: str, backup: str) -> None:
    _ssh(host,
         f"cp -p -- {_home_path(backup)} {_home_path(env_file)}",
         capture=False)


def restart(host: str, service: str, port: int | None = None) -> None:
    """Restart, then wait for the service AND its health endpoint.

    A plain `sleep 2` is not enough: ada-kk-dev has taken ~10s to bind :8009.
    Polling happens on the remote host so one ssh call covers the whole wait.
    """
    cmd = (f"systemctl --user restart {shlex.quote(service)} && "
           f"systemctl --user is-active --quiet {shlex.quote(service)}")
    if port:
        url = f"http://127.0.0.1:{int(port)}{_HEALTH_PATH}"
        cmd += (f" && for i in $(seq 1 {_HEALTH_WAIT_S}); do "
                f"curl -fs --max-time 2 -o /dev/null {shlex.quote(url)} "
                f"&& exit 0; sleep 1; done; "
                f"echo 'health check timed out on :{int(port)}' >&2; exit 1")
    else:
        cmd += " && sleep 2"
    _ssh(host, cmd, capture=False)


def check(host: str, env_file: str, desired: str, name: str) -> int:
    try:
        current = remote_read(host, env_file)
    except subprocess.CalledProcessError as exc:
        print(f"cannot read {env_file} on {host}: {exc}", file=sys.stderr)
        return 2
    if block_status(current, desired):
        print(f"OK {name}: live managed blocks match {env_file}@{host}")
        return 0
    print(f"DRIFT {name}: "
          f"{describe_changes(managed_text(current), desired)}",
          file=sys.stderr)
    return 1


def apply(host: str, env_file: str, desired: str, name: str, prof: dict,
          *, no_restart: bool, no_auto_restore: bool) -> int:
    service = f"ada-{prof.get('instance') or name}.service"
    try:
        current = remote_read(host, env_file)
    except subprocess.CalledProcessError as exc:
        print(f"cannot read {env_file} on {host}: {exc}", file=sys.stderr)
        return 2

    if block_status(current, desired):
        print(f"UNCHANGED {env_file}@{host}")
        return 0

    print(f"CHANGE {name}: "
          f"{describe_changes(managed_text(current), desired)}")
    try:
        backup = remote_backup(host, env_file)
    except subprocess.CalledProcessError as exc:
        print(f"backup failed, refusing to write: {exc}", file=sys.stderr)
        return 1

    try:
        merged = merge_knobs_block(merge_block(current, render_block(
            name, prof)), render_knobs_block(name, prof))
        remote_write(host, env_file, merged)
        if not block_status(remote_read(host, env_file), desired):
            raise RuntimeError("post-write verification failed")
        if no_restart:
            print(f"applied config only (--no-restart); backup {backup}")
            return 0
        restart(host, service, prof.get("port"))
        print(f"APPLIED {name}; {service} active; backup {backup}")
        return 0
    except Exception as exc:
        if no_auto_restore:
            print(f"FAILED ({exc}); auto-restore disabled — "
                  f"env left in the new state (backup {backup})",
                  file=sys.stderr)
            return 1
        print(f"FAILED ({exc}); restoring {backup}", file=sys.stderr)
        try:
            remote_restore(host, env_file, backup)
            if not no_restart:
                restart(host, service)
            print("restored previous env + service", file=sys.stderr)
        except Exception as restore_exc:
            print(f"RESTORE ALSO FAILED: {restore_exc} — backup is {backup}",
                  file=sys.stderr)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="compare live managed block with the profile (exit 1 on drift)")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--no-auto-restore", action="store_true",
                    help="debugging only: leave the new env in place on failure")
    args = ap.parse_args()

    profiles = load_bench_profiles()
    if args.list:
        for name, prof in profiles.items():
            inc = prof.get("include") or []
            print(f"{name}: {prof.get('env_file')}@{prof.get('host')} "
                  f"({len(inc)} tools)")
        return 0

    if not args.profile or args.profile not in profiles:
        print("pick a profile:", ", ".join(sorted(profiles)), file=sys.stderr)
        return 2
    name = args.profile
    prof = profiles[name]
    assert_dev_profile(name, prof)
    block = render_block(name, prof)
    desired = desired_text(block, render_knobs_block(name, prof))

    if not args.apply and not args.check:
        sys.stdout.write(desired)
        return 0

    host = prof.get("host") or "idc03"
    env_file = prof["env_file"]
    if args.check:
        return check(host, env_file, desired, name)
    return apply(host, env_file, desired, name, prof,
                 no_restart=args.no_restart,
                 no_auto_restore=args.no_auto_restore)


if __name__ == "__main__":
    raise SystemExit(main())
