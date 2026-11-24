#!/usr/bin/env python3
"""Fixture server for the ada-chat-card browser harness.

Serves the worktree root so the REAL card file under test is loaded from
/stacks/tony-dell/ada-ha/www/ada-chat-card.js, plus:

  /tests/ha/ada-chat-card/harness.html      the harness page
  /tests/ha/ada-chat-card/fixtures/assets/*  png/gif/mp4/webm fixtures
  /dl/<name>                                Content-Disposition: attachment
  /gone/<path>                              HTTP 410 (expired/removed media)
  /bogus/image.png                          HTTP 200 but text/html body
                                            (corrupt "image" — img error path)
  /api/auth/status                          stub {"name":"tester"} — the card's
                                            _pushChatId probe when member unset
  /qc-picker/api/session                    stateful SESSION.json fixture —
                                            pending asset + recorded
                                            <asset>_qc_decision keys
  /qc-picker/api/qc-decision  (POST)        records {asset,decision,note}
  /qc-picker/img/<asset>                    serves the png fixture (thumb)
  /qc-picker/__control       (POST)         {"pending": asset|null,
                                            "clear_decisions": bool}
  /qc-picker/__state         (GET)          dump recorded decisions

Usage: python3 tests/ha/ada-chat-card/server.py [--port 8777]
"""
import argparse
import json
import mimetypes
import os
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FIXTURES = os.path.join(HERE, "fixtures")

MIME = {
    ".png": "image/png",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}

# Stateful fixture for the card's Adobe Stock QC panel — mirrors
# picker-server's /api/session + /api/qc-decision contract: a decision
# POST writes comparison[<asset_underscored>_qc_decision] into the session
# the next /api/session GET returns, exactly like qc_decision() does to
# the real SESSION.json on Drive.
QC_STATE = {"pending": None, "decisions": {}}
QC_DEFAULT_ASSET = "qc-fixture-candidate"


def qc_session_body():
    comp = {}
    if QC_STATE["pending"]:
        comp["last_landed"] = {
            "asset_id": QC_STATE["pending"],
            "lane": "gemini-image",
            "job_id": "gemini-2.5-flash-image",
            "at": "2026-11-24T00:00:00+00:00",
        }
        for asset, d in QC_STATE["decisions"].items():
            comp[asset.replace("-", "_") + "_qc_decision"] = d["decision"]
            comp[asset.replace("-", "_") + "_qc_note"] = d.get("note", "")
    return {
        "session_id": "QC-FIXTURE",
        "status": "human_qc_pending" if QC_STATE["pending"] else "idle",
        "current_stage": "40-qc-review",
        "comparison": comp,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WORKTREE, **kw)

    def log_message(self, fmt, *args):  # quiet access log
        pass

    def _type_for(self, path):
        ext = os.path.splitext(path)[1].lower()
        return MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"

    def _send_file(self, full, ctype, extra_headers=None):
        try:
            data = open(full, "rb").read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json_out(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _qc_route(self):
        path = self.path.split("?", 1)[0]
        if not path.startswith("/qc-picker"):
            return False
        if path == "/qc-picker/api/session":
            self._json_out(qc_session_body())
            return True
        if path == "/qc-picker/__state":
            self._json_out({"pending": QC_STATE["pending"],
                            "decisions": QC_STATE["decisions"]})
            return True
        if path.startswith("/qc-picker/img/"):
            # candidate thumb — any asset serves the png fixture
            full = os.path.join(FIXTURES, "assets", "ada-harness.png")
            self._send_file(full, "image/png")
            return True
        return False

    def _qc_post(self):
        path = self.path.split("?", 1)[0]
        if not path.startswith("/qc-picker"):
            return False
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._json_out({"ok": False, "error": "bad json"}, 400)
            return True
        if path == "/qc-picker/api/qc-decision":
            asset = str(body.get("asset", ""))[:120]
            decision = str(body.get("decision", ""))[:40]
            note = str(body.get("note", ""))[:400]
            if not asset or decision not in ("keep", "reject", "revise"):
                self._json_out({"ok": False,
                                "error": "asset + decision required"}, 400)
                return True
            QC_STATE["decisions"][asset] = {
                "decision": decision, "note": note,
                "at": datetime.now(timezone.utc).isoformat()}
            self._json_out({"ok": True, "result": "ok"})
            return True
        if path == "/qc-picker/__control":
            if "pending" in body:
                QC_STATE["pending"] = body["pending"]
            if body.get("clear_decisions"):
                QC_STATE["decisions"].clear()
            self._json_out({"ok": True})
            return True
        self._json_out({"ok": False, "error": "not found"}, 404)
        return True

    def _route(self):
        path = self.path.split("?", 1)[0]

        if path == "/api/auth/status":
            body = json.dumps({"name": "tester"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return True

        if path.startswith("/dl/"):
            name = os.path.basename(path[len("/dl/"):]) or "download.bin"
            full = os.path.join(FIXTURES, "download-note.txt")
            self._send_file(full, "text/plain; charset=utf-8",
                            {"Content-Disposition": f'attachment; filename="{name}"'})
            return True

        if path.startswith("/gone/"):
            self.send_error(410, "Gone")
            return True

        if path == "/bogus/image.png":
            # 200 but not an image — exercises the img decode-error path
            body = b"<html><body>this is not a png</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return True

        if path == "/apps/yolo/api/image":
            # path-pattern image URL (no file extension) — serves real png so
            # the /image[/?] render rule is exercised without a broken asset
            full = os.path.join(FIXTURES, "assets", "ada-harness.png")
            self._send_file(full, "image/png")
            return True

        if self._qc_route():
            return True

        return False

    def do_GET(self):
        if not self._route():
            # force correct media types for fixtures/card assets
            path = self.path.split("?", 1)[0]
            full = os.path.normpath(os.path.join(WORKTREE, path.lstrip("/")))
            if os.path.isfile(full) and full.startswith(WORKTREE):
                self._send_file(full, self._type_for(path))
            else:
                super().do_GET()

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if not self._qc_post():
            self.send_error(404)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ada-chat-card harness server: http://{args.host}:{args.port}")
    print(f"  harness: http://{args.host}:{args.port}/tests/ha/ada-chat-card/harness.html")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
