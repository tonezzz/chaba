#!/usr/bin/env python3
"""Check Ada's Telegram webhook registration without changing it.

Run on idc03 with TELEGRAM_BOT_TOKEN from telegram-bot.env. The bot API
token is used only to query getWebhookInfo; it is never logged. Problems
are sent through the local Ada TG relay, which can still send outbound
messages if inbound webhook registration is broken.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "board"))
import board_notify  # noqa: E402

EXPECTED_URL = os.environ.get(
    "TELEGRAM_EXPECTED_WEBHOOK_URL",
    "https://api.surf-thailand.com/webhook/tg")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
STATE_FILE = Path(os.environ.get(
    "TELEGRAM_WEBHOOK_WATCH_STATE",
    "~/.local/state/telegram-webhook-watch.json")).expanduser()
REPEAT_AFTER_S = int(os.environ.get(
    "TELEGRAM_WEBHOOK_WATCH_REPEAT_S", str(6 * 60 * 60)))
TIMEOUT_S = 10


def fetch_status(token: str) -> tuple[str, dict | None]:
    """Return a sanitized issue key and result; never expose request URL."""
    if not token:
        return "missing-token", None
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return f"telegram-http-{exc.code}", None
    except Exception as exc:
        # Exception strings from HTTP clients can contain the tokenized URL.
        return f"telegram-{type(exc).__name__.lower()}", None
    if not payload.get("ok") or not isinstance(payload.get("result"), dict):
        return "invalid-telegram-response", None
    result = payload["result"]
    problems = []
    if result.get("url") != EXPECTED_URL:
        problems.append("url-mismatch")
    try:
        pending = int(result.get("pending_update_count") or 0)
    except (TypeError, ValueError):
        pending = 0
        problems.append("invalid-pending-count")
    if pending:
        problems.append(f"pending-{pending}")
    try:
        last_error = int(result.get("last_error_date") or 0)
    except (TypeError, ValueError):
        last_error = 0
    if last_error and time.time() - last_error <= 30 * 60:
        problems.append("delivery-error")
    return ",".join(problems), result


def load_state() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n")
    tmp.replace(STATE_FILE)


def issue_message(issue: str, result: dict | None) -> str:
    if result is None:
        return f"Telegram webhook check failed ({issue}); inspect relay credentials/network."
    parts = []
    if "url-mismatch" in issue:
        if result.get("url"):
            parts.append("webhook URL differs from expected "
                         f"{EXPECTED_URL}")
        else:
            parts.append(f"webhook URL is unset; expected {EXPECTED_URL}")
    if "delivery-error" in issue:
        parts.append("Telegram reports a recent webhook delivery error")
    if issue.startswith("pending-"):
        parts.append(f"{result.get('pending_update_count')} updates are pending")
    elif "pending-" in issue:
        pending_issue = next(
            p for p in issue.split(",") if p.startswith("pending-"))
        parts.append(f"{pending_issue[8:]} updates are pending")
    if "invalid-pending-count" in issue:
        parts.append("Telegram returned an invalid pending-update count")
    return "; ".join(parts) or f"Telegram webhook check failed ({issue})"


def run() -> int:
    issue, result = fetch_status(TOKEN)
    state = load_state()
    previous = str(state.get("issue") or "")
    now = int(time.time())
    should_notify = bool(issue) and (
        issue != previous
        or now - int(state.get("notified_at") or 0) >= REPEAT_AFTER_S)
    if should_notify:
        accepted = board_notify.send(
            "[telegram] webhook health",
            issue_message(issue, result),
            url="")
        if not accepted:
            print("telegram-webhook-watch: alert delivery failed",
                  file=sys.stderr)
            return 1
        state["notified_at"] = now
    elif not issue and previous:
        accepted = board_notify.send(
            "[telegram] webhook recovered",
            f"Webhook registration is healthy at {EXPECTED_URL}; "
            "no pending updates or delivery error.",
            url="")
        if not accepted:
            print("telegram-webhook-watch: recovery delivery failed",
                  file=sys.stderr)
            return 1
    state["issue"] = issue
    state["checked_at"] = now
    save_state(state)
    if issue:
        print(f"telegram-webhook-watch: alert state={issue}")
        return 1
    print("telegram-webhook-watch: healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
