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

Usage: python3 tests/ha/ada-chat-card/server.py [--port 8777]
"""
import argparse
import json
import mimetypes
import os
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
