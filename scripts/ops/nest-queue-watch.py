#!/usr/bin/env python3
"""nest-queue-watch — one-shot poller for the ada-nest Colab queue.

Reads the queue state off Drive (via rclone on a proxy host — the
watcher host needs no rclone/Drive creds itself) and pushes a message
to Tony's TG relay (ada-ha lane /send, loopback on idc03) each time a
pack is claimed, finishes, or fails. State lives in a small json file
so repeat ticks only report new lines.

Intended as a dispatcher job (every: 1m) on idc03:
  - Drive read : ssh idc02 rclone cat/lsf gdrive:ada-nest/...
  - notify     : board_notify tg -> http://127.0.0.1:8911/send

Events reported (from the newest queue/log-*.txt or legacy
queue/run-*.out.log):
  == <name>: run            -> taken
  == <name>: DONE           -> finished (includes duration)
  == <name>: FAIL|PREP FAILED -> failed
  QUEUE-DRAINED             -> queue finished
  lease acquired / lost     -> runner up / fenced out
Plus a stall alert when the heartbeat is >STALE_S old mid-job.

Kill switch (easy off): touch ~/.config/nest-queue-watch.off — every
tick exits silently while it exists. `rm` it to resume. Or set
NEST_QUEUE_WATCH=off in the job env.

Env:
  NEST_QUEUE_WATCH          off disables (default on)
  NEST_QUEUE_WATCH_STATE    state file, default
                            ~/.local/state/nest-queue-watch.json
  NEST_QUEUE_WATCH_OFF_FILE kill-switch path, default
                            ~/.config/nest-queue-watch.off
  NEST_QUEUE_SSH            rclone proxy host (default idc02)
  NEST_QUEUE_REMOTE         rclone remote root (default gdrive:ada-nest)
  NEST_QUEUE_STALE_S        heartbeat staleness alert (default 240)
  BOARD_NOTIFY_CHANNEL      board_notify channel (default tg)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get(
    "NEST_QUEUE_WATCH_STATE",
    HOME / ".local/state/nest-queue-watch.json"))
OFF_FILE = Path(os.environ.get(
    "NEST_QUEUE_WATCH_OFF_FILE",
    HOME / ".config/nest-queue-watch.off"))
SSH_HOST = os.environ.get("NEST_QUEUE_SSH", "idc02")
REMOTE = os.environ.get("NEST_QUEUE_REMOTE", "gdrive:ada-nest").rstrip("/")
Q = f"{REMOTE}/queue"
STALE_S = int(os.environ.get("NEST_QUEUE_STALE_S", "240"))
MAX_CATCHUP = 5  # don't burst-notify ancient history on first tick
LOG_NAME = re.compile(r"^(?:log|run)-(?P<stamp>\d{8}-\d{4})")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
import board_notify  # noqa: E402


def remote(*args: str) -> str:
    """rclone over ssh to the proxy host; log failures and return ''."""
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
         SSH_HOST, "~/.local/bin/rclone " + " ".join(args)],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"nest-queue-watch: remote {' '.join(args[:2])} failed: "
              f"{r.stderr.strip()[:300]}", file=sys.stderr)
        return ""
    return r.stdout


def newest_log(listing: str) -> str:
    """Select the newest current or legacy runner log by its timestamp."""
    candidates = []
    for line in listing.splitlines():
        name = line.strip()
        match = LOG_NAME.match(name)
        if match:
            candidates.append((match.group("stamp"), name))
    return max(candidates, default=("", ""))[1]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"log": "", "seen": 0, "hb_job": "", "stalled": False}


def save_state(st: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st))
    except OSError as e:
        print(f"state write failed: {e}", file=sys.stderr)


def notify(title: str, body: str = "") -> bool:
    ok = board_notify.send(f"[nest] {title}", body, url="")
    if not ok:
        print(f"nest-queue-watch: notification was not accepted: {title}",
              file=sys.stderr)
    return ok


EVENT = re.compile(
    r"^(?P<t>\d\d:\d\d:\d\d) (?:== (?P<job>\S+): "
    r"(?P<ev>prep|run|DONE|FAIL"
    r"|PREP FAILED)(?P<rest>.*)|(?P<other>QUEUE-DRAINED.*|lease acquired:.*"
    r"|lease lost.*|fenced.*))")


def fmt_event(m: re.Match) -> str | None:
    job, ev, rest = m.group("job"), m.group("ev"), m.group("rest") or ""
    if job:
        if ev == "prep":
            return f"{job} — preparing"
        if ev == "run":
            return f"{job} — started"
        if ev == "DONE":
            return f"{job} — done{rest}"
        return f"{job} — {ev.lower()}"
    other = m.group("other") or ""
    if other.startswith("QUEUE-DRAINED"):
        return "queue drained"
    if other.startswith("lease acquired"):
        return f"runner up ({other.split(':', 1)[1].strip()})"
    return f"runner: {other.strip()}"


def main() -> int:
    if os.environ.get("NEST_QUEUE_WATCH") == "off" or OFF_FILE.exists():
        return 0
    st = load_state()
    hb = remote("cat", f"{Q}/heartbeat").split()
    hb_ts, hb_job, hb_phase = 0.0, "", ""
    if len(hb) >= 3:
        try:
            hb_ts, hb_job, hb_phase = float(hb[0]), hb[1], hb[2]
        except ValueError:
            pass

    # Current detached runner uses log-*.txt; retain legacy logs during
    # migration so a format change cannot silently stop notifications.
    listing = remote("lsf", Q, "--files-only", "--include",
                     "run-*.out.log", "--include", "log-*.txt")
    cur = newest_log(listing)

    events: list[str] = []
    if cur:
        lines = remote("cat", f"{Q}/{cur}").splitlines()
        if st.get("log") != cur:
            # new run file — only catch up on its tail
            st["log"], st["seen"] = cur, max(0, len(lines) - MAX_CATCHUP)
        for line in lines[st.get("seen", 0):]:
            m = EVENT.match(line.strip())
            if m:
                msg = fmt_event(m)
                if msg:
                    events.append(msg)
        st["seen"] = len(lines)

    now = time.time()
    if hb_ts and now - hb_ts > STALE_S and hb_phase in ("run", "prep") \
            and not st.get("stalled"):
        events.append(
            f"runner silent {int(now - hb_ts)}s mid-{hb_job}/{hb_phase}")
        st["stalled"] = True
    elif hb_ts and now - hb_ts <= STALE_S:
        st["stalled"] = False

    delivered = all(notify(e) for e in events)
    if delivered:
        save_state(st)
    else:
        # Keep the old cursor so failed Telegram delivery is retried next tick.
        print("nest-queue-watch: retaining event cursor for retry",
              file=sys.stderr)
    if events and delivered:
        print("sent: " + " | ".join(events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
