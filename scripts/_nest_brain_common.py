"""Shared Drive REST client for nest-brain tooling.

Reuses the rclone gdrive token exactly like scripts/bench-gdrive.py:
read ~/.config/rclone/rclone.conf; when rclone uses its built-in OAuth
client (empty client_id) a throwaway `rclone lsf` refreshes + rewrites
the token and we reuse the new access_token.
"""
import configparser
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RCLONE_CONF = os.path.expanduser("~/.config/rclone/rclone.conf")
REMOTE = "gdrive"
API = "https://www.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def log(msg):
    print(f"nest-brain-drive: {msg}", file=sys.stderr)


def _rclone(args, timeout=120):
    r = subprocess.run(["rclone"] + args, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"rclone {' '.join(args)} rc={r.returncode}: {r.stderr.decode()[:200]}")
    return r.stdout


def load_token():
    cp = configparser.ConfigParser()
    cp.read(RCLONE_CONF)
    g = cp[REMOTE]
    tok = json.loads(g["token"])
    if not g.get("client_id", "").strip():
        _rclone(["lsf", f"{REMOTE}:", "--max-depth", "1"])
        cp.read(RCLONE_CONF)
        return json.loads(cp[REMOTE]["token"])["access_token"]
    exp = tok.get("expiry", "")
    try:
        from datetime import datetime

        e = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        fresh = (e - datetime.now(e.tzinfo)).total_seconds() > 60
    except Exception:
        fresh = False
    if not fresh:
        body = urllib.parse.urlencode(
            {
                "client_id": g["client_id"],
                "client_secret": g["client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode()
        r = urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30)
        tok["access_token"] = json.loads(r.read())["access_token"]
    return tok["access_token"]


class Drive:
    """Minimal Drive v3 JSON client with the same retry policy as bench-gdrive."""

    def __init__(self):
        self.h = {"Authorization": f"Bearer {load_token()}"}

    def req_json(self, method, path, meta=None, timeout=60):
        body = json.dumps(meta).encode() if meta is not None else None
        headers = dict(self.h)
        if body is not None:
            headers["Content-Type"] = "application/json"
        url = API + path if path.startswith("/") else path
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        for attempt in range(4):
            try:
                r = urllib.request.urlopen(req, timeout=timeout)
                raw = r.read()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 500, 502, 503) and attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
