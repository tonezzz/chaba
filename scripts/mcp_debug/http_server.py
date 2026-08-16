"""CORS HTTP endpoint for live mcp_debug savings JSON."""
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from .reports import mcp_report


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

        result = mcp_report(hosts=[], format="json")
        if not result.get("ok"):
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._send_cors()
            self.end_headers()
            self.wfile.write(result.get("report", '{"ok":false,"error":"unknown"}').encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors()
        self.end_headers()
        self.wfile.write(result["report"].encode())

    def log_message(self, *args):
        pass


def main(port=9100):
    server = HTTPServer(("0.0.0.0", port), CORSHandler)
    print(f"Listening on http://0.0.0.0:{port}/mcp-savings.json")
    server.serve_forever()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    main(port)
