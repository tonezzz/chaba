#!/usr/bin/env python3
"""Export Ada voice transcripts + session reports for offline review.

Pulls the L0/L1 layer from an Ada runtime host:
  ~/.local/share/ada/transcripts/*.md   raw transcripts (private, local-only)
  ~/.local/share/ada/reports/*.json     L1 session reports (session-report.py)
  ~/.local/share/ada/session-memory.md  rolling '## ' memory log

into the local review dir (~/.local/share/ada-review/), then runs
focus-rollup.py to refresh focus-digest.md — one command refreshes the
whole offline corpus that memory.yml's ada-sessions/ada-focus sections
read.

Privacy: transcripts can contain private details and credential-shaped
text. The output directory is intentionally outside the repo and must
never be committed. Keep it that way.

Usage:
  export-transcripts.py                    # pull idc01 (live host), rollup
  export-transcripts.py --host mn01        # standby host (transcripts only)
  export-transcripts.py --since 2026-09-20 --limit 20
  export-transcripts.py --backfill         # stage-2 LLM reports for
                                           # transcripts missing one
  export-transcripts.py --local /path      # no ssh, local dir source
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REMOTE_BASE = "~/.local/share/ada"
REMOTE_DIR = f"{REMOTE_BASE}/transcripts"
REMOTE_REPORTS = f"{REMOTE_BASE}/reports"
REMOTE_LOG = f"{REMOTE_BASE}/session-memory.md"
REMOTE_EVENTS = f"{REMOTE_BASE}/events.md"
DEFAULT_OUT = Path.home() / ".local/share/ada-review/transcripts"
ADA_SCRIPTS = Path(__file__).resolve().parent


def _ssh_ls(host: str, pattern: str) -> list[str]:
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", host,
             f"ls -1 {pattern} 2>/dev/null | sort -r"],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def _scp(host: str, remote: str, dst: Path) -> bool:
    r = subprocess.run(
        ["scp", "-q", f"{host}:{remote}", str(dst)], timeout=60)
    return r.returncode == 0


def _merge_session_log(local: Path, remote_text: str) -> int:
    """Union '## ' entries by heading; returns count of new entries."""
    def entries(text: str) -> dict[str, str]:
        out = {}
        for e in re.split(r"\n(?=## )", text):
            e = e.strip()
            if not e:
                continue
            head = e.split("\n", 1)[0].strip()
            out[head] = e
        return out

    prev = local.read_text(encoding="utf-8") if local.exists() else ""
    merged = entries(prev)
    new = 0
    for head, e in entries(remote_text).items():
        if head not in merged:
            merged[head] = e
            new += 1
    # chronological-ish order: heading is '## YYYY-MM-DD <id>'
    ordered = [merged[h] for h in sorted(merged)]
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("\n\n".join(ordered) + "\n", encoding="utf-8")
    return new


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host", default="idc01",
                    help="ada runtime host to pull from (idc01|mn01|tony-dell)")
    ap.add_argument("--local", type=Path, default=None,
                    help="read transcripts from a local dir instead of ssh")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--remote-dir", default=REMOTE_DIR)
    ap.add_argument("--since", default=None,
                    help="only transcripts dated >= YYYY-MM-DD (filename prefix)")
    ap.add_argument("--limit", type=int, default=50,
                    help="max most-recent transcripts to copy")
    ap.add_argument("--no-reports", action="store_true",
                    help="skip pulling reports/ and session-memory.md")
    ap.add_argument("--no-rollup", action="store_true",
                    help="skip focus-rollup.py refresh at the end")
    ap.add_argument("--no-ops", action="store_true",
                    help="skip journal-report.py session-ops pull")
    ap.add_argument("--ops-since", default="7 days ago",
                    help="journal window for the ops layer")
    ap.add_argument("--no-hosts", action="store_true",
                    help="skip host-report.py health sweep")
    ap.add_argument("--no-personal", action="store_true",
                    help="skip personal-tier collectors + personal-rollup.py")
    ap.add_argument("--keep-days", type=int, default=30,
                    help="prune mirrored transcripts/reports older than this "
                         "(local mirror only; remote untouched)")
    ap.add_argument("--hosts", default="idc01,mn01,tony-dell,tony-omen",
                    help="comma-separated hosts for the health sweep")
    ap.add_argument("--backfill", action="store_true",
                    help="generate stage-2 reports for transcripts missing one "
                         "(one LLM call each — slow)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    review = args.out.parent          # ~/.local/share/ada-review
    reports_dir = review / "reports"
    session_log = review / "session-memory.md"
    events_log = review / "events.md"

    # ---- transcripts ----
    if args.local is not None:
        src = args.local.expanduser()
        files = sorted(p for p in src.glob("*.md") if p.is_file())
    else:
        remote = _ssh_ls(args.host, f"{args.remote_dir}/*.md")
        if not remote and args.remote_dir == REMOTE_DIR:
            print(f"ssh listing failed or empty on {args.host}",
                  file=sys.stderr)
            return 1
        files = [Path(l) for l in remote]

    if args.since:
        files = [p for p in files if p.name >= args.since]
    files = files[: args.limit]

    copied = []
    if args.local is not None:
        for p in files:
            dst = args.out / p.name
            if not dst.exists() or dst.stat().st_size != p.stat().st_size:
                shutil.copy2(p, dst)
                copied.append(p.name)
    else:
        for p in files:
            if _scp(args.host, f"{args.remote_dir}/{p.name}",
                    args.out / p.name):
                copied.append(p.name)
    print(f"transcripts: {len(copied)} copied -> {args.out}")

    # ---- reports + session-memory.md ----
    if not args.no_reports and args.local is None:
        reports_dir.mkdir(parents=True, exist_ok=True)
        remote_reports = _ssh_ls(args.host, f"{REMOTE_REPORTS}/*.json")
        n = 0
        for rp in remote_reports:
            name = Path(rp).name
            dst = reports_dir / name
            if not dst.exists() and _scp(args.host, f"{REMOTE_REPORTS}/{name}",
                                         dst):
                n += 1
        print(f"reports: {n} new -> {reports_dir} "
              f"({len(list(reports_dir.glob('*.json')))} total)")

        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.host,
             f"cat {REMOTE_LOG} 2>/dev/null"],
            capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            added = _merge_session_log(session_log, out.stdout)
            print(f"session-memory.md: +{added} entries merged "
                  f"-> {session_log}")

        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.host,
             f"cat {REMOTE_EVENTS} 2>/dev/null"],
            capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            added = _merge_session_log(events_log, out.stdout)
            if added:
                print(f"events.md: +{added} entries merged -> {events_log}")

    # ---- backfill missing reports (optional, LLM cost) ----
    if args.backfill:
        have = {p.stem for p in reports_dir.glob("*.json")}
        missing = [p for p in sorted(args.out.glob("*.md"))
                   if p.stem not in have]
        print(f"backfill: {len(missing)} transcripts missing reports")
        for p in missing:
            r = subprocess.run(
                [sys.executable, str(ADA_SCRIPTS / "session-report.py"),
                 str(p), "--emit-session-log", str(session_log)],
                capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                print(f"  {p.name}: FAILED {r.stderr.strip()[:120]}",
                      file=sys.stderr)

    # ---- session-ops layer (journald) ----
    ops_file = review / "session-ops.jsonl"
    if not args.no_ops and args.local is None:
        r = subprocess.run(
            [sys.executable, str(ADA_SCRIPTS / "journal-report.py"),
             "--host", args.host, "--since", args.ops_since,
             "--out", str(review), "--merge-reports", str(reports_dir)],
            capture_output=True, text=True)
        print(r.stdout.strip().splitlines()[0] if r.stdout.strip()
              else f"ops: {r.stderr.strip()[:120]}")

    # ---- local mirror retention ----
    cutoff = time.time() - args.keep_days * 86400
    pruned = 0
    for p in list(args.out.glob("*.md")) + list(reports_dir.glob("*.json")):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                pruned += 1
        except OSError:
            pass
    if pruned:
        print(f"retention: pruned {pruned} mirrored files older than "
              f"{args.keep_days}d")

    # ---- host health sweep ----
    host_ops = review / "host-ops.jsonl"
    if not args.no_hosts and args.local is None:
        r = subprocess.run(
            [sys.executable, str(ADA_SCRIPTS / "host-report.py"),
             "--hosts", args.hosts, "--since", args.ops_since,
             "--out", str(review)],
            capture_output=True, text=True, timeout=300)
        print((r.stdout.strip().splitlines() or ["host sweep: no output"])[0])

    # ---- HA log sweep ----
    ha_ops = review / "ha-ops.jsonl"
    if not args.no_hosts and args.local is None:
        r = subprocess.run(
            [sys.executable, str(ADA_SCRIPTS / "ha-report.py"),
             "--since", args.ops_since],
            capture_output=True, text=True, timeout=300)
        print((r.stdout.strip().splitlines() or ["ha sweep: no output"])[0])

    # ---- personal-tier collectors + rollup (local-only, devin context) ----
    if not args.no_personal:
        for name in ("devin-report", "net-report", "ops-report",
                     "ha-events-report", "spend-report", "caddy-report",
                     "tasks-report"):
            r = subprocess.run(
                [sys.executable, str(ADA_SCRIPTS / f"{name}.py"),
                 "--out", str(review)],
                capture_output=True, text=True, timeout=300)
            first = r.stdout.strip().splitlines()
            print(first[0] if first else
                  f"{name}: {r.stderr.strip()[:120]}")
        r = subprocess.run(
            [sys.executable, str(ADA_SCRIPTS / "personal-rollup.py"),
             "--out", str(review)],
            capture_output=True, text=True, timeout=60)
        print(r.stdout.strip() or r.stderr.strip())

    # ---- rollup ----
    if not args.no_rollup:
        cmd = [sys.executable, str(ADA_SCRIPTS / "focus-rollup.py"),
               "--reports", str(reports_dir)]
        if ops_file.exists():
            cmd += ["--ops", str(ops_file)]
        if host_ops.exists():
            cmd += ["--hosts", str(host_ops)]
        if ha_ops.exists():
            cmd += ["--ha", str(ha_ops)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())

    manifest = args.out / "MANIFEST.txt"
    with manifest.open("w") as fh:
        fh.write(f"host={args.host} local={args.local or '-'} "
                 f"pulled={len(copied)}\n")
        for name in copied:
            fh.write(f"{name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
