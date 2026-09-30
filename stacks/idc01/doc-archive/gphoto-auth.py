#!/usr/bin/env python3
"""One-time OAuth grant for Google Photos Picker — mints the
photospicker.mediaitems.readonly refresh token doc-archive needs.

The Drive token in rclone.conf only has `drive` scope; the Picker API
needs its own grant. Run this on a machine WITH a browser (the consent
redirect lands on 127.0.0.1:<port>):

    python3 gphoto-auth.py [--rclone ~/.config/rclone/rclone.conf]

It prints the consent URL, starts a localhost listener, and exchanges the
code for a refresh token — then prints ONLY the env line to append to
~/.config/secrets/doc-archive.env on idc01.

Headless path: open the URL on any signed-in device, let the browser
fail to reach 127.0.0.1:<port>, copy the full redirect URL from the
address bar, and paste it when prompted (the script extracts ?code=).
"""
import argparse
import configparser
import http.server
import json
import sys
import threading
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORT = 53683


def creds(conf_path):
    cp = configparser.ConfigParser()
    if not cp.read(conf_path):
        sys.exit(f"rclone conf not readable: {conf_path}")
    g = cp["gdrive"]
    return g["client_id"], g["client_secret"]


def exchange(code, client_id, client_secret, redirect_uri):
    body = urllib.parse.urlencode({
        "code": code, "client_id": client_id,
        "client_secret": client_secret, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"}).encode()
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(TOKEN_URL, data=body), timeout=30).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rclone",
                    default="~/.config/rclone/rclone.conf")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    import os
    client_id, client_secret = creds(os.path.expanduser(args.rclone))
    redirect_uri = f"http://127.0.0.1:{args.port}/"

    params = urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent"})
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    print("\nOpen this URL on a device signed into the Google account:\n")
    print(f"  {url}\n")

    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path).query
            got["code"] = urllib.parse.parse_qs(q).get("code", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                "Picker auth received — return to the terminal.".encode())
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", args.port), H)
    srv.timeout = 240
    threading.Thread(target=srv.handle_request, daemon=True).start()

    pasted = ""
    try:
        pasted = input("Waiting — press Enter after approving (or paste the "
                       "full redirect URL here): ").strip()
    except EOFError:
        pass
    code = got.get("code") or urllib.parse.parse_qs(
        urllib.parse.urlparse(pasted).query).get("code", [""])[0]
    if not code:
        sys.exit("no code received")

    tok = exchange(code, client_id, client_secret, redirect_uri)
    rt = tok.get("refresh_token")
    if not rt:
        sys.exit(f"no refresh_token in response: {tok}")
    print("\nAppend this line to ~/.config/secrets/doc-archive.env on idc01, "
          "then restart doc-archive.service:\n")
    print(f"GPHOTO_REFRESH_TOKEN={rt}")


if __name__ == "__main__":
    main()
