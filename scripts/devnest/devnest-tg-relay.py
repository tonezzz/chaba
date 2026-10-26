#!/usr/bin/env python3
"""Capture-only Telegram ingress for the DevNest Home supergroup.

This process deliberately does not execute jobs. It authenticates the chat and
sender, records each update, acknowledges it in the originating topic, and
exposes a loopback /send endpoint for the later board/job notification phase.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOG = logging.getLogger("devnest-tg-relay")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
CHAT_IDS = {
    int(value.strip())
    for value in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if value.strip()
}
CALLERS = {}
for mapping in os.environ.get("TELEGRAM_USER_CALLERS", "").split(","):
    if ":" in mapping:
        user_id, label = mapping.split(":", 1)
        if user_id.strip().isdigit() and label.strip():
            CALLERS[int(user_id)] = label.strip()
SPEAKER = os.environ.get("TG_SPEAKER_TAG", "devnestha").strip() or "devnestha"
LISTEN = os.environ.get("TG_WEBHOOK_LISTEN", "127.0.0.1:8919")
STATE_DIR = Path(os.environ.get(
    "DEVNEST_TELEGRAM_STATE",
    str(Path.home() / ".local/share/devnest/telegram"),
))
OFFSET_FILE = STATE_DIR / "state.json"
UPDATES_FILE = STATE_DIR / "updates.jsonl"
CONVERSATIONS_DIR = STATE_DIR / "conversations"
POLL_TIMEOUT = int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "25"))
TEXT_POLICY = os.environ.get("DEVNEST_TEXT_POLICY", "private-retained")
LANES = {
    "general": "home",
    "control": "control",
    "inbox": "inbox",
    "build": "build",
    "review": "review",
    "research": "research",
    "ops": "ops",
    "ha lab": "ha-lab",
    "education": "education",
    "archive": "archive",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _topic(msg: dict) -> tuple[str, int | None]:
    thread_id = msg.get("message_thread_id")
    if thread_id is None:
        return "general", None
    # Telegram does not include the forum topic title in ordinary messages.
    return f"thread-{thread_id}", int(thread_id)


def _lane(topic: str) -> str:
    return LANES.get(topic.casefold(), "unknown")


def _state_offset() -> int | None:
    try:
        return int(json.loads(OFFSET_FILE.read_text()).get("offset"))
    except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_offset(offset: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OFFSET_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset, "saved_at": _now()}))
    tmp.replace(OFFSET_FILE)


def _api(method: str, params: dict | None = None) -> dict:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    body = json.dumps(params or {}).encode()
    req = Request(
        f"{API_BASE}/bot{BOT_TOKEN}/{method}",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urlopen(req, timeout=POLL_TIMEOUT + 15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(result.get("description", f"Telegram {method} failed"))
    return result


def _send_text(chat_id: int, text: str, thread_id: int | None = None) -> None:
    params: dict[str, object] = {"chat_id": chat_id, "text": text[:4000]}
    if thread_id is not None:
        params["message_thread_id"] = thread_id
    _api("sendMessage", params)


def _record(update: dict, msg: dict, chat: dict, sender: dict,
            topic: str, thread_id: int | None, lane: str,
            authorized: bool) -> None:
    chat_id = int(chat["id"])
    sender_id = sender.get("id")
    text = msg.get("text") or msg.get("caption") or ""
    event = {
        "at": _now(),
        "update_id": update.get("update_id"),
        "message_id": msg.get("message_id"),
        "chat_id": chat_id,
        "chat_title": chat.get("title"),
        "chat_type": chat.get("type"),
        "message_thread_id": thread_id,
        "topic": topic,
        "lane": lane,
        "sender_id": sender_id,
        "sender_label": CALLERS.get(sender_id),
        "authorization": "allowed" if authorized else "quarantined",
        "text_policy": TEXT_POLICY if authorized else "metadata-only",
    }
    if authorized and TEXT_POLICY != "metadata-only":
        event["text"] = text
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with UPDATES_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    conversation = CONVERSATIONS_DIR / str(chat_id) / f"{topic}.jsonl"
    conversation.parent.mkdir(parents=True, exist_ok=True)
    with conversation.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def handle_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    sender = msg.get("from") or {}
    topic, thread_id = _topic(msg)
    lane = _lane(topic)
    sender_id = sender.get("id")
    authorized = chat_id in CHAT_IDS and sender_id in CALLERS
    _record(update, msg, chat, sender, topic, thread_id, lane, authorized)
    if not authorized:
        LOG.warning("quarantined chat=%s sender=%s topic=%s",
                    chat_id, sender_id, topic)
        if chat_id in CHAT_IDS and sender_id is not None:
            _send_text(
                chat_id,
                f"[{SPEAKER}] sender not authorized; user id={sender_id}",
                thread_id,
            )
        return
    message_id = msg.get("message_id")
    LOG.info("captured update=%s chat=%s sender=%s topic=%s lane=%s",
             update.get("update_id"), chat_id, sender_id, topic, lane)
    _send_text(
        chat_id,
        f"[{SPEAKER}] captured topic={topic} lane={lane} message={message_id}",
        thread_id,
    )


class PushHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps({
            "ok": True,
            "mode": "poll",
            "chat_ids": sorted(CHAT_IDS),
            "state_dir": str(STATE_DIR),
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/send":
            self.send_error(404)
            return
        size = int(self.headers.get("content-length", "0"))
        try:
            body = json.loads(self.rfile.read(size))
            chat_id = int(body.get("chat_id") or next(iter(CHAT_IDS)))
            thread_id = body.get("message_thread_id")
            _send_text(chat_id, str(body["text"]), thread_id)
            result = {"ok": True, "chat_id": chat_id,
                      "message_thread_id": thread_id}
            encoded = json.dumps(result).encode()
            self.send_response(200)
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            encoded = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(400)
        except Exception as exc:  # outbound API errors are caller-visible
            encoded = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(502)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: object) -> None:
        LOG.info("http: " + fmt, *args)


def serve_http() -> None:
    host, _, port = LISTEN.rpartition(":")
    server = ThreadingHTTPServer((host or "127.0.0.1", int(port or "8919")),
                                 PushHandler)
    server.serve_forever()


def poll() -> None:
    offset = _state_offset()
    while True:
        try:
            params: dict[str, object] = {
                "timeout": POLL_TIMEOUT,
                "limit": 50,
                "allowed_updates": json.dumps(["message", "edited_message"]),
            }
            if offset is not None:
                params["offset"] = offset
            result = _api("getUpdates", params)
            for update in result.get("result", []):
                update_id = int(update["update_id"])
                offset = update_id + 1
                # Persist after capture, before acknowledgement: a restart can
                # at worst repeat a Telegram acknowledgement, not lose input.
                handle_update(update)
                _save_offset(offset)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            LOG.warning("poll error: %s", exc)
            time.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    if not CHAT_IDS:
        raise SystemExit("TELEGRAM_ALLOWED_CHAT_IDS is empty")
    if not CALLERS:
        raise SystemExit("TELEGRAM_USER_CALLERS is empty")
    threading.Thread(target=serve_http, daemon=True).start()
    LOG.info("capture relay listening on %s", LISTEN)
    poll()


if __name__ == "__main__":
    main()
