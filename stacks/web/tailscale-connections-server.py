#!/usr/bin/env python3
"""Lightweight API exposing active Tailscale peer connections."""

import http.server
import json
import os
import socketserver
import subprocess

PORT = int(os.environ.get("TAILSCALE_CONNECTIONS_PORT", "9010"))


class TailscaleHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/tailscale/connections":
            self.send_error(404, "Not found")
            return

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

                # Skip Tailscale infrastructure peers (relays / Funnel ingress nodes)
                hostname = p.get("HostName", peer_id) or ""
                if not p.get("OS") or "funnel-ingress" in hostname or "controlplane" in hostname:
                    continue

                cur_addr = p.get("CurAddr", "")
                relay = p.get("Relay", "")
                is_direct = bool(cur_addr) and not bool(relay)

                # Prefer IPv4 for display
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
    with socketserver.TCPServer(("0.0.0.0", PORT), TailscaleHandler) as httpd:
        print(f"tailscale-connections-server listening on :{PORT}")
        httpd.serve_forever()
