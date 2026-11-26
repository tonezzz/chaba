#!/usr/bin/env python3
"""netdata nodes watchdog.

Watches the self-hosted Netdata parent's node list — the fleet streaming
setup (children -> tony-omen parent :19999 over tailnet, added
2026-11-18). If a child drops out of /api/v2/nodes the dashboard silently
loses that host; nothing else notices. This is the netdata equivalent of
system-report-watchdog's stale-data check.

Checks (one HTTPS-free tailnet GET):
  * parent reachable: GET /api/v1/info on the parent must answer
  * node set: every expected node name present in /api/v2/nodes
  * per-node reachability is implied by presence (streamed nodes only
    appear while connected)

Alert channel: board-api /inbox — deduped focus-inbox entry, at most
once per --repeat-h (default 12h) per condition. Recovery is silent +
journaled, matching the inbox's no-resolve semantics.

Exit 0 on completed checks, including alerts (OPS-0581 contract);
findings ride the board inbox, not the exit code.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PARENT = "http://100.75.102.88:19999"
BOARD_API = "https://idc03.taila0626a.ts.net:10000"
STATE = Path.home() / ".local/state/netdata-nodes-watch.json"
LABEL = "Netdata nodes unhealthy — fleet streaming"
TAGS = ["ops", "monitor", "netdata", "netdata-nodes-watch"]
DEFAULT_NODES = [
    "tony-omen", "con01", "idc02", "idc03",
    "mn01", "tony-dell", "tony-macbook", "michael-ha",
]


def get(path: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        PARENT + path, headers={"User-Agent": "netdata-nodes-watch/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        # Tailscale reaches tony-omen (ping works) but TCP/19999 is
        # filtered by the mesh policy, so a direct GET times out from
        # every host except the parent itself. The parent is local there;
        # use the existing SSH path as a fallback so a policy change is
        # not misreported as a Netdata outage.
        cmd = [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "tony-omen",
            f"curl -fsS --max-time {timeout} http://127.0.0.1:19999{path}",
        ]
        out = subprocess.run(
            cmd, check=True, capture_output=True, timeout=timeout + 10).stdout
        return json.loads(out)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(STATE.name + ".tmp")
    with tmp.open("w") as f:
        f.write(json.dumps(st))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE)


def recently_alerted(st: dict, cond: str, repeat_h: float) -> bool:
    try:
        at = st.get("alerts", {}).get(cond)
        return bool(at) and (
            dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(at)).total_seconds() < repeat_h * 3600
    except Exception:
        return False


def file_inbox(text: str) -> bool:
    body = {"text": text, "label": LABEL, "priority": "high",
            "tags": TAGS, "owner": "tony"}
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        sys.stderr.write(f"netdata-nodes-watch: inbox post failed: {e}\n")
        return False


def main() -> int:
    global PARENT
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", default=PARENT)
    ap.add_argument("--nodes", default=",".join(DEFAULT_NODES),
                    help="comma-separated expected node names")
    ap.add_argument("--repeat-h", type=float, default=12.0)
    ap.add_argument("--no-alert", action="store_true",
                    help="check only, print verdict")
    args = ap.parse_args()
    PARENT = args.parent.rstrip("/")

    expected = [n.strip() for n in args.nodes.split(",") if n.strip()]
    st = load_state()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    problems = []

    try:
        info = get("/api/v1/info")
    except Exception as e:
        problems.append(("parent-down",
                         f"netdata parent unreachable at {PARENT} — {e}"))
        info = None

    if info is not None:
        try:
            nodes = get("/api/v2/nodes")
            present = {n.get("nm") for n in nodes.get("nodes", [])}
        except Exception as e:
            problems.append(("nodes-api",
                             f"/api/v2/nodes failed — {e}"))
            present = set()
        missing = [n for n in expected if n not in present]
        if missing:
            problems.append((
                "nodes-missing",
                f"{len(missing)} expected node(s) absent from parent: "
                f"{', '.join(missing)} (present: {len(present)})"))

    rc = 0
    alerts = st.setdefault("alerts", {})
    for cond, text in problems:
        # OPS-0581: a completed check exits 0; alerts ride the inbox.
        if args.no_alert:
            print(f"ALERT {cond}: {text}")
            continue
        if recently_alerted(st, cond, args.repeat_h):
            print(f"alert muted (deduped): {cond}")
            continue
        if file_inbox(text):
            alerts[cond] = now
            print(f"alert filed: {cond}")
        else:
            print(f"alert FAILED to file: {cond}", file=sys.stderr)
    for cond in list(alerts):
        if not any(c == cond for c, _ in problems):
            print(f"recovered (silent): {cond}")
            del alerts[cond]

    if not problems:
        print(f"ok — {len(expected)} expected nodes present")
    save_state(st)
    return rc


if __name__ == "__main__":
    sys.exit(main())
