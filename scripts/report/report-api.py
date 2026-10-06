#!/usr/bin/env python3
"""report-api — on-demand trigger + status for the chaba report chain.

  GET  /health  -> {"ok": true}
  GET  /status  -> {"running": bool, "generated_at": str|null}
  POST /refresh -> start chaba-system-report.service (L1 host audits ->
                   L2 fleet rollup -> L3 system report — refreshing the
                   top level refreshes every linked layer). 409 while a
                   run is in flight.

Write gate mirrors board-api: POSTs need a verified tailnet identity
(Tailscale-User-Login, injected by tailscale serve and re-checked here
against the client IP chain) or a direct loopback caller. Caddy also
denies anonymous writes at the edge (stacks/web/Caddyfile).
"""
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
from pathlib import Path

# Reuse board-api's write gate (hyphenated filename — load by path so the
# tailnet-identity check stays single-sourced).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "board_api", Path(__file__).resolve().parent.parent / "board" / "board-api.py")
_board_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_board_api)
caller_identity = _board_api.caller_identity

REPO = Path(__file__).resolve().parent.parent.parent
SUMMARY_YML = REPO / "stacks/web/public/apps/system-report/data/system-report.yml"
SERVICE = "chaba-system-report.service"
PORT = int(os.environ.get("REPORT_API_PORT", "8792"))


def _running() -> bool:
    return subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", SERVICE],
        check=False).returncode == 0


def _generated_at() -> str | None:
    try:
        import yaml
        doc = yaml.safe_load(SUMMARY_YML.read_text())
        return str((doc or {}).get("generated_at") or "") or None
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "report-api/1"

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"ok": True})
        elif self.path == "/status":
            self._json(200, {"running": _running(),
                             "generated_at": _generated_at()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/refresh":
            self._json(404, {"error": "not found"})
            return
        who = caller_identity(self.headers, self.client_address[0])
        if not who:
            self._json(403, {"error": "writes need a tailnet identity"})
            return
        if _running():
            self._json(409, {"ok": False, "running": True,
                             "generated_at": _generated_at()})
            return
        proc = subprocess.run(
            ["systemctl", "--user", "start", SERVICE],
            check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            self._json(500, {"ok": False,
                             "error": proc.stderr.strip() or "start failed"})
            return
        self._json(202, {"ok": True, "started_by": who})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("report-api %s\n" % (fmt % args))


if __name__ == "__main__":
    import unittest
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        sys.exit(unittest.main(argv=[sys.argv[0]]))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
