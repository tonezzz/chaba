"""Simple HTTP server for the Gold/THB/USD causality app."""
import http.server
import os
import socketserver
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("PORT", 8050))


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    os.chdir(ROOT)
    url = f"http://localhost:{PORT}/app/"
    print(f"Serving {ROOT} at {url}")
    with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
        webbrowser.open(url)
        httpd.serve_forever()
