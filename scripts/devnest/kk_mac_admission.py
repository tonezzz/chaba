#!/usr/bin/env python3
"""Fail-closed admission snapshot for the opportunistic KK-Mac LLM lane.

The heartbeat is the availability signal; this helper deliberately does not
submit work or keep KK-Mac alive. Callers can use the JSON result to choose
KK-Mac for bounded, read-only tasks and fall back immediately when the node
is absent or unhealthy.
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
    # Tony 2026-11-09: KK runs hot under load — hold new work at 60C.
    max_temp_c: float = 60.0,
    require_idle: bool = True,
    max_load_pc: float = 1.0,
    now: float | None = None,
    docs: list[dict] | None = None,
    ssh_fallback: bool = True,
) -> dict:
    now = time.time() if now is None else now
    # docs: inject heartbeat docs instead of querying MDDB (tests /
    # simulated heartbeats for the LiteLLM admission shim).
    candidates = [_parse(d) for d in (_search(url) if docs is None else docs)]

    def _ts(x: dict) -> float:
        try:
            raw = x.get("ts")
            if isinstance(raw, (int, float)):
                return float(raw)
            return datetime.fromisoformat(
                str(raw).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0.0
    body = next((x for x in candidates if x and x.get("host") == host), None)
    identity_alias = False
    if body is None:
        # Older installed Mac heartbeat scripts used the LAN address as the
        # host key (for example "192"). Accept it only when the tailnet IP
        # identifies the expected machine — and when several alias docs
        # exist (renamed host keys accumulate) take the FRESHEST, so a stale
        # shadow doc cannot deny a healthy node.
        alias = [x for x in candidates
                 if x and x.get("tailnet_ip") == tailnet_ip]
        body = max(alias, key=_ts) if alias else None
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
    # ssh_fallback=False keeps admission callers (the LiteLLM gateway shim)
    # fail-fast — a missing field denies instead of probing a dead node.
    # Probes are also skipped once a deny reason exists: they can only add
    # reasons, never clear them.
    if load is None and ssh_fallback and not result["reasons"]:
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
    try:
        temp = body.get("cpu_temp_c")
        if temp is None and ssh_fallback and not result["reasons"]:
            # heartbeat body lacks temp (root-owned adanest script) —
            # same read-only fallback pattern as the load probe.
            t = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 os.environ.get("KK_MAC_SSH_HOST", "kk-mac"),
                 "~/.local/bin/smctemp -c"],
                capture_output=True, text=True, timeout=12)
            if t.returncode == 0 and t.stdout.strip():
                temp = float(t.stdout.strip())
        result["cpu_temp_c"] = temp
        if temp is not None and float(temp) > max_temp_c:
            result["reasons"].append("temp_high")
    except (TypeError, ValueError):
        pass
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


LOCAL_HOSTS = frozenset({"local", "localhost", "127.0.0.1", "::1"})


def _which(*names: str) -> str | None:
    for name in names:
        for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
                  "/usr/sbin", "/sbin",
                  os.path.expanduser("~/.local/bin")):
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def _run_text(cmd: list[str], timeout: int = 10) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _local_load_1m() -> float | None:
    if os.uname().sysname == "Darwin":
        sysctl = _which("sysctl") or "/usr/sbin/sysctl"
        out = _run_text([sysctl, "-n", "vm.loadavg"])
        if out:
            m = re.search(r"\d+(?:\.\d+)?", out)
            return float(m.group(0)) if m else None
        return None
    try:
        return float(open("/proc/loadavg").read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _local_tmux_jobs() -> str:
    tmux = _which("tmux")
    if not tmux:
        return ""
    out = _run_text([tmux, "ls"])
    if not out:
        return ""
    return ",".join(
        line.split(":", 1)[0] for line in out.splitlines() if line.strip())


def _local_temp_c() -> float | None:
    smctemp = _which("smctemp")
    if not smctemp:
        return None
    out = _run_text([smctemp, "-c"])
    try:
        return float((out or "").strip())
    except ValueError:
        return None


def local_snapshot(
    *,
    host: str = "local",
    min_disk_gb: int = 20,
    max_load_1m: float = 4.0,
    max_temp_c: float = 60.0,
    require_idle: bool = True,
    max_load_pc: float = 1.0,
    ollama_url: str = "http://127.0.0.1:11434",
) -> dict:
    """On-host self-gate for the dedicated lane worker — the same
    thresholds as snapshot() but sourced from local ground truth instead
    of the MDDB heartbeat, so a worker sitting on the node itself gates
    on what is true right now, not on a heartbeat up to 15 min old.
    Read-only probes only: ollama /api/version, loadavg, statvfs,
    smctemp, tmux ls."""
    result = {
        "host": host,
        "eligible": False,
        "lane": "kk_mac_local",
        "source": "local_self",
        "reasons": [],
        "heartbeat_age_s": 0.0,
        "ollama_ok": None,
        "disk_free_gb": None,
        "load_1m": None,
        "cpu_temp_c": None,
        "node_busy": None,
    }
    try:
        req = urllib.request.Request(
            ollama_url.rstrip("/") + "/api/version")
        with urllib.request.urlopen(req, timeout=5) as r:
            result["ollama_ok"] = r.status == 200
    except Exception:
        result["ollama_ok"] = False
    if result["ollama_ok"] is not True:
        result["reasons"].append("ollama_unhealthy")
    try:
        st = os.statvfs("/")
        result["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
        if result["disk_free_gb"] < min_disk_gb:
            result["reasons"].append("disk_low")
    except OSError:
        result["reasons"].append("disk_unknown")
    load = _local_load_1m()
    result["load_1m"] = load
    if load is None:
        result["reasons"].append("load_unknown")
    elif load > max_load_1m:
        result["reasons"].append("load_high")
    temp = _local_temp_c()
    result["cpu_temp_c"] = temp
    if temp is not None and temp > max_temp_c:
        result["reasons"].append("temp_high")
    busy = []
    if require_idle:
        tmux = _local_tmux_jobs()
        result["tmux_jobs"] = tmux
        if tmux:
            busy.append("tmux_jobs")
    cores = os.cpu_count() or 0
    if cores > 0 and load is not None and load / cores > max_load_pc:
        busy.append("load1")
    result["node_busy"] = bool(busy)
    if busy:
        result["reasons"].append("node_busy:" + "+".join(busy))
    result["eligible"] = not result["reasons"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="KKs-Mac-Studio")
    parser.add_argument("--local", action="store_true",
                        help="on-host self-gate (run on the node itself) "
                             "instead of the MDDB heartbeat snapshot")
    parser.add_argument("--url", default="http://100.102.134.91:11026/v1")
    parser.add_argument("--max-age-s", type=int, default=900)
    parser.add_argument("--min-disk-gb", type=int, default=20)
    parser.add_argument("--allow-busy", action="store_true",
                        help="admit even when the node reports work")
    parser.add_argument("--max-load-pc", type=float, default=1.0)
    args = parser.parse_args()
    if args.local:
        result = local_snapshot(min_disk_gb=args.min_disk_gb,
                                require_idle=not args.allow_busy,
                                max_load_pc=args.max_load_pc)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["eligible"] else 2
    try:
        result = snapshot(
            host=args.host,
            url=args.url,
            max_age_s=args.max_age_s,
            min_disk_gb=args.min_disk_gb,
            require_idle=not args.allow_busy,
            max_load_pc=args.max_load_pc,
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
