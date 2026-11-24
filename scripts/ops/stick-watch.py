#!/usr/bin/env python3
"""stick-watch — detect the tony-usb stick booting and alert with the fix.

Card: tony-usb-own-nodekey (SEC-0303).
Runbook: docs/kb/mn01-stick-standard.md — "Per-stick tailnet identity".

Why this exists: the stick's tailscaled.state is a clone of mn01's node
key, so EVERY boot steals mn01's tailnet session until
scripts/ops/stick-own-nodekey.sh runs on it. Four dispatch attempts
verified the fix is prepared but the stick is physical — nobody knew
when it next booted. This watcher closes that gap: run it on a fleet
host (tony-dell recommended — always on, fleet ssh keys, tailnet) every
few minutes via systemd/stick-watch.timer and it pages Tony the moment
the stick appears, with the exact remediation command.

Signals, strongest first:

  active_theft — `ssh <STICK_WATCH_SSH_HOST> hostname` answers
      'tony-usb': the stick is holding mn01's nodekey RIGHT NOW.
      (ssh lands on whatever machine owns the nodekey — the stick's
      hostname is always tony-usb.)
  announced    — ops feed (ada-ha-events-tony) has a stick_online /
      host_online ops-event for the stick inside the window. This is
      the earliest signal: stick-announce fires at boot even while the
      stick is still contesting mn01.
  own_node     — tailnet roster carries a node named tony-usb/rescue:
      the fix already ran. Posts once suggesting registry update +
      card close.

On detection: one comment on the card via board-api + one
board_notify push (HA iPhone default). Deduped per signal via state
file — repeat boots re-alert, a stuck signal doesn't spam.

Env:
  MDDB_OPS_URL          ops feed base, default http://100.123.163.11:11025/v1
  BOARD_API             default https://idc03.taila0626a.ts.net:10000
  STICK_WATCH_CARD      card id, default tony-usb-own-nodekey
  STICK_WATCH_SSH_HOST  tailnet host to probe, default mn01
  STICK_WATCH_WINDOW_MIN  announce window, default 30
  STICK_WATCH_OPS_LIMIT   ops-event docs fetched, default 200
  STICK_WATCH_ALERT_S   per-signal re-alert seconds, default 86400
  STICK_WATCH_STATE     state file, default ~/.local/state/stick-watch.json
  STICK_WATCH_OFF_FILE  kill switch, default ~/.config/stick-watch.off
  STICK_WATCH_NOTIFY    'off' disables push+comment (detect only, rc=0)
  STICK_WATCH_VERBOSE   '1' prints detections

CLI: stick-watch.py [--dry-run] [--verbose]
Exit: always 0 on completed runs (findings travel via comment/push —
nonzero = crash, per timer-expectations).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_OPS_URL", "http://100.123.163.11:11025/v1").rstrip("/")
OPS_COLLECTION = os.environ.get("ADA_OPS_COLLECTION", "ada-ha-events-tony")
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
CARD = os.environ.get("STICK_WATCH_CARD", "tony-usb-own-nodekey")
SSH_HOST = os.environ.get("STICK_WATCH_SSH_HOST", "mn01")
WINDOW_MIN = int(os.environ.get("STICK_WATCH_WINDOW_MIN", "30"))
OPS_LIMIT = int(os.environ.get("STICK_WATCH_OPS_LIMIT", "200"))
ALERT_S = int(os.environ.get("STICK_WATCH_ALERT_S", "86400"))
STATE = Path(os.environ.get(
    "STICK_WATCH_STATE",
    str(Path.home() / ".local/state/stick-watch.json")))
OFF_FILE = Path(os.environ.get(
    "STICK_WATCH_OFF_FILE",
    str(Path.home() / ".config/stick-watch.off")))
NOTIFY = os.environ.get("STICK_WATCH_NOTIFY", "on").lower() != "off"
VERBOSE = os.environ.get("STICK_WATCH_VERBOSE", "") == "1"

STICK_NAMES = {"tony-usb", "rescue"}
ANNOUNCE_TYPES = {"stick_online", "host_online"}
FIX_CMD = ("ssh -t tony@<stick-lan-ip> 'sudo bash -s' "
           "< scripts/ops/stick-own-nodekey.sh   # any fleet host; "
           "then approve the tony-usb node in the admin console")


def log(msg: str) -> None:
    if VERBOSE:
        print(f"[stick-watch] {msg}", file=sys.stderr)


def _post(url: str, payload: dict, timeout: int = 15) -> dict | list | None:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as exc:
        log(f"POST {url} failed: {exc}")
        return None


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _parse_ts(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ---- signals ---------------------------------------------------------

def probe_active_theft() -> dict | None:
    """ssh <host> hostname — 'tony-usb' means the stick owns the nodekey."""
    rc, out = _run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
         "-o", "StrictHostKeyChecking=accept-new", SSH_HOST, "hostname"],
        timeout=20)
    first = out.splitlines()[0].strip() if out else ""
    log(f"ssh {SSH_HOST} hostname -> rc={rc} {first!r}")
    if first == "tony-usb":
        return {"kind": "active_theft",
                "detail": f"ssh {SSH_HOST} resolves to the stick — it is "
                          "holding mn01's nodekey right now"}
    return None


def scan_ops_feed(now: datetime) -> dict | None:
    """Recent stick announce ops-event in ada-ha-events-tony."""
    payload = {"collection": OPS_COLLECTION,
               "filterMeta": {"kind": ["ops-event"]},
               "limit": OPS_LIMIT}
    docs = _post(f"{MDDB}/search", payload) or []
    if not isinstance(docs, list):
        return None
    for d in docs:
        m = d.get("meta") or {}
        etype = (m.get("type") or [""])[0]
        if etype not in ANNOUNCE_TYPES:
            continue
        ts = _parse_ts((m.get("ts") or [""])[0])
        if ts and (now - ts).total_seconds() > WINDOW_MIN * 60:
            continue
        host = (m.get("host") or m.get("hostname") or [""])[0]
        blob = json.dumps(m).lower() + " " + (
            d.get("contentMd") or d.get("content") or "").lower()
        is_stick = (host == "tony-usb" or "tony-usb" in blob
                    or etype == "stick_online")
        if not is_stick:
            continue
        lan = (m.get("lan_ip") or [""])[0]
        tip = (m.get("tailnet_ip") or [""])[0]
        return {"kind": "announced", "type": etype, "host": host or "?",
                "lan_ip": lan, "tailnet_ip": tip,
                "at": (m.get("ts") or [""])[0],
                "detail": f"stick announce ops-event ({etype}) at "
                          f"{(m.get('ts') or ['?'])[0]} host={host or '?'} "
                          f"lan_ip={lan or '?'} tailnet_ip={tip or '?'}"}
    return None


def probe_own_node() -> dict | None:
    """Tailnet roster carries tony-usb/rescue — the fix already ran."""
    rc, out = _run(["tailscale", "status", "--json"], timeout=15)
    if rc != 0 or not out:
        return None
    try:
        s = json.loads(out)
    except Exception:
        return None
    peers = s.get("Peer") or {}
    names = [(p.get("HostName") or "") for p in peers.values()]
    names.append((s.get("Self") or {}).get("HostName") or "")
    for n in names:
        if n.lower() in STICK_NAMES or n.lower().startswith("tony-usb"):
            return {"kind": "own_node", "node": n,
                    "detail": f"tailnet node '{n}' exists — stick has its "
                              "own nodekey; update the identity registry "
                              "in mn01-stick-standard.md and close the card"}
    return None


# ---- alerting --------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"alerts": {}}


def save_state(st: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st))
    except Exception as exc:
        log(f"state write failed: {exc}")


def should_alert(st: dict, key: str, now: datetime) -> bool:
    last = _parse_ts(st.get("alerts", {}).get(key, ""))
    return last is None or (now - last).total_seconds() > ALERT_S


def mark_alerted(st: dict, key: str, now: datetime) -> None:
    st.setdefault("alerts", {})[key] = now.isoformat()
    # prune keys older than 7d
    cutoff = now.timestamp() - 7 * 86400
    st["alerts"] = {k: v for k, v in st["alerts"].items()
                    if (_parse_ts(v) and _parse_ts(v).timestamp() > cutoff)}


def board_comment(text: str) -> bool:
    r = _post(f"{BOARD_API}/comment",
              {"id": CARD, "from": "stick-watch", "text": text[:1500]})
    return bool(r and r.get("ok"))


def notify(title: str, body: str) -> bool:
    if not NOTIFY:
        return False
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "board"))
    try:
        import board_notify
        return board_notify.send(title, body, channel=None)
    except Exception as exc:
        log(f"board_notify failed: {exc}")
        return False


def alert(sig: dict, now: datetime, st: dict, dry: bool) -> None:
    kind = sig["kind"]
    key = f"{kind}:{sig.get('host') or sig.get('node') or sig.get('lan_ip') or sig.get('at') or 'x'}"
    if not should_alert(st, key, now):
        log(f"suppressed repeat alert for {key}")
        return
    mark_alerted(st, key, now)
    if dry:
        print(f"[dry-run] would alert {key}: {sig['detail']}")
        return
    board_comment(f"[stick-watch] {sig['detail']}")
    if kind == "own_node":
        title = "tony-usb stick: own nodekey detected"
        body = (sig["detail"] + " — verify `tailscale status` and fill the "
                "registry row in docs/kb/mn01-stick-standard.md.")
    else:
        cmd = FIX_CMD
        if sig.get("lan_ip"):
            cmd = (f"ssh -t tony@{sig['lan_ip']} 'sudo bash -s' "
                   "< scripts/ops/stick-own-nodekey.sh   # any fleet host; "
                   "then approve the tony-usb node in the admin console")
        title = ("tony-usb stick is UP — run the nodekey fix now"
                 if kind == "announced"
                 else "tony-usb stick is STEALING mn01's tailnet session")
        body = (sig["detail"] + "\n\nFix: " + cmd +
                "\nRunbook: docs/kb/mn01-stick-standard.md")
    ok = notify(title, body)
    log(f"alert {key}: comment+notify sent (notify={ok})")


def main() -> int:
    dry = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv
    global VERBOSE
    VERBOSE = VERBOSE or verbose
    if OFF_FILE.exists():
        log("kill switch present — exiting")
        return 0
    now = datetime.now(timezone.utc)
    st = load_state()

    sigs = []
    s = probe_active_theft()
    if s:
        sigs.append(s)
    s = scan_ops_feed(now)
    if s:
        sigs.append(s)
    s = probe_own_node()
    if s:
        sigs.append(s)

    if not sigs:
        log("no stick signals")
        return 0
    for sig in sigs:
        log(f"signal: {sig['kind']} — {sig['detail']}")
        alert(sig, now, st, dry)
    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
