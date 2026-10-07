#!/usr/bin/env python3
"""stack-preflight — walk a stack manifest against a live host and report
which onboarding gates pass before you deploy. The manifest contract:

    stacks/<host>/<svc>/stack.yml:
      id, host, description
      verify:    shell command run on the host to prove the service is live
      secrets:   paths that must exist (checked, contents never touched)
      requires:  ssh/edge deps — "ssh:<alias>" or "tool:<binary>"
      state:     dirs that must exist (created if missing)
      ports:     host ports the service binds ("8080", "10.0.0.1:8080",
                 "53/udp") — merged with PublishPort= lines from *.container
                 quadlets in the same dir. A bound port passes only when
                 the service's own unit is already active (re-deploy);
                 a bound port with the unit down is a squatter -> FAIL.
      unit:      systemd unit name (default "<id>.service") — used to tell
                 "port held by me" apart from "port squatted".
      restore:   restore procedure text (documentation only)
      status:    deployed | standby | retired
                   standby — gates run normally; verify skipped by default
                   retired — single gate: the unit must NOT be active

Usage:
    stack-preflight.py stacks/idc03/secrets-backup/stack.yml
    stack-preflight.py stacks/idc01/mddb-follower/stack.yml --apply-verify
    stack-preflight.py stacks            # sweep every stack.yml (drift audit)

Exit code 0 when every gate passes. Designed to be the gate between "I
wrote the quadlet" and "it is deployed".
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

GREEN, RED, YELLOW, DIM = "\033[32m", "\033[31m", "\033[33m", "\033[2m"
RESET = "\033[0m"

REACHABLE: dict[str, bool] = {}


def ssh(host: str, cmd: str, timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
             host, cmd],
            capture_output=True, text=True, timeout=timeout + 10)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "ssh timeout"


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = f"{GREEN}ok{RESET}" if ok else f"{RED}FAIL{RESET}"
    extra = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  [{mark}] {label}{extra}")
    return ok


def note(label: str, detail: str = "") -> None:
    extra = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  [{YELLOW}note{RESET}] {label}{extra}")


def host_port(publish: str, manifest: bool = False) -> tuple[str, str] | None:
    """Host port + proto from a PublishPort= or manifest ports[] entry.

    PublishPort= is [ip:]host:container[/proto] -> host field.
    Manifest ports[] is a HOST port: '8080', '10.0.0.1:8080', '53/udp'.
    """
    publish = publish.split(" — ")[0].strip().rstrip("/")
    if not publish:
        return None
    proto = "tcp"
    if "/" in publish:
        publish, proto = publish.rsplit("/", 1)
    fields = publish.split(":")
    if manifest and len(fields) == 2 and not fields[0].isdigit():
        cand = fields[1]           # "ip:port" -> port
    elif len(fields) >= 2:
        cand = fields[-2]          # ip:host:container -> host
    else:
        cand = fields[0]           # bare port
    return (cand, proto) if cand.isdigit() else None


def service_ports(mdir: Path, m: dict) -> list[tuple[str, str, str]]:
    """(port, proto, source) — manifest ports[] + quadlet PublishPort=."""
    out: list[tuple[str, str, str]] = []
    for p in m.get("ports", []) or []:
        hp = host_port(str(p), manifest=True)
        if hp:
            out.append((hp[0], hp[1], "manifest"))
    for quad in sorted(mdir.glob("*.container")):
        for line in quad.read_text().splitlines():
            line = line.strip()
            if line.startswith("PublishPort="):
                hp = host_port(line.split("=", 1)[1])
                if hp:
                    out.append((hp[0], hp[1], quad.name))
    seen, uniq = set(), []
    for port, proto, src in out:
        if (port, proto) not in seen:
            seen.add((port, proto))
            uniq.append((port, proto, src))
    return uniq


def unit_active(host: str, unit: str) -> str:
    rc, out = ssh(host, f"systemctl --user is-active {shlex.quote(unit)}")
    return out.splitlines()[0].strip() if out else "unknown"


def preflight(path: Path, apply_verify: bool) -> bool:
    try:
        m = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        print(f"{path}: bad yaml: {e}")
        return False
    host = m["host"]
    svc_id = m.get("id", path.parent.name)
    unit = m.get("unit", f"{svc_id}.service")
    status = m.get("status", "deployed")
    print(f"preflight {svc_id} on {host} (status: {status})")

    if host not in REACHABLE:
        rc, _ = ssh(host, "hostname")
        REACHABLE[host] = rc == 0
    if not REACHABLE[host]:
        print(f"  [{RED}FAIL{RESET}] host {host} unreachable over ssh")
        return False

    fails = 0

    if status == "retired":
        state = unit_active(host, unit)
        fails += not check(f"{unit} not running", state != "active",
                           f"is-active={state}")
        print(f"\n{svc_id}: {'PASS' if not fails else 'FAILED'}\n")
        return not fails

    # Gate: secrets exist (existence only — never read values)
    for s in m.get("secrets", []):
        p = s.split(" — ")[0].strip()
        p = "$HOME/" + shlex.quote(p[2:]) if p.startswith("~/") \
            else shlex.quote(p)
        rc, out = ssh(host, f"test -e {p} && echo y")
        fails += not check(f"secret {p}", rc == 0 and out == "y")

    # Gate: requires — ssh edges + tool deps
    for req in m.get("requires", []):
        req = req.split(" — ")[0].strip()
        if req.startswith("ssh:"):
            target = req[4:]
            rc, out = ssh(host, f"ssh -o BatchMode=yes -o ConnectTimeout=8 "
                                f"{shlex.quote(target)} hostname")
            fails += not check(f"requires {req}", rc == 0, out[:60])
        elif req.startswith("tool:"):
            rc, _ = ssh(host, f"command -v {shlex.quote(req[5:])}")
            fails += not check(f"requires {req}", rc == 0)
        elif req.startswith("remote-tool:"):
            # dep that must exist on a TARGET the service pushes to
            target, _, tool = req[12:].partition(":")
            rc, out = ssh(host, f"ssh -o BatchMode=yes -o ConnectTimeout=8 "
                                f"{shlex.quote(target)} command -v "
                                f"{shlex.quote(tool)}")
            fails += not check(f"requires {req}", rc == 0, out[:60])
        elif req.startswith("tcp:"):
            # "tcp:host:port" — outbound connectivity from the service host
            hostport = req[4:].rsplit(":", 1)
            rc, out = ssh(host, f"timeout 5 bash -c 'echo > /dev/tcp/"
                                f"{hostport[0]}/{hostport[1]}' && echo y")
            fails += not check(f"requires {req}", rc == 0 and "y" in out)
        else:
            note(f"requires {req}", "manual check")

    # Gate: state dirs (create if missing — that's the fix, not a fail)
    for st in m.get("state", []):
        p = st.split(" — ")[0].strip()
        p = "$HOME/" + shlex.quote(p[2:]) if p.startswith("~/") \
            else shlex.quote(p)
        rc, out = ssh(host, f"test -d {p} && echo present")
        if rc == 0 and "present" in out:
            fails += not check(f"state {p}", True, "present")
        else:
            rc, out = ssh(host, f"mkdir -p {p}")
            fails += not check(f"state {p}", rc == 0,
                               "created" if rc == 0 else out[:60])

    # Gate: ports free — bound is ok only when this unit holds it (re-deploy)
    ports = service_ports(path.parent, m)
    for port, proto, src in ports:
        flag = "tln" if proto == "tcp" else "uln"
        rc, out = ssh(host, f"ss -{flag}H 'sport = :{port}' | head -1")
        if not out:
            fails += not check(f"port :{port}/{proto}", True, f"free ({src})")
            continue
        state = unit_active(host, unit)
        fails += not check(f"port :{port}/{proto}", state == "active",
                           f"bound; {unit} is-active={state}")

    # Lint: gitignored-dir shadow names (card
    # dispatch-gitignore-shadow-guard — the 2026-10-10 .venv incident:
    # `.venv/` ignored only dirs, so a committed `.venv` symlink slipped
    # in and clobbered the real venv on deploy). For each state dir with
    # a .gitignore, warn when a single-segment `X/` pattern has no bare
    # `X`/`/X` counterpart to catch a tracked file of that name.
    warned_gi = set()
    for st in m.get("state", []):
        path = st.split(" — ")[0].strip()
        if not path or path in warned_gi:
            continue
        warned_gi.add(path)
        q = ("$HOME/" + shlex.quote(path[2:])) \
            if path.startswith("~/") else shlex.quote(path)
        rc, gi = ssh(host, f"test -f {q}/.gitignore && cat {q}/.gitignore")
        if rc != 0:
            continue
        lines = [l.strip() for l in gi.splitlines()]
        dir_only = set()
        bare = set()
        for l in lines:
            if not l or l.startswith(("#", "!")):
                continue
            l = l.lstrip("/")
            if re.fullmatch(r"[A-Za-z0-9_.-]+/", l):
                dir_only.add(l[:-1])
            elif "/" not in l:
                bare.add(l)
        for name in sorted(dir_only - bare):
            print(f"  [{YELLOW}warn{RESET}] gitignore {path}: '{name}/' "
                  f"only ignores dirs — a tracked file/symlink '{name}' "
                  f"would shadow it (add bare '{name}')")

    # Gate: verify command (only meaningful once deployed)
    if apply_verify and m.get("verify"):
        if status == "deployed":
            rc, out = ssh(host, m["verify"], timeout=60)
            fails += not check("verify", rc == 0, out[:80])
        else:
            note("verify", f"skipped — status {status}")

    print(f"\n{svc_id}: {'PASS' if not fails else f'{fails} gate(s) failed'}\n")
    return not fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest",
                    help="path to stack.yml, or a dir to sweep "
                         "(e.g. stacks or stacks/idc03)")
    ap.add_argument("--apply-verify", action="store_true",
                    help="also run the verify command on the host "
                         "(deployed services only)")
    args = ap.parse_args()

    p = Path(args.manifest)
    if p.is_dir():
        manifests = sorted(p.rglob("stack.yml"))
        if not manifests:
            print(f"no stack.yml under {p}")
            return 1
    else:
        manifests = [p]

    results = [preflight(mf, args.apply_verify) for mf in manifests]
    if len(manifests) > 1:
        ok = sum(results)
        print(f"sweep: {ok}/{len(manifests)} manifests green")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
