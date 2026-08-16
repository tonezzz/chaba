"""CORS HTTP endpoint for live mcp_debug savings JSON with cached refresh."""
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .reports import mcp_report

REFRESH_INTERVAL = 60

_cache = {
    "report": None,
    "generated": 0.0,
    "refreshing": False,
}
_cache_lock = threading.Lock()


def _regenerate_cache():
    with _cache_lock:
        if _cache["refreshing"]:
            return
        _cache["refreshing"] = True
    try:
        result = mcp_report(hosts=[], save=False, format="json")
        with _cache_lock:
            _cache["report"] = result.get("report") if result.get("ok") else None
            _cache["generated"] = time.time()
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
        if parsed.path != "/mcp-savings.json":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"not found"}')
            return

        query = parse_qs(parsed.query)
        force = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
        report = _get_report(force=force)

        if report is None:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"report generation failed"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=60")
        self._send_cors()
        self.end_headers()
        self.wfile.write(report.encode())

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
