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

Per-host model (2026-10-05): each fleet host runs this on its own
systemd user timer (`--self`, installed by install-log-shipper.sh) and
posts straight to MDDB — no ssh hop that can die silently on tailscale
auth expiry. The central tony-omen ada-review-refresh run stays as a
fallback lane over ssh. Both lanes share the same remote cursor files,
so whichever runs first ships, the other reports 0 (no double-posting —
keys are deterministic per line).

michael-ha can't host a local shipper (ssh lands in the Alpine core-ssh
addon — no python3/systemd/journalctl; supervisor only serves text
logs). It's pulled via `ha host logs` over key-auth ssh by a dedicated
timer on tony-dell; dedup is a collector-side ts+hash state file since
there's no journald cursor.

Usage:
  log-shipper.py                          # all hosts, user+system journals
  log-shipper.py --self                   # this host only (per-host timer)
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
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_HOSTS = ["idc01", "idc02", "idc03", "mn01", "tony-dell",
                 "tony-omen", "michael-ha"]
LOCAL_NAMES = {"tony-omen", "localhost", ""}
# Hosts with no local runtime for the shipper — michael-ha ssh lands in
# the core-ssh addon container (Alpine, no python3/systemd/journalctl).
# Pulled via `ha host logs` text stream instead.
HA_CLI_HOSTS = {"michael-ha"}
# Non-default ssh targets — (target, extra ssh args). michael-ha needs
# the dedicated key + root (addon container); not tailscale-ssh auth, so
# a tailscale auth expiry can't break it.
SSH_TARGETS = {
    "michael-ha": ("root@michael-ha",
                   ["-i", os.path.expanduser(
                       os.environ.get("HA_SSH_KEY",
                                      "~/.ssh/michael-ha"))]),
}
# Ops telemetry goes to mddb-ops when configured — keeps host-logs
# (the largest collection) off the leader's vector index.
# Default = live MDDB leader (idc03 tailnet IP; docs' "idc01" label is
# stale — the leader moved and 100.74.146.0 no longer serves MDDB).
MDDB_URL = (os.environ.get("MDDB_OPS_URL")
            or os.environ.get("MDDB_BASE_URL",
                              "http://100.102.134.91:11023/v1")).rstrip("/")
COLLECTION = os.environ.get("LOG_COLLECTION", "host-logs")
# one doc per host in a sidecar collection — the ship heartbeat that
# logs-kanban judges silence/unreachable/backlog against. Same-key upsert
# keeps it at ~1 revision per host per run; not per-line bloat.
STATE_COLLECTION = os.environ.get("LOG_STATE_COLLECTION",
                                  "host-logs-state")

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
    "Started podman-", "Stopped podman-",  # per-transaction container scopes —
]                                          # podman churn is not a restart event


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


def _local_name() -> str:
    """Fleet name of the machine we're running on — fleet hostnames
    already match (tony-dell, idc01, ...); LOG_SHIP_HOST overrides."""
    return os.environ.get("LOG_SHIP_HOST") or \
        socket.gethostname().split(".")[0]


def _is_local(host: str) -> bool:
    return host in LOCAL_NAMES or host == _local_name()


def _ssh(host: str, remote: str, timeout: int = 120) -> str:
    if _is_local(host):
        return _run(["bash", "-c", remote], timeout)
    target, extra = SSH_TARGETS.get(host, (host, []))
    return _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 *extra, target, remote], timeout)


def _cursor_path(user: bool) -> str:
    return f"~/.cache/log-shipper-{'user' if user else 'sys'}.cursor"


# `ha host logs` line: "2026-10-05 15:06:34.360 homeassistant systemd[1]: msg"
HA_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \S+ "
    r"([^:\[\s]+)(?:\[\d+\])?: (.*)$")


def _ha_state_file(host: str) -> Path:
    return Path.home() / ".cache" / f"log-shipper-ha-{host}.json"


def _journal_ha(host: str) -> list[dict]:
    """ha-cli hosts: `ha host logs` text tail — the supervisor exposes no
    journald cursor protocol, so dedup is (ts watermark, boundary hashes)
    kept in a collector-side state file. Rows carry a JSON cursor
    snapshot so the write-back-after-post rule still holds."""
    out = _ssh(host, "ha host logs -n 1500 --no-progress 2>/dev/null",
               timeout=60)
    st = {}
    try:
        st = json.loads(_ha_state_file(host).read_text())
    except Exception:
        pass
    last_ts = st.get("ts", "")
    max_ts = last_ts
    boundary = list(st.get("seen", []))
    rows = []
    for ln in out.splitlines():
        m = HA_LINE.match(ln.strip())
        if not m:
            continue
        raw_ts, ident, msg = m.groups()
        if not msg.strip():
            continue
        kind = classify(msg)
        if not kind:
            continue
        # journal-gatewayd renders in the HAOS host's TZ (UTC)
        try:
            ts = datetime.datetime.fromisoformat(
                raw_ts.replace(" ", "T")).replace(
                    tzinfo=datetime.timezone.utc
                ).isoformat(timespec="seconds")
        except Exception:
            continue
        h = hashlib.sha1((ident + ts + msg).encode()).hexdigest()[:8]
        if ts < last_ts or (ts == last_ts and h in boundary):
            continue
        if ts > max_ts:
            max_ts, boundary = ts, []
        if ts == max_ts:
            boundary.append(h)
        try:
            rt = str(int(datetime.datetime.fromisoformat(ts)
                       .timestamp() * 1e6))
        except Exception:
            rt = ""
        rows.append({"key": f"hostlog/{host}/{rt[-12:]}-{h}",
                     "host": host, "journal": "sys",
                     "unit": ident, "ts": ts, "kind": kind,
                     "cursor": json.dumps({"ts": max_ts,
                                           "seen": boundary}),
                     "line": msg.strip()[:400]})
    return rows


def _save_ha_state(host: str, cursor_json: str) -> None:
    """Collector-side dedup file for ha-cli hosts (the remote addon has
    no persistent $HOME)."""
    try:
        _ha_state_file(host).parent.mkdir(parents=True, exist_ok=True)
        _ha_state_file(host).write_text(cursor_json)
    except Exception as e:
        print(f"warn: {host}: ha state save failed: {e}",
              file=sys.stderr)


def _journal(host: str, user: bool) -> list[dict]:
    """json lines since last SHIPPED cursor; cursor file is read-only
    here — written back by ship() after posts succeed."""
    scope = "--user" if user else "--system"
    cur = _cursor_path(user)
    # --grep filters at journal level — on noisy hosts (idc01's user
    # journal = days of uvicorn INFO spam) piping the full journal into
    # grep blew past the ssh timeout and silently yielded 0 rows, hiding
    # every user-unit log on the VPSes. Requires systemd >=243.
    out = _ssh(
        host,
        f"mkdir -p ~/.cache; "
        f"if [ -s {cur} ]; then "
        f"journalctl {scope} -o json --no-pager --cursor=\"$(cat {cur})\" "
        f"--grep='{GREP}' --case-sensitive=false; "
        f"else journalctl {scope} -o json --no-pager --since '7 days ago' "
        f"--grep='{GREP}' --case-sensitive=false; "
        f"fi 2>/dev/null | tail -3000",
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


def _reachable(host: str) -> bool:
    """Cheap probe so a dead ssh hop (tailscale auth check, host down)
    is distinguishable from a healthy-but-quiet host in the state doc."""
    probe = ("ha host logs -n 1 --no-progress >/dev/null 2>&1 && echo ok"
             if host in HA_CLI_HOSTS else "echo ok")
    return "ok" in _ssh(host, probe, timeout=15)


def ship(host: str, dry: bool, max_docs: int) -> dict:
    sent = fail = scanned = 0
    journals = {"user": 0, "sys": 0}
    ha = host in HA_CLI_HOSTS
    lane = ("ha-cli-ssh" if ha else
            "local" if _is_local(host) else "ssh")
    if not _reachable(host):
        return {"host": host, "shipped": 0, "failed": 0, "scanned": 0,
                "reachable": False, "journals": journals, "lane": lane,
                "error": "ha-cli probe failed" if ha else
                         "ssh probe failed"}
    # ha-cli hosts have a single host journal; others run user+system.
    sides = [(False, _journal_ha(host))] if ha else \
            [(user, _journal(host, user)) for user in (True, False)]
    for user, rows in sides:
        scanned += len(rows)
        journals["user" if user else "sys"] = len(rows)
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
            if ha:
                _save_ha_state(host, last_ok)
            else:
                _save_cursor(host, user, last_ok)
        if fail:
            break
    return {"host": host, "shipped": sent, "failed": fail,
            "scanned": scanned, "reachable": True, "lane": lane,
            "journals": journals,
            "error": "mddb add failed" if fail else ""}


def post_state(r: dict) -> None:
    """Upsert the per-host ship heartbeat. Runs even when shipped=0 — a
    quiet host and a broken shipper must not look identical."""
    _post("/add", {
        "collection": STATE_COLLECTION, "key": f"ship/{r['host']}",
        "lang": "en",
        "contentMd": json.dumps(r),
        "meta": {"host": [r["host"]], "kind": ["ship-state"],
                 "ts": [datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds")]}}, timeout=10)


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
    ap.add_argument("--self", dest="self_host", action="store_true",
                    help="ship only this machine's journals — fleet name "
                         "from LOG_SHIP_HOST or hostname (per-host timer "
                         "mode)")
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

    hosts = [_local_name()] if args.self_host else \
        [x.strip() for x in args.hosts.split(",") if x.strip()]
    for h in hosts:
        try:
            r = ship(h, args.dry_run, args.max_docs)
            print(f"{r['host']}: {r['shipped']} shipped "
                  f"({r['scanned']} lines matched, {r['failed']} failed)"
                  + ("" if r.get("reachable") else " — unreachable"))
            if not args.dry_run:
                post_state(r)
        except Exception as e:
            print(f"warn: {h}: {e}", file=sys.stderr)
            if not args.dry_run:
                post_state({"host": h, "shipped": 0, "failed": 0,
                            "scanned": 0, "reachable": False,
                            "journals": {}, "error": str(e)[:200]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
