#!/usr/bin/env python3
"""Telegram ingress + card command router for the DevNest Home supergroup.

Capture: authenticates the chat and sender, records each update, and replies
in the originating topic. Commands (anchored whole-message forms only):

  explain|status <ref|card-id>   read-only card summary via board-api GET
  APPROVE <ref|card-id>          board-api /respond (open ask/request) or
  REJECT  <ref|card-id>          /action (review card -> close|hold)

Refs normalize like the board: bare digits -> OPS-XXXX, 'ops 0905'/'ops-0905'
-> OPS-0905, anything else must be an exact card id. Unknown or ambiguous
refs are refused and audited (STATE_DIR/audit.jsonl). Approvals only run for
TELEGRAM_APPROVER_IDS (default: callers labelled *tony). All board mutations
go through board-api HTTP — never card YAML or shell execution.

A loopback /send endpoint remains for the board/job notification phase.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
AUDIT_FILE = STATE_DIR / "audit.jsonl"
CONVERSATIONS_DIR = STATE_DIR / "conversations"
POLL_TIMEOUT = int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "25"))
TEXT_POLICY = os.environ.get("DEVNEST_TEXT_POLICY", "private-retained")
BOARD_API = os.environ.get(
    "BOARD_API_BASE", "http://127.0.0.1:8787").rstrip("/")
# APPROVE/REJECT gate: explicit id allowlist wins; otherwise callers whose
# label ends in 'tony' (the board's owner identity, e.g. 'user-tony').
APPROVER_IDS = {
    int(value.strip())
    for value in os.environ.get("TELEGRAM_APPROVER_IDS", "").split(",")
    if value.strip()
} or {
    uid for uid, label in CALLERS.items()
    if label.strip().lower().endswith("tony")
}
COMMAND_RE = re.compile(
    r"^\s*(explain|status|approve|reject)\s+(.+?)\s*$", re.IGNORECASE)
BARE_VERB_RE = re.compile(
    r"^\s*(explain|status|approve|reject)\s*$", re.IGNORECASE)
_REF_RE = re.compile(r"^([A-Za-z]{3})-?(\d{1,4})$")
_NUMERIC_RE = re.compile(r"^\d{1,4}$")
_SPACED_REF_RE = re.compile(r"^([A-Za-z]{3})\s+(\d{1,4})$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")
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


# --- board-api command surface (read via GET /cards; writes via POST only) --


def normalize_ref(token: str) -> str | None:
    """'0905' -> 'OPS-0905', 'ops 0911'/'OPS-0911' -> 'OPS-0911', or a slug."""
    t = re.sub(_SPACED_REF_RE, r"\1-\2", token.strip().strip(".,;:!?\"'`"))
    m = _REF_RE.match(t)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):04d}"
    if _NUMERIC_RE.match(t):
        return f"OPS-{int(t):04d}"
    if _SLUG_RE.match(t.lower()):
        return t.lower()
    return None


def parse_command(text: str) -> tuple[str, str] | None:
    """Anchored whole-message commands only — 'please explain 0905' is not
    one. Returns (verb, raw operand) or None."""
    m = COMMAND_RE.match(text or "")
    if m:
        return m.group(1).lower(), m.group(2)
    m = BARE_VERB_RE.match(text or "")
    if m:
        return m.group(1).lower(), ""
    return None


def _board_get(path: str) -> dict:
    req = Request(f"{BOARD_API}{path}")
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def _board_post(path: str, body: dict) -> dict:
    req = Request(
        f"{BOARD_API}{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"board-api {path} -> {exc.code}: {detail}")


def _card_index() -> dict:
    data = _board_get("/cards")
    index: dict[str, list] = {}
    for card in data.get("cards", []):
        ref = str(card.get("ref") or "").strip().upper()
        cid = str(card.get("id") or "").strip()
        for key in (ref, cid):
            if key:
                index.setdefault(key, []).append(card)
    return index


def resolve_card(index: dict, operand: str) -> dict:
    """Exact ref-or-id resolution. One hit wins; zero/many refuse."""
    hits, seen = [], set()
    for key in (operand.upper(), operand.lower()):
        for card in index.get(key, []):
            cid = card.get("id")
            if cid not in seen:
                seen.add(cid)
                hits.append(card)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"unknown ref {operand} — no card matches")
    names = ", ".join(str(c.get("id")) for c in hits[:3])
    raise LookupError(f"ambiguous ref {operand} — matches: {names}")


def _open_requests(card: dict) -> list:
    return [r for r in card.get("requests") or []
            if r.get("status") not in ("answered", "closed")]


def _status_line(card: dict) -> str:
    col = str(card.get("column") or "backlog")
    a = card.get("action") or {}
    if a.get("status"):
        return f"{col} (action: {a.get('type') or '?'} {a['status']})"
    return col


def _phase_line(card: dict) -> str:
    a = card.get("action") or {}
    col = str(card.get("column") or "backlog")
    if a.get("status") == "running":
        return f"dispatch running on {a.get('runner') or 'unclaimed'}"
    if a.get("status") == "queued":
        return "queued for dispatch"
    if col == "review":
        return f"awaiting review ({card.get('review_kind') or 'verify'})"
    if col == "done":
        return "closed"
    if col == "doing":
        return "in progress"
    return col


def _verified_line(card: dict) -> str:
    checks = [c for c in card.get("checks") or [] if c.get("k") == "verify"]
    if checks:
        mark = {True: "ok", False: "failed"}.get(checks[-1].get("ok"), "pending")
        return f"{mark}: {str(checks[-1].get('how') or '')[:160]}"
    for entry in reversed(card.get("comms") or []):
        if "verif" in str(entry.get("text") or "").lower():
            return (f"{entry.get('from')}@{entry.get('at')}: "
                    f"{str(entry.get('text'))[:160]}")
    return "none recorded"


def _next_line(card: dict) -> str:
    a = card.get("action") or {}
    if card.get("column") == "done":
        return "none — card closed"
    if a.get("status") == "queued":
        return "queued — awaiting runner claim"
    if a.get("status") == "running":
        return "runner in progress — next: finish + verify"
    note = str(card.get("note") or "").strip()
    return note[:200] if note else "none recorded"


def _ask_line(card: dict) -> str:
    ask = card.get("ask")
    if isinstance(ask, str):
        ask = {"question": ask}
    if isinstance(ask, dict) and ask.get("status") != "answered" \
            and str(ask.get("question") or "").strip():
        return str(ask["question"])[:200]
    open_reqs = _open_requests(card)
    if open_reqs:
        bits = [str(r.get("ask") or r.get("needed") or r.get("id") or "?")[:80]
                for r in open_reqs[:2]]
        tail = f" (+{len(open_reqs) - 2} more)" if len(open_reqs) > 2 else ""
        return "; ".join(bits) + tail
    return "none"


def summarize_card(card: dict) -> str:
    """Deterministic status/phase/verified/next/ask — same card state in,
    same text out."""
    head = " ".join(x for x in (
        f"[{SPEAKER}]",
        str(card.get("ref") or ""),
        str(card.get("id") or ""),
        "—",
        str(card.get("title") or "")) if x)
    return "\n".join((
        head,
        f"status: {_status_line(card)}",
        f"phase: {_phase_line(card)}",
        f"verified: {_verified_line(card)}",
        f"next: {_next_line(card)}",
        f"ask: {_ask_line(card)}",
    ))


def _apply_decision(card: dict, verb: str) -> str:
    """Sanctioned mutation paths only: /respond for a pending question,
    /action for a review-column verdict. Nothing else mutates."""
    answer = f"{verb} via devnest-tg"
    open_reqs = _open_requests(card)
    if len(open_reqs) > 1:
        raise LookupError(
            f"{len(open_reqs)} open requests — name one on the board, "
            f"bare {verb.upper()} cannot pick")
    if len(open_reqs) == 1:
        rid = str(open_reqs[0].get("id") or "request")
        res = _board_post("/respond", {
            "id": card["id"], "request_id": rid,
            "answer": answer, "from": "tony"})
        return f"answered {rid} ({res.get('message', 'ok')})"
    ask = card.get("ask")
    ask_open = (isinstance(ask, str) and ask.strip()) or \
        (isinstance(ask, dict) and ask.get("status") != "answered"
         and str(ask.get("question") or "").strip())
    if ask_open:
        res = _board_post("/respond", {
            "id": card["id"], "answer": answer, "from": "tony"})
        return f"answered ask ({res.get('message', 'ok')})"
    if card.get("column") == "review":
        do = "close" if verb == "approve" else "hold"
        res = _board_post("/action", {
            "id": card["id"], "do": do, "from": "tony"})
        return f"action {do} ({res.get('message', 'ok')})"
    raise LookupError(
        f"nothing pending — no open ask/request, column="
        f"{card.get('column')}")


def _audit(event: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    event.setdefault("at", _now())
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def handle_command(update: dict, msg: dict, chat_id: int, sender: dict,
                   topic: str, thread_id: int | None) -> bool:
    """Run a board command if the message is one. True = handled (the
    generic capture ack is skipped)."""
    parsed = parse_command(msg.get("text") or "")
    if not parsed:
        return False
    verb, operand_raw = parsed
    sender_id = sender.get("id")
    event = {
        "update_id": update.get("update_id"),
        "message_id": msg.get("message_id"),
        "sender_id": sender_id,
        "sender_label": CALLERS.get(sender_id),
        "command": verb, "operand": operand_raw,
        "chat_id": chat_id, "topic": topic, "thread_id": thread_id,
    }

    def refuse(reason: str) -> None:
        event["result"] = "refused"
        event["detail"] = reason
        _audit(event)
        LOG.warning("refused %s %r sender=%s: %s",
                    verb, operand_raw, sender_id, reason)
        _send_text(chat_id, f"[{SPEAKER}] {verb} refused: {reason}", thread_id)

    operand = normalize_ref(operand_raw) if operand_raw else None
    event["normalized"] = operand
    if operand is None:
        refuse("usage: explain <ref|card-id>, APPROVE <ref>, REJECT <ref>"
               if not operand_raw
               else f"unparseable ref {operand_raw!r}")
        return True
    if verb in ("approve", "reject") and sender_id not in APPROVER_IDS:
        refuse("sender not in approver allowlist")
        return True
    try:
        card = resolve_card(_card_index(), operand)
    except LookupError as exc:
        refuse(str(exc))
        return True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError,
            RuntimeError) as exc:
        refuse(f"board-api unavailable: {exc}")
        return True
    event["card"] = card.get("id")
    if verb in ("explain", "status"):
        _send_text(chat_id, summarize_card(card), thread_id)
        event["result"] = "explained"
        _audit(event)
        LOG.info("explained %s for sender=%s topic=%s",
                 card.get("id"), sender_id, topic)
        return True
    try:
        outcome = _apply_decision(card, verb)
    except (LookupError, RuntimeError, ValueError) as exc:
        refuse(str(exc))
        return True
    event["result"] = f"{verb}d"
    event["detail"] = outcome
    _audit(event)
    LOG.info("%s %s (%s) for sender=%s: %s",
             verb.upper(), card.get("ref"), card.get("id"), sender_id, outcome)
    _send_text(
        chat_id,
        f"[{SPEAKER}] {verb.upper()} {card.get('ref') or card.get('id')}: "
        f"{outcome}",
        thread_id,
    )
    return True


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
    if handle_command(update, msg, chat_id, sender, topic, thread_id):
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
                # A poison update must not wedge the loop — it is logged,
                # skipped past, and the offset still advances.
                try:
                    handle_update(update)
                except Exception:
                    LOG.exception("update %s failed", update_id)
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
