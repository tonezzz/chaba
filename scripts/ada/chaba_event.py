#!/usr/bin/env python3
"""Shared chaba-admin Events emit helper for ada-* jobs.

Transports, tried in order (both best-effort, never raise):
  1. ssh tony-dell -> chaba-event-log.py add -   (fast path on home hosts)
  2. POST <ha>/api/services/shell_command/chaba_event  (HA REST; works from
     idc01 where Tailscale SSH check-mode periodically blocks ssh tony-dell)

Config/env:
  CHABA_EVENT_TRANSPORT  ssh|http  — force one transport (default: ssh,http)
  CHABA_EVENT_HA_URL     override HA base URL
  HOME_ASSISTANT_URL     fallback HA base URL
  CHABA_EVENT_HA_TOKEN / HA_TOKEN / HOME_ASSISTANT_TOKEN / HA_LONG_LIVED_TOKEN
  secrets file fallback: ~/.config/secrets/home-assistant-token.env
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request

SSH_CMD = [
    "ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "tony-dell",
    "python3", "/home/tony/.config/home-assistant/scripts/chaba-event-log.py",
    "add", "-",
]

DEFAULT_HA_URL = "https://tony-dell.taila0626a.ts.net:8123"
TOKEN_ENV = os.path.expanduser("~/.config/secrets/home-assistant-token.env")


def _ha_url() -> str:
    url = (os.environ.get("CHABA_EVENT_HA_URL")
           or os.environ.get("HOME_ASSISTANT_URL")
           or DEFAULT_HA_URL)
    return url.rstrip("/")


def _ha_token() -> str | None:
    for name in ("CHABA_EVENT_HA_TOKEN", "HA_TOKEN", "HOME_ASSISTANT_TOKEN",
                 "HA_LONG_LIVED_TOKEN"):
        tok = os.environ.get(name)
        if tok:
            return tok.strip()
    try:
        for line in open(TOKEN_ENV):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in ("HA_LONG_LIVED_TOKEN", "HASS_TOKEN",
                                 "HOME_ASSISTANT_TOKEN"):
                    v = v.strip().strip('"').strip("'")
                    if v:
                        return v
    except OSError:
        pass
    return None


def _send_ssh(payload: str) -> tuple[bool, str]:
    r = subprocess.run(SSH_CMD, input=payload, capture_output=True,
                       text=True, timeout=15)
    if r.returncode == 0:
        return True, "ssh"
    return False, (r.stderr or r.stdout or f"rc={r.returncode}").strip()[:200]


def _send_http(payload: str) -> tuple[bool, str]:
    token = _ha_token()
    if not token:
        return False, "no HA token (env or home-assistant-token.env)"
    body = json.dumps({
        "payload": base64.b64encode(payload.encode()).decode(),
    }).encode()
    req = urllib.request.Request(
        f"{_ha_url()}/api/services/shell_command/chaba_event",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return (200 <= r.status < 300), f"http:{r.status}"
    except Exception as exc:
        return False, f"http:{exc}"


def send(payload: str | dict) -> tuple[bool, str]:
    """Emit a chaba-event. Returns (ok, detail). Never raises."""
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    order = os.environ.get("CHABA_EVENT_TRANSPORT", "ssh,http").split(",")
    last = "no transports configured"
    for t in (x.strip() for x in order if x.strip()):
        try:
            if t == "ssh":
                ok, last = _send_ssh(payload)
            elif t == "http":
                ok, last = _send_http(payload)
            else:
                continue
            if ok:
                return True, t
        except Exception as exc:
            last = f"{t}:{exc}"
    return False, last


if __name__ == "__main__":
    import sys
    ev = json.loads(sys.stdin.read()) if not sys.argv[1:] else json.loads(sys.argv[1])
    ok, via = send(ev)
    print(f"{'ok' if ok else 'failed'} via {via}")
    sys.exit(0 if ok else 1)
