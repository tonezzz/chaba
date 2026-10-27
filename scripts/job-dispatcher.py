#!/usr/bin/env python3
"""Chaba job dispatcher — runs dispatch:dispatcher jobs from ssot.jobs.yml.

Fired by chaba-jobs.timer (1-min tick). For each enabled dispatcher job on
this host, runs it if `every:` has elapsed since the last attempt and any
failure backoff (state next_retry) has passed. State and results follow
ssot.reports.yml conventions.

Failure policy (card fix-chaba-jobs-network-scan-failure-isolation,
2026-10-27): dispatcher jobs are NONCRITICAL by default — a failing job is
isolated to itself:

- it cannot starve other due jobs on the same tick (per-job try/except);
- it backs off exponentially: interval * factor**(failures-1), floor = the
  job's own interval, ceiling = config.failure_policy.backoff_cap;
- it persists last_success / last_failure / failure_count / next_retry in
  config.state_dir/state.json and appends a results record each attempt;
- it files ONE focus-inbox alert per failure episode via board-api /inbox
  (local docs/ssot/focus-inbox/job-fail-<host>-<jid>.yml fallback, removed
  again on recovery);
- it does NOT fail the chaba-jobs.service tick.

`critical: true` in the manifest opts a job back into exit-nonzero
semantics (systemd marks the tick failed). Success resets failure_count,
next_retry and the alert flag.

Usage:
  job-dispatcher.py [--host tony_dell] [--dry-run]
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/infrastructure/ssot.jobs.yml"
INBOX_DIR = REPO / "docs/ssot/focus-inbox"
BOARD_API = "https://idc03.taila0626a.ts.net:10000"
UNIT_S = {"s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400}
# exit_code used when the dispatcher itself failed to run the job (no
# subprocess exit status exists) — sysexits EX_SOFTWARE.
EXEC_ERR = 70


def dur_s(v) -> int:
    m = re.match(r"^(\d+)(min|s|m|h|d)?$", str(v).strip())
    return int(m.group(1)) * UNIT_S.get(m.group(2) or "s", 1)


def detect_host() -> str:
    return socket.gethostname().split(".")[0].replace("-", "_")


def expand(s: str) -> str:
    return os.path.expandvars(s.replace("%h", str(Path.home())))


def backoff_delay(interval: int, failure_count: int, factor: float,
                  cap: int) -> int:
    """Exponential backoff anchored on the job's own interval: the first
    failure retries on the normal cadence, later failures double, and the
    ceiling never drops below the interval (a daily job never retries
    faster than daily no matter how small the cap)."""
    delay = interval * factor ** max(0, failure_count - 1)
    return int(min(delay, max(cap, interval)))


def run_job(j: dict, cmd: str, timeout: int):
    """Execute one job's command. Returns (ok, exit_code, err_tail)."""
    # stale-name pre-clean: if a previous run was timeout-killed
    # mid `podman run`, the client died before --rm could fire and
    # the dead container keeps the name -> every later run exits
    # 125 forever (incident OPS-0531, 2026-10-13)
    if "podman" in cmd:
        for cname in re.findall(r"--name[ =]([\w.:-]+)", cmd):
            subprocess.run(
                ["podman", "rm", "-f", cname],
                capture_output=True, timeout=15,
            )
    r = subprocess.run(
        cmd,
        shell=True,
        timeout=timeout,
        cwd=expand(j["cwd"]) if j.get("cwd") else None,
        env={**os.environ,
             **{k: str(v) for k, v in (j.get("env") or {}).items()}},
        capture_output=True,
        text=True,
    )
    return r.returncode == 0, r.returncode, (r.stderr or "")[-500:]


def _alert_path(inbox_dir: Path, host: str, jid: str) -> Path:
    return inbox_dir / f"job-fail-{host}-{jid}.yml"


def _post_inbox(label: str, text: str, priority: str, tags: list) -> dict:
    api = (os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
           or BOARD_API).rstrip("/")
    req = urllib.request.Request(
        f"{api}/inbox",
        data=json.dumps({
            "from": "devin", "label": label, "text": text,
            "priority": priority, "tags": tags,
            "session": "chaba-jobs-dispatcher"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def default_alert(j: dict, host: str, rec: dict, st: dict, inbox_dir: Path,
                  post_fn=_post_inbox) -> bool:
    """One deduped alert per failure episode (caller gates on
    st['alerted']). board-api /inbox is the write door; when it's
    unreachable the alert degrades to a local focus-inbox file that
    self-heals on recovery. Returns True if any path succeeded."""
    jid = j["id"]
    label = f"job-fail: {jid} on {host}"
    retry = (dt.datetime.fromtimestamp(st["next_retry"]).isoformat(
        timespec="seconds") if st.get("next_retry") else "-")
    text = (
        f"Dispatcher job '{j.get('name', jid)}' ({jid}) failed on {host} "
        f"at {rec['ts']}: exit {rec['exit_code']}\n"
        f"command: {rec['command']}\n"
        f"stderr tail: {rec.get('err', '')[:800]}\n\n"
        f"failure_count={st.get('failure_count')} — dispatcher backs off "
        f"exponentially (next retry {retry}) and this is the only alert "
        f"for the episode; recovery clears the flag. Policy: "
        f"{'CRITICAL — tick exits nonzero' if rec.get('critical') else 'noncritical — other jobs unaffected'}. "
        f"See scripts/job-dispatcher.py + ssot.jobs.yml failure_policy.")
    tags = ["ops", "chaba-jobs", "job-failure", host]
    try:
        post_fn(label, text, "high" if rec.get("critical") else "medium",
                tags)
        return True
    except Exception:
        pass
    doc = {
        "title": label,
        "subtitle": f"job-dispatcher {rec['ts']}",
        "icon": "alert",
        "focus": {
            "label": label,
            "text": text,
            "branch": "chaba",
            "priority": "high" if rec.get("critical") else "medium",
            "status": "draft",
            "tags": tags,
        },
        "ownership": {"owner": "tony", "locked": False, "lock_reason": ""},
        "source": {"date": dt.date.today().isoformat(),
                   "session": "chaba-jobs-dispatcher"},
    }
    try:
        inbox_dir.mkdir(parents=True, exist_ok=True)
        _alert_path(inbox_dir, host, jid).write_text(
            yaml.safe_dump(doc, sort_keys=False, width=120))
        return True
    except Exception:
        return False


def clear_alert(inbox_dir: Path, host: str, jid: str) -> bool:
    """Self-heal: remove a fallback alert file once the job is green."""
    try:
        p = _alert_path(inbox_dir, host, jid)
        if p.exists():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def tick(man: dict, host: str, state_file: Path, results_path: Path, *,
         now: float = None, dry_run: bool = False, run_fn=None,
         alert_fn=None, inbox_dir: Path = None, out=print) -> dict:
    """One dispatcher tick over the manifest. Returns a summary dict —
    callers convert failed_critical into the service exit code."""
    now = time.time() if now is None else now
    inbox_dir = inbox_dir or INBOX_DIR
    run_fn = run_fn or run_job
    alert_fn = alert_fn or default_alert
    policy = (man.get("config") or {}).get("failure_policy") or {}
    factor = float(policy.get("backoff_factor", 2))
    cap = dur_s(policy.get("backoff_cap", "4h"))

    fh = None
    if dry_run:
        state = json.loads(state_file.read_text() or "{}") \
            if state_file.exists() else {}
    else:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        fh = open(state_file, "a+")
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        state = json.loads(fh.read() or "{}")

    summary = {"ran": [], "failed": [], "failed_critical": [],
               "backoff": [], "state": state}
    try:
        for j in man["jobs"]:
            if (j.get("host") != host
                    or j.get("dispatch") != "dispatcher"
                    or not j.get("enabled", True)):
                continue
            jid = j["id"]
            interval = dur_s(j["every"])
            st = state.get(jid) or {}
            last = st.get("last_run", 0)
            if now - last < interval:
                continue
            retry_at = st.get("next_retry") or 0
            if now < retry_at:
                summary["backoff"].append(jid)
                out(f"backoff {jid} retry in {int(retry_at - now)}s "
                    f"(failure_count={st.get('failure_count', 0)})")
                continue
            e = j["exec"]
            cmd = " && ".join(expand(x) for x in e) \
                if isinstance(e, list) else expand(e)
            timeout = dur_s(j.get("timeout", "5m"))
            if dry_run:
                out(f"due {jid} (every {interval}s, "
                    f"last {int(now - last)}s ago)")
                continue
            t0 = now            # logical attempt time (state/scheduling)
            wall0 = time.time()  # wall clock for duration_ms only
            try:
                ok, code, err = run_fn(j, cmd, timeout)
            except subprocess.TimeoutExpired:
                ok, code, err = False, 124, f"timeout {timeout}s"
            except Exception as exc:
                # per-job isolation — a dispatcher-level error on one job
                # must not take the rest of the tick down with it
                ok, code, err = False, EXEC_ERR, \
                    f"dispatcher: {type(exc).__name__}: {exc}"
            critical = bool(j.get("critical"))
            delay = 0 if ok else backoff_delay(
                interval, st.get("failure_count", 0) + 1, factor, cap)
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "name": jid,
                "command": cmd,
                "ok": ok,
                "exit_code": code,
                "duration_ms": int((time.time() - wall0) * 1000),
                "host": host,
                "critical": critical,
                "failure_count": 0 if ok else st.get("failure_count", 0) + 1,
                "backoff_s": delay,
                "err": str(err or "")[-500:],
            }
            try:
                results_path.parent.mkdir(parents=True, exist_ok=True)
                with open(results_path, "a") as rf:
                    rf.write(json.dumps(rec) + "\n")
            except Exception as exc:
                out(f"WARN results append failed for {jid}: {exc}")

            st = dict(st)
            st["last_run"] = t0
            st["ok"], st["exit_code"] = ok, code
            if ok:
                recovered = st.get("failure_count", 0) > 0
                st.update({"last_success": t0, "failure_count": 0,
                           "next_retry": 0, "alerted": False})
                if recovered:
                    tag = "RECOVERED"
                    if clear_alert(inbox_dir, host, jid):
                        tag += " (alert cleared)"
                    out(f"{tag} {jid} {rec['duration_ms']}ms")
                else:
                    out(f"ok   {jid} {rec['duration_ms']}ms")
            else:
                st.update({"last_failure": t0,
                           "failure_count": rec["failure_count"],
                           "next_retry": t0 + delay})
                summary["failed"].append(jid)
                if critical:
                    summary["failed_critical"].append(jid)
                if not st.get("alerted"):
                    try:
                        if alert_fn(j, host, rec, st, inbox_dir):
                            st["alerted"] = True
                            st["alerted_at"] = t0
                    except Exception as exc:
                        out(f"WARN alert failed for {jid}: {exc}")
                kind = "critical" if critical else f"backoff {delay}s"
                out(f"FAIL {jid} exit={code} ({kind}) "
                    f"{str(err).strip()[:200]}")
            state[jid] = st
            summary["ran"].append(jid)
    finally:
        if fh is not None:
            fh.seek(0)
            fh.truncate()
            json.dump(state, fh)
            fh.close()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=detect_host())
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    man = yaml.safe_load(MANIFEST.read_text())
    cfg = man["config"]
    res = tick(man, args.host,
               Path(expand(cfg["state_dir"])) / "state.json",
               Path(expand(cfg["results"])),
               dry_run=args.dry_run)
    return 1 if res["failed_critical"] else 0


if __name__ == "__main__":
    sys.exit(main())
