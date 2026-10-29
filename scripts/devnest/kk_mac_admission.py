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


def snapshot(
    *,
    host: str = "KKs-Mac-Studio",
    tailnet_ip: str = "100.108.217.17",
    url: str = "http://100.102.134.91:11026/v1",
    max_age_s: int = 900,
    min_disk_gb: int = 20,
    require_idle: bool = True,
    max_load_pc: float = 1.0,
    now: float | None = None,
) -> dict:
    now = time.time() if now is None else now
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
        "identity_alias": identity_alias,
        "node_busy": None,
    }
    if not body:
        result["reasons"].append("heartbeat_missing")
        return result
    result["ollama_ok"] = body.get("ollama_ok")
    result["disk_free_gb"] = body.get("disk_free_gb")
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
    args = parser.parse_args()
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
