#!/usr/bin/env python3
"""Fail-closed admission snapshot for the opportunistic KK-Mac LLM lane.

The heartbeat is the availability signal; this helper deliberately does not
submit work or keep KK-Mac alive. Callers can use the JSON result to choose
KK-Mac for bounded, read-only tasks and fall back immediately when the node
is absent or unhealthy.

Job visibility (2026-10-30): besides the host heartbeat, snapshot() also
reads each KK-Mac nest lane's `<lane_root>/queue/heartbeat`
(`<epoch> <pack> <phase>` written by nest-worker while a pack is claimed)
via `ssh $KK_MAC_QUEUE_SSH rclone` (default idc02 — same transport as
nest-queue-watch; fleet hosts need no gdrive remote). Lanes default to
the two pilot roots; override with `KK_MAC_NEST_LANES=name=remote,...`
(an empty value disables lane reads). Result keys: per-lane
`nest_jobs.<lane>.{current_job,phase,job_age_s}` plus top-level
`current_job`/`phase`/`job_age_s` from the freshest beat. These are
visibility fields only — they never gate eligibility.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

DEFAULT_LANES = {
    "video": "gdrive:ada-nest-kk-mac-video-pilot",
    "llm": "gdrive:ada-nest-kk-mac-pilot",
}


def _lanes(job_lanes: dict | None) -> dict:
    """Resolve lane map: explicit arg > KK_MAC_NEST_LANES > defaults."""
    if job_lanes is not None:
        return dict(job_lanes)
    env = os.environ.get("KK_MAC_NEST_LANES")
    if env is None:
        return dict(DEFAULT_LANES)
    out = {}
    for item in env.split(","):
        name, _, remote = item.strip().partition("=")
        if name and remote:
            out[name] = remote.rstrip("/")
    return out


def _lane_heartbeat(remote_root: str, ssh_host: str,
                    now: float) -> dict | None:
    """'<epoch> <pack> <phase>' from <remote_root>/queue/heartbeat."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             ssh_host,
             f"~/.local/bin/rclone cat {remote_root}/queue/heartbeat"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    parts = result.stdout.split()
    if len(parts) < 3:
        return None
    try:
        ts = float(parts[0])
    except ValueError:
        return None
    return {"current_job": parts[1], "phase": parts[2],
            "job_age_s": max(0, round(now - ts, 1))}


def _search(url: str) -> list[dict]:
    req = urllib.request.Request(
        url.rstrip("/") + "/search",
        data=json.dumps({
            "collection": "ada-nest-heartbeats",
            "query": "",
            "limit": 100,
        }).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        value = json.load(response)
    return value if isinstance(value, list) else []


def _parse(doc: dict) -> dict | None:
    try:
        body = json.loads(doc.get("contentMd", "{}"))
    except (TypeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _ssh_load(host: str) -> float | None:
    """Read-only fallback while older installed heartbeats lack load_1m."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             host, "sysctl -n vm.loadavg 2>/dev/null"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode:
            return None
        match = re.search(r"\d+(?:\.\d+)?", result.stdout)
        return float(match.group(0)) if match else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def snapshot(
    *,
    host: str = "KKs-Mac-Studio",
    tailnet_ip: str = "100.108.217.17",
    url: str = "http://100.102.134.91:11026/v1",
    max_age_s: int = 900,
    min_disk_gb: int = 20,
    max_load_1m: float = 4.0,
    require_idle: bool = True,
    max_load_pc: float = 1.0,
    job_lanes: dict | None = None,
    queue_ssh: str | None = None,
    now: float | None = None,
) -> dict:
    now = time.time() if now is None else now
    ssh_host = queue_ssh or os.environ.get("KK_MAC_QUEUE_SSH", "idc02")
    nest_jobs = {}
    freshest = None
    for lane, root in _lanes(job_lanes).items():
        hb = _lane_heartbeat(root.rstrip("/"), ssh_host, now)
        if hb:
            nest_jobs[lane] = hb
            if freshest is None or hb["job_age_s"] < freshest["job_age_s"]:
                freshest = hb
    candidates = [_parse(d) for d in _search(url)]
    body = next((x for x in candidates if x and x.get("host") == host), None)
    identity_alias = False
    if body is None:
        # Older installed Mac heartbeat scripts used the LAN address as the
        # host key (for example "192"). Accept it only when the tailnet IP
        # identifies the expected machine; freshness and health gates remain.
        body = next(
            (x for x in candidates if x and x.get("tailnet_ip") == tailnet_ip),
            None,
        )
        identity_alias = body is not None
    result = {
        "host": host,
        "eligible": False,
        "lane": "kk_mac_local",
        "reasons": [],
        "heartbeat_age_s": None,
        "ollama_ok": None,
        "disk_free_gb": None,
        "load_1m": None,
        "identity_alias": identity_alias,
        "node_busy": None,
        "nest_jobs": nest_jobs,
        "current_job": freshest["current_job"] if freshest else None,
        "phase": freshest["phase"] if freshest else None,
        "job_age_s": freshest["job_age_s"] if freshest else None,
    }
    if not body:
        result["reasons"].append("heartbeat_missing")
        return result
    result["ollama_ok"] = body.get("ollama_ok")
    result["disk_free_gb"] = body.get("disk_free_gb")
    result["load_1m"] = body.get("load_1m")
    try:
        raw_ts = body["ts"]
        if isinstance(raw_ts, (int, float)):
            ts = float(raw_ts)
        else:
            ts = datetime.fromisoformat(
                str(raw_ts).replace("Z", "+00:00")
            ).timestamp()
        result["heartbeat_age_s"] = max(0, round(now - ts, 1))
    except (KeyError, TypeError, ValueError):
        result["reasons"].append("heartbeat_invalid")
        return result
    if result["heartbeat_age_s"] > max_age_s:
        result["reasons"].append("heartbeat_stale")
    if body.get("ollama_ok") is not True:
        result["reasons"].append("ollama_unhealthy")
    try:
        if float(body.get("disk_free_gb", 0)) < min_disk_gb:
            result["reasons"].append("disk_low")
    except (TypeError, ValueError):
        result["reasons"].append("disk_unknown")
    load = body.get("load_1m")
    if load is None:
        load = _ssh_load(os.environ.get("KK_MAC_SSH_HOST", "kk-mac"))
        if load is not None:
            result["load_1m"] = load
            result["load_source"] = "ssh_read_only_fallback"
    try:
        if load is None:
            raise ValueError("missing load")
        if float(load) > max_load_1m:
            result["reasons"].append("load_high")
    except (KeyError, TypeError, ValueError):
        result["reasons"].append("load_unknown")
    # Overload gate: KK-Mac is an owner-first box — a busy node defers
    # the opportunistic lane. Signals, best available first: tmux_jobs
    # non-empty (work is running on the node), an explicit load_ok flag,
    # or load1/cpu_cores above max_load_pc — absent fields are skipped.
    busy = []
    if require_idle:
        tmux = body.get("tmux_jobs")
        if isinstance(tmux, str) and tmux.strip():
            busy.append("tmux_jobs")
        elif isinstance(tmux, list) and tmux:
            busy.append("tmux_jobs")
    if body.get("load_ok") is False:
        busy.append("load_ok")
    try:
        load1 = float(body.get("load1"))
        cores = float(body.get("cpu_cores") or 0)
        if cores > 0 and load1 / cores > max_load_pc:
            busy.append("load1")
    except (TypeError, ValueError):
        pass
    result["node_busy"] = bool(busy)
    if busy:
        result["reasons"].append("node_busy:" + "+".join(busy))
    result["eligible"] = not result["reasons"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="KKs-Mac-Studio")
    parser.add_argument("--url", default="http://100.102.134.91:11026/v1")
    parser.add_argument("--max-age-s", type=int, default=900)
    parser.add_argument("--min-disk-gb", type=int, default=20)
    parser.add_argument("--allow-busy", action="store_true",
                        help="admit even when the node reports work")
    parser.add_argument("--max-load-pc", type=float, default=1.0)
    parser.add_argument("--lane", action="append", default=None,
                        metavar="NAME=REMOTE",
                        help="nest lane root to read job state from; "
                             "repeatable. Default: the two kk-mac pilot "
                             "roots (or KK_MAC_NEST_LANES env)")
    parser.add_argument("--queue-ssh", default=None,
                        help="rclone proxy host for lane reads "
                             "(default env KK_MAC_QUEUE_SSH or idc02)")
    args = parser.parse_args()
    lanes = None
    if args.lane is not None:
        lanes = dict(
            item.split("=", 1) for item in args.lane if "=" in item)
    try:
        result = snapshot(
            host=args.host,
            url=args.url,
            max_age_s=args.max_age_s,
            min_disk_gb=args.min_disk_gb,
            require_idle=not args.allow_busy,
            max_load_pc=args.max_load_pc,
            job_lanes=lanes,
            queue_ssh=args.queue_ssh,
        )
    except Exception as exc:
        result = {
            "host": args.host,
            "eligible": False,
            "lane": "kk_mac_local",
            "reasons": [f"heartbeat_probe_failed:{type(exc).__name__}"],
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
