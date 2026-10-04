#!/usr/bin/env python3
"""board-api — write endpoint for the kanban board page.

Binds 127.0.0.1:8787 on tony-dell; Caddy proxies /apps/board-api/* here
(prefix stripped). Each request edits the card YAML in the *served*
checkout (chaba-tony-dell — the web container bind-mounts that tree),
then re-runs render-board.py so cards.json + index.html refresh
immediately. Git persistence is handled by kanban-commit.timer.

Endpoints (after prefix strip):
  GET  /health                       -> {"ok": true}
  GET  /cards                        -> cards.json payload
  POST /action   {id, do}            do: queue|close|hold|retry
  POST /respond  {id, request_id, answer}
  POST /comment  {id, from, text}    from: devin|ada|chaba|tony

Writes are serialized with an flock so concurrent clicks don't race.
"""
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
LOCK = Path("/tmp/board-api.lock")
PORT = int(os.environ.get("BOARD_API_PORT", "8787"))
ACTORS = {"devin", "ada", "chaba", "tony"}
TRANSITIONS = {"queue", "close", "hold", "retry"}


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def card_path(cid: str) -> Path:
    if not cid or "/" in cid or ".." in cid:
        raise ValueError("bad card id")
    p = CARD_DIR / f"{cid}.yml"
    if not p.exists():
        raise ValueError(f"no card {cid}")
    return p


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def save(p: Path, card: dict) -> None:
    p.write_text(
        yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=110)
    )


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]}
    )


def do_action(card: dict, verb: str, frm: str) -> str:
    a = card.setdefault("action", {})
    st = a.get("status", "idle")
    if verb == "queue":
        if st in ("queued", "running"):
            return f"already {st}"
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
        if card.get("column") in ("done", "review"):
            card["column"] = "backlog"
        comms_add(card, frm, "queued for processing")
        return "queued — kanban-dispatch will claim it"
    if verb == "retry":
        a["status"] = "queued"
        a.pop("result", None)
        comms_add(card, frm, "retry requested")
        return "re-queued"
    if verb == "close":
        card["column"] = "done"
        a["status"] = "done"
        comms_add(card, frm, "closed by Tony")
        return "moved to done"
    if verb == "hold":
        a["status"] = "idle"
        card["column"] = "backlog"
        comms_add(card, frm, "put on hold")
        return "back to backlog"
    raise ValueError(f"unknown verb {verb}")


def do_respond(card: dict, rid: str, answer: str, frm: str) -> str:
    for r in card.get("requests") or []:
        if r.get("id") == rid:
            r["status"] = "answered"
            r["answer"] = answer[:500]
            comms_add(card, frm, f"answered {rid}: {answer[:200]}")
            return "answer saved"
    raise ValueError(f"no request {rid}")


def render() -> None:
    subprocess.run(
        [sys.executable, str(RENDER)], cwd=REPO, timeout=60, check=False
    )


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("board-api %s\n" % (fmt % args))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/cards":
            j = REPO / "stacks/web/public/apps/board/cards.json"
            if j.exists():
                return self._send(200, json.loads(j.read_text()))
            return self._send(404, {"error": "no cards.json yet"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0)) or b"0") or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})

        with LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                if path == "/action":
                    verb = body.get("do", "queue")
                    if verb not in TRANSITIONS:
                        raise ValueError(f"do must be one of {sorted(TRANSITIONS)}")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_action(card, verb, "tony")
                    card["updated"] = now()
                    save(p, card)
                elif path == "/respond":
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_respond(
                        card, body.get("request_id", ""),
                        body.get("answer", "").strip(), "tony")
                    card["updated"] = now()
                    save(p, card)
                elif path == "/comment":
                    frm = body.get("from", "")
                    if frm not in ACTORS:
                        raise ValueError(f"from must be one of {sorted(ACTORS)}")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    comms_add(card, frm, body.get("text", "").strip())
                    card["updated"] = now()
                    save(p, card)
                    msg = "comment added"
                else:
                    return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
            render()
        self._send(200, {"ok": True, "message": msg})


if __name__ == "__main__":
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
