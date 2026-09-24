#!/usr/bin/env python3
"""One-time Google OAuth consent flow for Ada's calendar/tasks tools.

Reuses the existing Desktop-app OAuth client in
~/.config/secrets/google_credentials.json (project gen-lang-client-* — the
same project as the Gemini API key; enable the Calendar and Tasks APIs on
it first). Spins up a loopback listener for the redirect, exchanges the
code, and writes a refresh-token file:

    ~/.config/secrets/ada-google-calendar-token.json   (chmod 600)

Scopes requested: calendar.readonly + calendar.events + tasks.

NOTE: if the project's OAuth consent screen is in "Testing" status, refresh
tokens expire after 7 days — publish the app in the console first.

Usage:
  google-calendar-auth.py                 # local consent + write token file
  google-calendar-auth.py --host mn01     # also scp the token file to a host
  google-calendar-auth.py --check         # verify the stored token refreshes
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CLIENT_FILE = Path.home() / ".config/secrets/google_credentials.json"
TOKEN_FILE = Path.home() / ".config/secrets/ada-google-calendar-token.json"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]
CAL_LIST = "https://www.googleapis.com/calendar/v3/users/me/calendarList"


def _post_form(url: str, form: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _load_client(path: Path) -> dict:
    data = json.loads(path.read_text())
    client = data.get("installed") or data.get("web")
    if not isinstance(client, dict) or "client_id" not in client:
        raise SystemExit(f"{path}: expected an OAuth client JSON ('installed' or 'web' key)")
    return client


def _consent(client: dict) -> dict:
    """Run the loopback consent flow; returns the token response."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"
    url = AUTH_URI + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    })
    print("Open this URL in the browser signed into your Google account:\n")
    print(f"  {url}\n")
    webbrowser.open(url)
    print(f"Waiting for the redirect on {redirect_uri} ...")
    server.handle_request()  # single request: the OAuth redirect
    code = getattr(server, "auth_code", None)
    if not code:
        raise SystemExit("no authorization code received — consent was denied or timed out")
    return _post_form(TOKEN_URI, {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
    })


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        code = urllib.parse.parse_qs(query).get("code", [None])[0]
        self.server.auth_code = code
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Ada calendar auth received - you can close this tab.")

    def log_message(self, *args):
        pass


def _write_token(client: dict, tokens: dict, out: Path) -> None:
    if "refresh_token" not in tokens:
        raise SystemExit(
            "no refresh_token in the response — the account likely already "
            "consented without access_type=offline; revoke ada at "
            "myaccount.google.com/permissions and re-run."
        )
    payload = {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": tokens["refresh_token"],
        "token_uri": TOKEN_URI,
        "scopes": SCOPES,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    out.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"wrote {out} (chmod 600)")


def _check(token_file: Path) -> int:
    data = json.loads(token_file.read_text())
    tokens = _post_form(data.get("token_uri") or TOKEN_URI, {
        "grant_type": "refresh_token",
        "client_id": data["client_id"],
        "client_secret": data["client_secret"],
        "refresh_token": data["refresh_token"],
    })
    if "access_token" not in tokens:
        print(f"FAIL: refresh rejected: {tokens}")
        return 1
    calendars = _get_json(CAL_LIST, tokens["access_token"])
    names = [c.get("summary", c["id"]) for c in calendars.get("items", [])]
    print(f"OK: token refreshes; {len(names)} calendars visible: {', '.join(names[:8])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", type=Path, default=CLIENT_FILE, help="OAuth client JSON")
    ap.add_argument("--output", type=Path, default=TOKEN_FILE, help="token file to write")
    ap.add_argument("--host", help="scp the token file to this SSH host afterwards")
    ap.add_argument("--check", action="store_true", help="verify the stored token refreshes + list calendars")
    args = ap.parse_args()

    if args.check:
        return _check(args.output)

    client = _load_client(args.client)
    tokens = _consent(client)
    _write_token(client, tokens, args.output)

    if args.host:
        remote = "~/.config/secrets/ada-google-calendar-token.json"
        subprocess.run(["ssh", args.host, "mkdir -p ~/.config/secrets"], check=True)
        subprocess.run(["scp", "-q", str(args.output), f"{args.host}:{remote}"], check=True)
        subprocess.run(["ssh", args.host, f"chmod 600 {remote}"], check=True)
        print(f"copied -> {args.host}:{remote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
