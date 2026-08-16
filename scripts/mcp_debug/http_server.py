"""CORS HTTP endpoint for live mcp_debug savings JSON with cached refresh."""
import threading
import time
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .config import HOSTS
from .reports import mcp_report
from .formatters import mcp_table

REFRESH_INTERVAL = 60

_cache = {
    "report": None,
    "generated": 0.0,
    "collected_at": None,
    "duration_ms": 0.0,
    "refreshing": False,
}
_cache_lock = threading.Lock()


def _regenerate_cache():
    with _cache_lock:
        if _cache["refreshing"]:
            return
        _cache["refreshing"] = True
    try:
        start = time.perf_counter()
        result = mcp_report(hosts=[], save=False, format="json")
        duration_ms = (time.perf_counter() - start) * 1000
        with _cache_lock:
            _cache["report"] = result.get("report") if result.get("ok") else None
            _cache["generated"] = time.time()
            _cache["collected_at"] = datetime.now().isoformat()
            _cache["duration_ms"] = round(duration_ms, 2)
    finally:
        with _cache_lock:
            _cache["refreshing"] = False


def _get_report(force=False):
    with _cache_lock:
        now = time.time()
        if _cache["report"] is not None and not force and (now - _cache["generated"]) < REFRESH_INTERVAL:
            return _cache["report"]
    _regenerate_cache()
    with _cache_lock:
        return _cache["report"]


def _background_refresh():
    _regenerate_cache()
    threading.Timer(REFRESH_INTERVAL, _background_refresh).start()


class CORSHandler(BaseHTTPRequestHandler):
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/mcp-table.json":
            self._handle_table(parsed)
            return
        if parsed.path == "/mcp-savings.json":
            self._handle_savings(parsed)
            return
        if parsed.path == "/health":
            self._send_json(200, {"ok": True})
            return

        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(b'{"ok":false,"error":"not found"}')

    def _handle_table(self, parsed):
        query = parse_qs(parsed.query)
        host = query.get("host", [""])[0]
        command = query.get("command", [""])[0]

        if not host or not command:
            self._send_json(400, {"ok": False, "error": "host and command query params required"})
            return

        if host not in HOSTS:
            self._send_json(404, {"ok": False, "error": f"unknown host: {host}"})
            return

        result = mcp_table(host, command)
        status = 200 if result.get("ok") else 500
        self._send_json(status, result)

    def _handle_savings(self, parsed):
        query = parse_qs(parsed.query)
        force = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
        report = _get_report(force=force)

        if report is None:
            self._send_json(500, {"ok": False, "error": "report generation failed"})
            return

        payload = json.loads(report)
        payload["freshness"] = {
            "collected_at": _cache.get("collected_at"),
            "cache_age_ms": round((time.time() - _cache["generated"]) * 1000, 1),
            "duration_ms": _cache.get("duration_ms", 0.0),
        }
        self._send_json(200, payload)

    def _send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=60")
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main(port=9100):
    _regenerate_cache()
    threading.Timer(REFRESH_INTERVAL, _background_refresh).start()
    server = HTTPServer(("0.0.0.0", port), CORSHandler)
    print(f"Listening on http://0.0.0.0:{port}/mcp-savings.json")
    server.serve_forever()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    main(port)
