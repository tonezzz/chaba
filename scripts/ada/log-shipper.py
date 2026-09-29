#!/usr/bin/env python3
"""Log shipper (L0.5): interesting journald lines -> MDDB host-logs.

Incremental, cursor-based: a cursor file per (host, journal) on the
REMOTE host holds the last SHIPPED position. journalctl is invoked with
--cursor (read-only — never --cursor-file, which would advance past
unshipped lines); after a run we write back the cursor of the last line
actually posted, so failures and dry runs replay cleanly next time.
Filtered server-side to warn-level-and-worse classes (error / oom / panic
/ failed / restart / killed) — the same families the digest collectors
use, so volume stays ~hundreds/day, not journal scale.

Docs land in collection "host-logs" as {contentMd: line, meta: {host,
journal, unit, ts, kind}}. Key = hostlog/<host>/<rt_us>-<hash8> (unique
per emission — never a re-add, so no HNSW tombstone churn).

MDDB-down tolerant: posts with a short timeout and stops at the first
failure (lines are ordered — a shipped-cursor gap would silently drop
lines); the remote cursor only advances past lines confirmed shipped.

Usage:
  log-shipper.py                          # all hosts, user+system journals
  log-shipper.py --hosts idc01 --dry-run
  log-shipper.py --prune-days 14          # retention sweep (delete old docs)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_HOSTS = ["idc01", "mn01", "tony-dell", "tony-omen"]
LOCAL_NAMES = {"tony-omen", "localhost", ""}
MDDB_URL = os.environ.get("MDDB_BASE_URL",
                          "http://100.74.146.0:11023/v1").rstrip("/")
COLLECTION = os.environ.get("LOG_COLLECTION", "host-logs")

# server-side pre-filter (cheap, keeps ssh payload small)
GREP = ("error|fail|oom|kill|panic|warn|refus|restart|Started |Stopped |"
        "timeout|denied|critical|emerg|alert")
# client-side classifier — ordered, first match wins
KINDS = [
    ("oom",    re.compile(r"oom[-_ ]?kill|Out of memory|Killed process",
                          re.I)),
    ("panic",  re.compile(r"panic", re.I)),
    ("failed", re.compile(r"Failed|failure|failed with result", re.I)),
    ("restart", re.compile(r"\b(Started|Stopped|Scheduled restart job)\b")),
    ("deny",   re.compile(r"denied|refused", re.I)),
    ("error",  re.compile(r"error|critical|alert|emerg", re.I)),
]
DROP = [
    "function_call result",          # transcript dumps, not real events
    "[RATELIMIT]",                   # tailscaled log-suppression noise
    "session opened", "session closed", "pam_",
    "remote-only, kept)", "voice, kept)",  # ada-memory-sync status lines —
    "remote-only, kept",                   # filenames in them (…-failed.yml)
    "kept)",                               # were being misclassified 'failed'
]


def classify(line: str) -> str | None:
    if any(d in line for d in DROP):
        return None
    for kind, rx in KINDS:
        if rx.search(line):
            return kind
    return None


def _run(cmd: list[str], timeout: int) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return ""


def _ssh(host: str, remote: str, timeout: int = 120) -> str:
    if host in LOCAL_NAMES:
        return _run(["bash", "-c", remote], timeout)
    return _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 host, remote], timeout)


def _cursor_path(user: bool) -> str:
    return f"~/.cache/log-shipper-{'user' if user else 'sys'}.cursor"


def _journal(host: str, user: bool) -> list[dict]:
    """json lines since last SHIPPED cursor; cursor file is read-only
    here — written back by ship() after posts succeed."""
    scope = "--user" if user else "--system"
    cur = _cursor_path(user)
    out = _ssh(
        host,
        f"mkdir -p ~/.cache; "
        f"if [ -s {cur} ]; then "
        f"journalctl {scope} -o json --no-pager --cursor=\"$(cat {cur})\"; "
        f"else journalctl {scope} -o json --no-pager --since '7 days ago'; "
        f"fi 2>/dev/null | grep -aiE '{GREP}' | tail -3000",
        timeout=150)
    rows = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            e = json.loads(ln)
        except Exception:
            continue
        msg = e.get("MESSAGE")
        if not isinstance(msg, str) or not msg.strip():
            continue
        kind = classify(msg)
        if not kind:
            continue
        unit = (e.get("_SYSTEMD_USER_UNIT") or e.get("_SYSTEMD_UNIT")
                or e.get("UNIT") or e.get("SYSLOG_IDENTIFIER") or "?")
        rt = e.get("__REALTIME_TIMESTAMP")
        try:
            ts = datetime.datetime.fromtimestamp(
                int(rt) / 1e6, datetime.timezone.utc
            ).isoformat(timespec="seconds")
        except Exception:
            ts = ""
        cursor = e.get("__CURSOR", "")
        h = hashlib.sha1((unit + ts + msg).encode()).hexdigest()[:8]
        key = f"hostlog/{host}/{str(rt or cursor)[-12:]}-{h}"
        rows.append({"key": key, "host": host,
                     "journal": "user" if user else "sys",
                     "unit": unit, "ts": ts, "kind": kind,
                     "cursor": cursor,
                     "line": msg.strip()[:400]})
    return rows


def _post(path: str, payload: dict, timeout: int = 15) -> bool:
    try:
        req = urllib.request.Request(
            f"{MDDB_URL}{path}", data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return True
    except Exception:
        return False


def _save_cursor(host: str, user: bool, cursor: str) -> None:
    _ssh(host, f"mkdir -p ~/.cache; printf '%s' '{cursor}' "
               f"> {_cursor_path(user)}", timeout=30)


def ship(host: str, dry: bool, max_docs: int) -> dict:
    sent = fail = scanned = 0
    for user in (True, False):
        rows = _journal(host, user)
        scanned += len(rows)
        last_ok = ""
        for r in rows:
            if sent >= max_docs:
                break
            if dry:
                sent += 1
                continue
            if not _post("/add", {
                    "collection": COLLECTION, "key": r["key"],
                    "lang": "en",
                    "contentMd":
                        f"`{r['ts']}` [{r['unit']}] {r['line']}",
                    "meta": {"host": [r["host"]],
                             "journal": [r["journal"]],
                             "unit": [r["unit"]], "ts": [r["ts"]],
                             "kind": [r["kind"]]}}):
                fail += 1
                # ordered lines — stop here; everything after last_ok
                # replays next run
                print(f"warn: {host}: mddb add failed — stopping "
                      f"(cursor replays unshipped)", file=sys.stderr)
                break
            sent += 1
            last_ok = r["cursor"]
        if not dry and last_ok:
            _save_cursor(host, user, last_ok)
        if fail:
            break
    return {"host": host, "shipped": sent, "failed": fail,
            "scanned": scanned}


def prune(days: int) -> int:
    """Delete host-log docs older than N days (meta.ts < cutoff)."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=days)).isoformat()
    skip, deleted = 0, 0
    while True:
        try:
            req = urllib.request.Request(
                f"{MDDB_URL}/search",
                data=json.dumps({"collection": COLLECTION, "query": "",
                                 "limit": 100, "offset": skip}).encode(),
                headers={"content-type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                page = json.loads(r.read())
        except Exception as e:
            print(f"warn: prune list failed: {e}", file=sys.stderr)
            return deleted
        if not page:
            break
        for d in page:
            ts = ((d.get("meta") or {}).get("ts") or [""])[0]
            if ts and ts < cutoff:
                if _post("/delete", {"collection": COLLECTION,
                                        "key": d["key"],
                                        "lang": d.get("lang", "en")}):
                    deleted += 1
        if len(page) < 100:
            break
        skip += 100
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hosts", default=",".join(DEFAULT_HOSTS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-docs", type=int, default=500,
                    help="cap docs shipped per host per run")
    ap.add_argument("--prune-days", type=int, default=0,
                    help="delete host-logs docs older than N days, then exit")
    args = ap.parse_args()

    if args.prune_days:
        print(f"pruned {prune(args.prune_days)} docs older than "
              f"{args.prune_days}d")
        return 0

    for h in [x.strip() for x in args.hosts.split(",") if x.strip()]:
        try:
            r = ship(h, args.dry_run, args.max_docs)
            print(f"{r['host']}: {r['shipped']} shipped "
                  f"({r['scanned']} lines matched, {r['failed']} failed)")
        except Exception as e:
            print(f"warn: {h}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
