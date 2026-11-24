#!/usr/bin/env python3
"""Denial-streak circuit breaker for headless `opencode run` dispatch
units (card runner-dispatch-no-timeout / OPS-0999 follow-up).

The dispatch lanes launch `opencode run --format json ... | tee
events.jsonl` under systemd-run. RuntimeMaxSec bounds wall-clock, but a
model stuck in a permission-denial loop (the 2026-10-30 nemotron run:
77 tool calls / 60 denials on a 420s fixture) burns the whole budget
retrying calls the permission layer will never allow — and headless
`doom_loop=ask` can't escalate to a human. This guard sits in the
pipeline, tees the child's combined output to the events file and to
its own stdout (same shape as `| tee`), and counts the streak of
consecutive tool-permission denials. A completed tool call resets the
streak; non-tool events (text/step noise between retries) do not —
the loop is defined by denied *tool calls*, not by event adjacency.

On trip: writes --marker JSON, SIGTERMs the child (SIGKILL after a
grace), drains briefly, exits 3. The unit's exit_code then records a
normal nonzero failure and the closeout audit sees the denial trail
in events.jsonl exactly as before.

Usage:
    opencode_stream_guard.py --events PATH [--max-streak N]
        [--marker PATH] [--kill-grace S] -- CMD [ARGS...]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_DEFAULT_MAX_STREAK = 10
_KILL_GRACE_S = 8.0


def _deny_re():
    """DENY_HINT_RE from opencode_profiles — imported lazily so the
    guard still runs (with a narrower built-in pattern) if the profiles
    module can't load in a stripped worktree."""
    try:
        import opencode_profiles as ocp
        return ocp.DENY_HINT_RE
    except Exception:
        import re
        return re.compile(
            r"prevent|denied|deny|not permitted|permission|"
            r"specified a rule", re.I)


def _is_denial(part: dict, deny_re) -> bool:
    st = part.get("state") or {}
    if st.get("status") != "error":
        return False
    return bool(deny_re.search(
        str(st.get("error") or st.get("output") or "")))


def _is_tool_done(part: dict) -> bool:
    return bool(part.get("tool")) and \
        (part.get("state") or {}).get("status") == "completed"


def guard_stream(child_stdout, events_path: Path, max_streak: int,
                 marker: Path | None, deny_re,
                 out=None) -> tuple[int, dict]:
    """Pump child stdout lines -> events file + `out` (default sys.stdout).
    Returns (lines_seen, breaker_record_or_None)."""
    out = out if out is not None else sys.stdout
    streak = 0
    lines = 0
    breaker = None
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", buffering=1) as ev:
        for line in child_stdout:
            lines += 1
            ev.write(line)
            out.write(line)
            out.flush()
            try:
                part = json.loads(line).get("part") or {}
            except Exception:
                part = {}
            if part.get("tool"):
                if _is_denial(part, deny_re):
                    streak += 1
                elif _is_tool_done(part):
                    streak = 0
            if streak >= max_streak:
                breaker = {"tripped": True, "streak": streak,
                           "max_streak": max_streak,
                           "at": datetime.now(timezone.utc).isoformat(),
                           "events": str(events_path)}
                break
    return lines, breaker


def _terminate(proc: subprocess.Popen, grace_s: float) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        return
    try:
        proc.kill()
        proc.wait(timeout=grace_s)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--events", required=True, type=Path)
    ap.add_argument("--max-streak", type=int,
                    default=int(os.environ.get(
                        "OPENCODE_DENIAL_STREAK_MAX",
                        str(_DEFAULT_MAX_STREAK))))
    ap.add_argument("--marker", type=Path, default=None)
    ap.add_argument("--kill-grace", type=float, default=_KILL_GRACE_S)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        ap.error("no command after --")
    if args.max_streak < 1:
        ap.error("--max-streak must be >= 1")

    deny_re = _deny_re()
    # stderr merges into the event stream exactly like the historical
    # `2>&1 | tee` — audit_events tolerates non-JSON lines.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    lines, breaker = guard_stream(proc.stdout, args.events,
                                  args.max_streak, args.marker, deny_re)
    rc = proc.poll()
    if breaker is not None:
        if args.marker:
            try:
                args.marker.parent.mkdir(parents=True, exist_ok=True)
                args.marker.write_text(json.dumps(breaker, indent=1))
            except OSError:
                pass
        print(f"opencode_stream_guard: denial streak "
              f"{breaker['streak']} >= {args.max_streak} after "
              f"{lines} events — terminating child", file=sys.stderr,
              flush=True)
        _terminate(proc, args.kill_grace)
        # drain whatever the child flushed before dying so the events
        # file keeps the full trail
        try:
            for line in proc.stdout:
                with args.events.open("a", buffering=1) as ev:
                    ev.write(line)
                sys.stdout.write(line)
                sys.stdout.flush()
        except Exception:
            pass
        return 3
    try:
        proc.wait(timeout=args.kill_grace)
    except subprocess.TimeoutExpired:
        _terminate(proc, args.kill_grace)
    return proc.returncode if proc.returncode is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
