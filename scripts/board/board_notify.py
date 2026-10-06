#!/usr/bin/env python3
"""board_notify — push channel for board request alerts.

Channel decision (2026-10-05, card kanban-push-notify): the primary
channel is the HA iPhone push — notify.mobile_app_tony_ip on tony-ha
loopback (:8123), the same path devin-dispatch-watch has used for every
finished dispatch job. Proven live, zero new dependencies, and
clickAction deep-links straight to /chaba-admin/board.

Evaluated and rejected for now (see docs/ssot/jobs/kanban/
2026-10-05-board-request-notify.yml):
  yomi LINE — POST 127.0.0.1:3000/api/yomi/send {chatId, text} exists and
    was the card's preference, but the LINE session is currently invalid
    (/api/yomi/session-status valid:false) and no target chat id is
    configured anywhere; sending to Tony's own account is also unverified.
    Revisit once the session is back — set BOARD_NOTIFY_CHANNEL=yomi and
    BOARD_NOTIFY_YOMI_CHAT=<chatId>.
  ntfy.sh — works fine but adds an external SaaS plus a new phone
    app/topic Tony would have to subscribe; nothing in the repo uses it.

Every send is best-effort and never raises — a dead channel must not
break a card write. Returns True when the channel accepted the message.

CLI:  python3 board_notify.py [--channel ha|yomi|ntfy|file|off] TITLE [BODY]

Env:
  BOARD_NOTIFY_CHANNEL   ha (default) | yomi | ntfy | file | off;
                         comma list ('ha,yomi') fans out to each
  HA_NOTIFY_URL          default http://127.0.0.1:8123
  HA_NOTIFY_SERVICE      default notify/mobile_app_tony_ip
  HA_TOKEN_FILE          default ~/.config/secrets/home-assistant-token.env
                         (HA_LONG_LIVED_TOKEN or HASS_TOKEN)
  BOARD_NOTIFY_CLICK     default /chaba-admin/board (HA in-app path)
  BOARD_NOTIFY_YOMI_URL  default http://127.0.0.1:3000/api/yomi/send
  BOARD_NOTIFY_YOMI_CHAT LINE chatId — required for the yomi channel
  BOARD_NOTIFY_NTFY_URL  default https://ntfy.sh
  BOARD_NOTIFY_NTFY_TOPIC ntfy topic — required for the ntfy channel
  BOARD_NOTIFY_FILE      file channel sink, default /tmp/board-notify.jsonl
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TIMEOUT_S = 8


def _post(url: str, payload: dict, headers: dict | None = None) -> bool:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"board_notify: POST {url} failed: {e}", file=sys.stderr)
        return False


def _ha_token() -> str:
    env = Path(os.environ.get(
        "HA_TOKEN_FILE",
        str(Path.home() / ".config/secrets/home-assistant-token.env")))
    try:
        for line in env.read_text().splitlines():
            line = line.strip().lstrip("export").strip()
            if line.startswith(("HA_LONG_LIVED_TOKEN=", "HASS_TOKEN=")):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _ha_send(title: str, body: str, url: str) -> bool:
    token = _ha_token()
    if not token:
        print("board_notify: no HA token (HA_TOKEN_FILE)", file=sys.stderr)
        return False
    base = os.environ.get("HA_NOTIFY_URL", "http://127.0.0.1:8123").rstrip("/")
    svc = os.environ.get("HA_NOTIFY_SERVICE", "notify/mobile_app_tony_ip")
    return _post(f"{base}/api/services/{svc}", {
        "title": title,
        "message": body[:500],
        "data": {"url": url, "clickAction": url},
    }, {"Authorization": f"Bearer {token}"})


def _yomi_send(title: str, body: str, url: str) -> bool:
    chat = os.environ.get("BOARD_NOTIFY_YOMI_CHAT", "")
    if not chat:
        print("board_notify: BOARD_NOTIFY_YOMI_CHAT unset", file=sys.stderr)
        return False
    api = os.environ.get("BOARD_NOTIFY_YOMI_URL",
                         "http://127.0.0.1:3000/api/yomi/send")
    text = f"{title}\n{body}\n{url}" if url else f"{title}\n{body}"
    return _post(api, {"chatId": chat, "text": text[:900]})


def _ntfy_send(title: str, body: str, url: str) -> bool:
    topic = os.environ.get("BOARD_NOTIFY_NTFY_TOPIC", "")
    if not topic:
        print("board_notify: BOARD_NOTIFY_NTFY_TOPIC unset", file=sys.stderr)
        return False
    base = os.environ.get("BOARD_NOTIFY_NTFY_URL",
                          "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(
        f"{base}/{topic}", data=body[:900].encode(),
        headers={"Title": title, **({"Click": url} if url else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"board_notify: ntfy failed: {e}", file=sys.stderr)
        return False


def _file_send(title: str, body: str, url: str) -> bool:
    sink = Path(os.environ.get("BOARD_NOTIFY_FILE",
                               "/tmp/board-notify.jsonl"))
    try:
        with sink.open("a") as f:
            f.write(json.dumps({
                "at": datetime.now(timezone.utc).isoformat(),
                "title": title, "body": body, "url": url},
                ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        print(f"board_notify: file sink failed: {e}", file=sys.stderr)
        return False


CHANNELS = {
    "ha": _ha_send,
    "yomi": _yomi_send,
    "ntfy": _ntfy_send,
    "file": _file_send,
}


def send(title: str, body: str = "",
         url: str | None = None, channel: str | None = None) -> bool:
    """One push. channel defaults to BOARD_NOTIFY_CHANNEL / 'ha' and
    accepts a comma list ('ha,yomi') — fans out to each, True when any
    channel accepted. 'off' is a silent no-op (for quiet contexts)."""
    chan = (channel or os.environ.get("BOARD_NOTIFY_CHANNEL") or "ha").strip()
    if chan == "off":
        return True
    if url is None:
        url = os.environ.get("BOARD_NOTIFY_CLICK", "/chaba-admin/board")
    ok_any = False
    for c in [x.strip() for x in chan.split(",") if x.strip()]:
        fn = CHANNELS.get(c)
        if not fn:
            print(f"board_notify: unknown channel {c!r}", file=sys.stderr)
            continue
        ok_any = fn(title, body, url) or ok_any
    return ok_any


if __name__ == "__main__":
    args = sys.argv[1:]
    chan = None
    if args[:1] == ["--channel"]:
        chan, args = args[1], args[2:]
    if not args:
        print(__doc__)
        sys.exit(2)
    ok = send(args[0], args[1] if len(args) > 1 else "", channel=chan)
    print("sent" if ok else "FAILED")
    sys.exit(0 if ok else 1)
