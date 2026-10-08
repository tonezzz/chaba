#!/usr/bin/env python3
"""mddb follower apply-stall watchdog — self-heal for the silent stream stall.

Runs ON the follower host (idc02, idc01, ...) as a systemd user timer
(systemd/mddb-follower-watchdog.{service,timer}). Each run polls the leader's
/v1/replication/status and detects the silent-stall signature observed on
idc02 2026-10-06 and in the original replication wedge:

    followers[] entry for this node has
      - last_seen_at FRESH  -> gRPC stream still connected at protocol level
      - confirmed_lsn FROZEN across runs while
      - leader current_lsn > confirmed_lsn (there is data to apply)

A working stream applies continuously; a follower that is behind, connected,
and not advancing confirmed_lsn for --stall-seconds has a dead apply path
(follower replicate() blocks in stream.Recv() with no deadline and no
heartbeat — root fix lives on mddb-fork branch repl-heartbeat; this watchdog
is the mitigation until that image ships, and the safety net after it).

On detection the watchdog runs `systemctl --user restart <unit>` — restart
resumes from the persisted LSN marker (mddb >=2.15.4-lsn) and reconnects the
stream. Guards:

  - --restart-cooldown (default 900s) between restarts,
  - --max-restarts (default 3) per stall episode, then it stops acting and
    keeps reporting (manual intervention; the binlog canary on tony-dell
    pages the fleet view),
  - confirmed_lsn == 0 is NOT restarted: that means snapshot-in-flight or
    never-applied, and restarting a multi-minute verify would doom-loop.
  - follower absent from followers[] / last_seen_at stale -> stream dropped;
    not this watchdog's signature, no action (use --restart-if-absent to
    override for hosts where "absent" means "wedged before first connect").

Prints one JSON result line per run (same shape as mddb-binlog-canary.py) for
the journal. file:// URLs are accepted for testing. State lives in
--state-file so freeze duration survives timer gaps and service restarts.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LEADER_URL = "http://100.102.134.91:11023/v1/replication/status"
DEFAULT_UNIT = "mddb-follower.service"
DEFAULT_STATE = Path.home() / "var/chaba/health/mddb-follower-watchdog.json"
SEEN_FRESH_SECONDS = 120        # last_seen_at younger than this = connected
DEFAULT_STALL_SECONDS = 300     # confirmed_lsn frozen this long -> restart
DEFAULT_COOLDOWN = 900          # min seconds between restarts
DEFAULT_MAX_RESTARTS = 3        # per continuous stall episode
DEFAULT_MIN_LAG = 1             # leader must be at least this far ahead


def utcnow():
    return datetime.now(timezone.utc)


def ts_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, timeout=8):
    """Return (data, error). file:// is allowed for canned payloads."""
    try:
        if url.startswith("file://"):
            body = Path(url[7:]).read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = resp.read()
        return json.loads(body), None
    except Exception as e:
        return None, str(e)


def find_follower(data, follower_id):
    followers = data.get("followers") or []
    if isinstance(followers, dict):
        followers = list(followers.values())
    for f in followers:
        if not isinstance(f, dict):
            continue
        fid = (f.get("follower_id") or f.get("node_id") or f.get("id")
               or f.get("name"))
        if fid == follower_id:
            return f
    return None


def load_state(path):
    try:
        state = json.loads(Path(path).read_text())
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    return {}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def restart_unit(unit):
    """Restart the follower unit. Returns (ok, detail)."""
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "restart", unit],
            capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return True, f"systemctl --user restart {unit}: ok"
        return False, (f"systemctl --user restart {unit} rc={proc.returncode}: "
                       f"{(proc.stderr or proc.stdout).strip()}")
    except Exception as e:
        return False, f"restart failed: {e}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--leader-url", default=DEFAULT_LEADER_URL,
                        help="leader /v1/replication/status URL (file:// ok)")
    parser.add_argument("--follower-id",
                        default=os.environ.get("MDDB_NODE_ID"),
                        help="this node's follower_id (default: $MDDB_NODE_ID)")
    parser.add_argument("--unit", default=DEFAULT_UNIT,
                        help="user unit to restart on stall")
    parser.add_argument("--local-url", default=None,
                        help="optional follower-local status URL for metrics")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--stall-seconds", type=float,
                        default=DEFAULT_STALL_SECONDS)
    parser.add_argument("--seen-fresh-seconds", type=float,
                        default=SEEN_FRESH_SECONDS)
    parser.add_argument("--min-lag", type=float, default=DEFAULT_MIN_LAG,
                        help="min leader_lsn - confirmed_lsn to count as behind")
    parser.add_argument("--restart-cooldown", type=float,
                        default=DEFAULT_COOLDOWN)
    parser.add_argument("--max-restarts", type=int,
                        default=DEFAULT_MAX_RESTARTS)
    parser.add_argument("--restart-if-absent", action="store_true",
                        help="also restart when our entry is missing from "
                             "followers[] (default: only the connected+frozen "
                             "signature triggers)")
    parser.add_argument("--dry-run", action="store_true",
                        help="detect and report but never run systemctl")
    args = parser.parse_args()

    now = utcnow()
    now_epoch = now.timestamp()
    result = {
        "timestamp": ts_iso(now),
        "service": "mddb-follower-watchdog",
        "follower_id": args.follower_id,
        "unit": args.unit,
        "status": "unknown",
        "detail": "",
        "action": "none",
    }
    state = load_state(args.state_file)

    if not args.follower_id:
        result["status"] = "error"
        result["detail"] = "no --follower-id and MDDB_NODE_ID unset"
        print(json.dumps(result, separators=(",", ":")))
        return 0

    data, err = fetch(args.leader_url)
    if err:
        # Cannot observe the leader — pause the freeze timer rather than
        # reset it, so a flap cannot hide a real stall.
        result["status"] = "error"
        result["detail"] = f"leader fetch: {err}"
        state.update({"last_check": ts_iso(now), "last_status": "error"})
        save_state(args.state_file, state)
        print(json.dumps(result, separators=(",", ":")))
        return 0

    leader_lsn = data.get("current_lsn")
    entry = find_follower(data, args.follower_id)
    local, _ = (fetch(args.local_url) if args.local_url else (None, None))
    if local:
        result["local"] = {"current_lsn": local.get("current_lsn"),
                           "healthy": local.get("healthy"),
                           "replication_lag_ms":
                           local.get("replication_lag_ms")}

    if entry is None:
        # Stream not connected at all (or leader pruned us) — different
        # failure class than the silent stall.
        result["status"] = "absent"
        result["detail"] = (f"{args.follower_id} not in followers[] "
                            f"(leader current_lsn={leader_lsn})")
        state.pop("frozen_since_epoch", None)
        if (args.restart_if_absent and not args.dry_run
                and now_epoch - state.get("last_restart_epoch", 0)
                > args.restart_cooldown):
            ok, detail = restart_unit(args.unit)
            result["action"] = "restart"
            result["detail"] += f" | restart-if-absent: {detail}"
            if ok:
                state["last_restart_epoch"] = now_epoch
    else:
        confirmed = entry.get("confirmed_lsn")
        seen_at = entry.get("last_seen_at")
        seen_age = (now_epoch - seen_at
                    if isinstance(seen_at, (int, float)) else None)
        connected = (seen_age is not None
                     and seen_age <= args.seen_fresh_seconds)
        lag = (leader_lsn - confirmed
               if isinstance(leader_lsn, (int, float))
               and isinstance(confirmed, (int, float)) else None)
        behind = lag is not None and lag >= args.min_lag
        result["metrics"] = {
            "leader_current_lsn": leader_lsn,
            "confirmed_lsn": confirmed,
            "apply_lag_lsn": lag,
            "last_seen_age_s": (round(seen_age, 1)
                                if seen_age is not None else None),
            "connected": connected,
            "leader_status": entry.get("status"),
        }

        prev_lsn = state.get("confirmed_lsn")
        if confirmed == prev_lsn and state.get("frozen_since_epoch"):
            frozen_secs = now_epoch - state["frozen_since_epoch"]
        else:
            state["frozen_since_epoch"] = now_epoch
            frozen_secs = 0
        state["confirmed_lsn"] = confirmed
        result["metrics"]["frozen_seconds"] = int(frozen_secs)

        if confirmed == 0:
            # Snapshot in flight or never applied — restarting a long
            # verify would doom-loop. Report only.
            result["status"] = "snapshotting"
            result["detail"] = ("confirmed_lsn=0 — snapshot/apply of full "
                                "image in progress; not restarting")
        elif not connected:
            result["status"] = "disconnected"
            result["detail"] = (f"last_seen_at age "
                                f"{result['metrics']['last_seen_age_s']}s "
                                f"> {args.seen_fresh_seconds}s — stream "
                                "dropped, not the silent-stall signature")
            state.pop("frozen_since_epoch", None)
        elif not behind:
            result["status"] = "caught-up"
            result["detail"] = f"confirmed_lsn={confirmed} lag={lag}"
        elif frozen_secs < args.stall_seconds:
            result["status"] = "watching"
            result["detail"] = (f"confirmed_lsn={confirmed} frozen "
                                f"{int(frozen_secs)}s "
                                f"(< {args.stall_seconds}s), lag={lag}, "
                                f"connected")
        else:
            # THE SIGNATURE: connected, behind, frozen past threshold.
            state["restarts"] = state.get("restarts", 0)
            last_restart = state.get("last_restart_epoch", 0)
            cooled = now_epoch - last_restart > args.restart_cooldown
            result["status"] = "stalled"
            result["detail"] = (
                f"APPLY STALL: confirmed_lsn={confirmed} frozen "
                f"{int(frozen_secs)}s while connected "
                f"(last_seen {result['metrics']['last_seen_age_s']}s ago), "
                f"lag={lag} vs leader {leader_lsn}")
            if state["restarts"] >= args.max_restarts:
                result["action"] = "gave-up"
                result["detail"] += (f" | {args.max_restarts} restarts "
                                     "already tried — needs human")
            elif not cooled:
                result["action"] = "cooldown"
                result["detail"] += (f" | cooldown "
                                     f"{int(args.restart_cooldown - (now_epoch - last_restart))}s "
                                     "left")
            elif args.dry_run:
                result["action"] = "would-restart"
            else:
                ok, detail = restart_unit(args.unit)
                result["action"] = "restart" if ok else "restart-failed"
                result["detail"] += f" | {detail}"
                state["last_restart_epoch"] = now_epoch
                state["restarts"] = state["restarts"] + 1
                # New episode bookkeeping: after a restart the LSN should
                # advance; the freeze clock resets so a still-dead stream
                # is re-detected rather than instantly re-fired.
                state["frozen_since_epoch"] = now_epoch

        # Recovered (confirmed_lsn moved) -> reset episode counters.
        if frozen_secs == 0 and behind is not None:
            state["restarts"] = 0
    state.update({"last_check": ts_iso(now),
                  "last_status": result["status"]})
    save_state(args.state_file, state)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
