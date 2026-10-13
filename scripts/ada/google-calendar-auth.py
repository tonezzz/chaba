#!/usr/bin/env python3
"""One-time Google OAuth consent flow for Ada's calendar/tasks tools.

Reuses the existing Desktop-app OAuth client in
~/.config/secrets/google_credentials.json (project gen-lang-client-* — the
same project as the Gemini API key; enable the Calendar and Tasks APIs on
it first). Spins up a loopback listener for the redirect, exchanges the
code, and writes a refresh-token file:

    ~/.config/secrets/ada-google-calendar-token.json          (chmod 600)
    ~/.config/secrets/ada-google-calendar-token-<member>.json (--member)

Scopes requested: calendar.readonly + calendar.events + tasks.

NOTE: if the project's OAuth consent screen is in "Testing" status, refresh
tokens expire after 7 days AND only whitelisted test-user accounts may
consent at all — publish the app in the console first (a published but
unverified app shows a "Google hasn't verified this app" warning the
member can click through: Advanced -> Go to <app>).

Manual-paste mode (--manual): for member-on-phone onboarding where the
member signs in on their own device and this host runs no browser. The
script prints the auth URL with redirect_uri=http://localhost (no port —
allowed unregistered for installed/desktop clients, RFC 8252); the member
opens it, consents, and Google redirects to a dead localhost URL — they
copy the address-bar URL (or just the code= value) and send it back to
paste here. Google's device flow is NOT an alternative: the OAuth device
authorization endpoint rejects the Calendar/Tasks scopes (limited-input
devices only get a small scope whitelist — drive.file, youtube, etc.).

Usage:
  google-calendar-auth.py                            # local consent + write token file
  google-calendar-auth.py --host mn01                # also scp the token file to a host
  google-calendar-auth.py --manual --member kk --host idc03   # member phone flow
  google-calendar-auth.py --check [--member kk]      # verify the stored token refreshes
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
SECRETS_DIR = Path.home() / ".config/secrets"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]
CAL_LIST = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
MANUAL_REDIRECT_URI = "http://localhost"  # no port — dead URL the member pastes back


def _token_path(member: str | None, service: str = "calendar") -> Path:
    """Per-member token convention: ada-google-<svc>-token[-<member>].json.

    The memberless file is the shared/tony token (pre-existing name —
    not renamed so existing lanes keep working)."""
    suffix = f"-{member}" if member else ""
    return SECRETS_DIR / f"ada-google-{service}-token{suffix}.json"


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


def _consent_manual(client: dict) -> dict:
    """Manual-paste flow for member-on-phone onboarding (no local browser,
    no reachable listener). Prints the auth URL with a dead-localhost
    redirect; the member opens it on their phone, consents, and the
    browser lands on an unreachable page whose address-bar URL carries
    ?code=. They send that URL back; we extract the code and exchange it
    with the same redirect_uri."""
    url = AUTH_URI + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"],
        "redirect_uri": MANUAL_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    })
    print("Send this URL to the member — they open it on their phone, sign in")
    print("with THEIR Google account, and approve the scopes:\n")
    print(f"  {url}\n")
    print("Their browser will land on a 'can't reach localhost' page — that is")
    print("expected. Ask them to copy the full URL from the address bar (or just")
    print("the code= value) and send it back.\n")
    pasted = input("Paste the redirect URL or code here: ").strip()
    if not pasted:
        raise SystemExit("nothing pasted — re-run and paste the redirect URL")
    code = pasted
    if "://" in pasted or "=" in pasted:
        parsed = urllib.parse.urlparse(pasted)
        params = urllib.parse.parse_qs(parsed.query or parsed.fragment)
        if "error" in params:
            raise SystemExit(f"consent denied: {params['error'][0]}")
        code = (params.get("code") or [None])[0]
        if not code:
            raise SystemExit("no code= in the pasted URL — copy the full address-bar URL")
    code = urllib.parse.unquote(code)
    return _post_form(TOKEN_URI, {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": MANUAL_REDIRECT_URI,
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
    ap.add_argument("--member", help="household member id (kk, nhong, ...) — token file gains a -<member> suffix")
    ap.add_argument("--service", default="calendar", help="service slug in the token filename (default: calendar)")
    ap.add_argument("--output", type=Path, help="token file to write (default: derived from --member/--service)")
    ap.add_argument("--manual", action="store_true",
                    help="member-on-phone flow: print the auth URL, paste the dead-localhost redirect back")
    ap.add_argument("--host", help="scp the token file to this SSH host afterwards")
    ap.add_argument("--check", action="store_true", help="verify the stored token refreshes + list calendars")
    args = ap.parse_args()

    out = args.output or _token_path(args.member, args.service)

    if args.check:
        return _check(out)

    client = _load_client(args.client)
    tokens = _consent_manual(client) if args.manual else _consent(client)
    _write_token(client, tokens, out)

    if args.host:
        remote = f"~/.config/secrets/{out.name}"
        subprocess.run(["ssh", args.host, "mkdir -p ~/.config/secrets"], check=True)
        subprocess.run(["scp", "-q", str(out), f"{args.host}:{remote}"], check=True)
        subprocess.run(["ssh", args.host, f"chmod 600 {remote}"], check=True)
        print(f"copied -> {args.host}:{remote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
