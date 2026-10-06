#!/usr/bin/env python3
"""stack-preflight — walk a stack manifest against a live host and report
which onboarding gates pass before you deploy. The manifest contract:

    stacks/<host>/<svc>/stack.yml:
      id, host, description
      verify:    shell command run on the host to prove the service is live
      secrets:   paths that must exist (checked, contents never touched)
      requires:  ssh/edge deps — "ssh:<alias>" or "tool:<binary>"
      state:     dirs that must exist (created if missing)
      restore:   restore procedure text (documentation only)

Usage:
    stack-preflight.py stacks/idc03/secrets-backup/stack.yml
    stack-preflight.py stacks/idc01/mddb-follower/stack.yml --apply-verify

Exit code 0 when every gate passes. Designed to be the gate between "I
wrote the quadlet" and "it is deployed".
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

GREEN, RED, YELLOW, DIM = "\033[32m", "\033[31m", "\033[33m", "\033[2m"
RESET = "\033[0m"


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", help="path to stack.yml")
    ap.add_argument("--apply-verify", action="store_true",
                    help="also run the verify command on the host "
                         "(deployed services only)")
    args = ap.parse_args()

    m = yaml.safe_load(Path(args.manifest).read_text())
    host = m["host"]
    print(f"preflight {m.get('id', '?')} on {host}")

    rc, _ = ssh(host, "hostname")
    if rc != 0:
        print(f"  [{RED}FAIL{RESET}] host {host} unreachable over ssh")
        return 1

    fails = 0

    # Gate: secrets exist (existence only — never read values)
    for s in m.get("secrets", []):
        path = s.split(" — ")[0].strip()
        if path.startswith("~/"):
            path = "$HOME/" + shlex.quote(path[2:])
        else:
            path = shlex.quote(path)
        rc, out = ssh(host, f"test -e {path} && echo y")
        fails += not check(f"secret {path}", rc == 0 and out == "y")

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
            print(f"  [{YELLOW}note{RESET}] requires {req} (manual check)")

    # Gate: state dirs (create if missing — that's the fix, not a fail)
    for st in m.get("state", []):
        path = st.split(" — ")[0].strip()
        if path.startswith("~/"):
            path = "$HOME/" + shlex.quote(path[2:])
        else:
            path = shlex.quote(path)
        rc, out = ssh(host, f"mkdir -p {path} && echo y")
        fails += not check(f"state {path}", rc == 0 and out == "y",
                           "created" if rc == 0 else out[:60])

    # Gate: verify command (only meaningful once deployed)
    if args.apply_verify and m.get("verify"):
        rc, out = ssh(host, m["verify"], timeout=60)
        fails += not check("verify", rc == 0, out[:80])

    print(f"\n{m.get('id')}: {'PASS' if not fails else f'{fails} gate(s) failed'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
