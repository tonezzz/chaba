#!/usr/bin/env python3
"""Combined Funnel landing page, docs, and active Tailscale connections API for tony-dell."""

import http.server
import json
import mimetypes
import os
import socketserver
import subprocess

PORT = int(os.environ.get("FUNNEL_PORT", "8080"))
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(STATIC_DIR, "public", "apps", "docs")


class FunnelHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/apps/tailscale-funnel/", "/apps/tailscale-funnel/index.html"):
            self._serve_index()
            return
        if path.startswith("/apps/docs/"):
            self._serve_docs(path)
            return
        if path == "/api/tailscale/connections":
            self._serve_connections()
            return
        if path == "/health":
            self._serve_health()
            return
        self.send_error(404, "Not found")

    def _serve_index(self):
        index_path = os.path.join(STATIC_DIR, "index.html")
        try:
            with open(index_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_error(500, "index.html not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(body)

    def _serve_docs(self, path):
        rel = path[len("/apps/docs/"):]
        if not rel:
            rel = "index.html"
        elif rel.endswith("/"):
            rel += "index.html"

        file_path = os.path.join(DOCS_DIR, rel)
        file_path = os.path.normpath(file_path)

        # Prevent path traversal outside DOCS_DIR
        if not file_path.startswith(os.path.normpath(DOCS_DIR) + os.sep) and file_path != os.path.normpath(DOCS_DIR):
            self.send_error(403, "Forbidden")
            return

        if os.path.isdir(file_path):
            file_path = os.path.join(file_path, "index.html")

        try:
            with open(file_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        except IsADirectoryError:
            self.send_error(404, "Not found")
            return

        content_type, _ = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _serve_health(self):
        self._send_json(200, {"ok": True})

    def _serve_connections(self):
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            data = json.loads(result.stdout)

            users = {
                uid: u.get("DisplayName", uid)
                for uid, u in data.get("User", {}).items()
            }

            peers = []
            for peer_id, p in data.get("Peer", {}).items():
                if not p.get("Online"):
                    continue

                hostname = p.get("HostName", peer_id) or ""
                if not p.get("OS") or "funnel-ingress" in hostname or "controlplane" in hostname:
                    continue

                cur_addr = p.get("CurAddr", "")
                relay = p.get("Relay", "")
                is_direct = bool(cur_addr) and not bool(relay)

                ips = p.get("TailscaleIPs", [])
                ipv4s = [ip for ip in ips if ":" not in ip]
                ip = (ipv4s[0] if ipv4s else (ips[0] if ips else ""))

                last_seen = p.get("LastSeen", "")
                if last_seen == "0001-01-01T00:00:00Z":
                    last_seen = ""

                peers.append(
                    {
                        "id": peer_id,
                        "name": (p.get("DNSName", "").rstrip(".") or p.get("HostName", peer_id)).rstrip("."),
                        "hostname": hostname,
                        "ip": ip,
                        "os": p.get("OS", "?"),
                        "user": users.get(str(p.get("UserID")), p.get("UserID")),
                        "online": p.get("Online", False),
                        "active": p.get("Active", False),
                        "direct": is_direct,
                        "address": cur_addr,
                        "relay": relay,
                        "rx": p.get("RxBytes", 0),
                        "tx": p.get("TxBytes", 0),
                        "last_seen": last_seen,
                    }
                )

            peers.sort(key=lambda x: x["name"].lower())
            self._send_json(200, peers)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _send_json(self, status, payload):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), FunnelHandler) as httpd:
        print(f"chaba-funnel-server listening on :{PORT}")
        httpd.serve_forever()
