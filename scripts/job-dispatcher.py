#!/usr/bin/env python3
"""Chaba job dispatcher — runs dispatch:dispatcher jobs from ssot.jobs.yml.

Fired by chaba-jobs.timer (1-min tick). For each enabled dispatcher job on
this host, runs it if `every:` has elapsed since last_run. State and
results follow ssot.reports.yml conventions.

Usage:
  job-dispatcher.py [--host tony_dell] [--dry-run]
"""
import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/infrastructure/ssot.jobs.yml"
UNIT_S = {"s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400}


def dur_s(v) -> int:
    import re

    m = re.match(r"^(\d+)(min|s|m|h|d)?$", str(v).strip())
    return int(m.group(1)) * UNIT_S.get(m.group(2) or "s", 1)


def detect_host() -> str:
    return socket.gethostname().split(".")[0].replace("-", "_")


def expand(s: str) -> str:
    return os.path.expandvars(s.replace("%h", str(Path.home())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=detect_host())
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    man = yaml.safe_load(MANIFEST.read_text())
    cfg = man["config"]
    state_dir = Path(expand(cfg["state_dir"]))
    state_dir.mkdir(parents=True, exist_ok=True)
    results_path = Path(expand(cfg["results"]))
    state_file = state_dir / "state.json"

    with open(state_file, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        state = json.loads(fh.read() or "{}")

        now = time.time()
        failed = []
        for j in man["jobs"]:
            if (
                j.get("host") != args.host
                or j.get("dispatch") != "dispatcher"
                or not j.get("enabled", True)
            ):
                continue
            jid = j["id"]
            interval = dur_s(j["every"])
            last = state.get(jid, {}).get("last_run", 0)
            if now - last < interval:
                continue
            cmd = expand(j["exec"])
            timeout = dur_s(j.get("timeout", "5m"))
            if args.dry_run:
                print(f"due {jid} (every {interval}s, last {int(now-last)}s ago)")
                continue
            t0 = time.time()
            try:
                r = subprocess.run(
                    cmd,
                    shell=True,
                    timeout=timeout,
                    cwd=expand(j["cwd"]) if j.get("cwd") else None,
                    env={**os.environ, **{k: str(v) for k, v in (j.get("env") or {}).items()}},
                    capture_output=True,
                    text=True,
                )
                ok, code = r.returncode == 0, r.returncode
                err = (r.stderr or "")[-500:]
            except subprocess.TimeoutExpired:
                ok, code, err = False, 124, f"timeout {timeout}s"
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "name": jid,
                "command": cmd,
                "ok": ok,
                "exit_code": code,
                "duration_ms": int((time.time() - t0) * 1000),
                "host": args.host,
            }
            results_path.parent.mkdir(parents=True, exist_ok=True)
            with open(results_path, "a") as rf:
                rf.write(json.dumps(rec) + "\n")
            state[jid] = {"last_run": t0 if ok else last, "ok": ok, "exit_code": code}
            if not ok:
                failed.append(jid)
                print(f"FAIL {jid} exit={code} {err.strip()[:200]}")
            else:
                print(f"ok   {jid} {rec['duration_ms']}ms")

        if not args.dry_run:
            fh.seek(0)
            fh.truncate()
            json.dump(state, fh)
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
