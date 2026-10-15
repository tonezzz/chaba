#!/usr/bin/env python3
"""Provision a non-admin svc-* HA user + per-lane long-lived access tokens.

Implements card ha-ada-isolation Phase B (docs/kb/ha-ada-isolation.md):
an Ada lane must authenticate to HA as a dedicated non-admin service user,
never a person's owner/admin account.

Requires `websockets` — run with the ada-voice venv python on idc03:

    ~/CascadeProjects/ada-voice/.venv/bin/python ha-svc-user.py provision \
        --ha-url https://tony-dell.taila0626a.ts.net:8123 \
        --admin-env ~/.config/secrets/ada-ha-tony.env \
        --user svc-ada --lanes ada-ha-tony,ada-pi-pwa \
        --out /tmp/svc-ada-tokens.json

    ha-svc-user.py verify --ha-url ... --token-file /tmp/svc-ada-tokens.json --lane ada-ha-tony

Steps:
  1. admin WS (current token in --admin-env) -> config/auth/create user
     {name, username, random password, group_ids=[system-users]} — skipped
     if the username already exists.
  2. OAuth login flow (homeassistant provider) as the new user -> access token.
  3. svc-user WS -> auth/long_lived_access_token once per lane (client_name =
     lane id) so each lane's token is independently revocable.
  4. tokens go to --out (mode 0600), never to stdout.

Token values never appear in logs; only fingerprints (sha256[:10]).
"""
import argparse
import asyncio
import hashlib
import json
import os
import secrets
import ssl
import sys
import urllib.parse
import urllib.request

import websockets

LLAT_LIFESPAN_DAYS = 3650


def _fp(tok):
    return hashlib.sha256(tok.encode()).hexdigest()[:10]


def _load_token_from_env(path):
    for line in open(os.path.expanduser(path)):
        line = line.strip()
        if line.startswith("HOME_ASSISTANT_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"no HOME_ASSISTANT_TOKEN in {path}")


async def _ws(url, token):
    ws_url = url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    ws = await websockets.connect(ws_url, open_timeout=10)
    await ws.recv()  # auth_required
    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    r = json.loads(await ws.recv())
    if r.get("type") != "auth_ok":
        await ws.close()
        raise SystemExit(f"WS auth failed: {r}")
    return ws


class Ws:
    def __init__(self, ws):
        self.ws = ws
        self.i = 0

    async def call(self, **msg):
        self.i += 1
        await self.ws.send(json.dumps({"id": self.i, **msg}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self.i:
                if not r.get("success", True):
                    raise RuntimeError(f"{msg.get('type')} failed: {r.get('error')}")
                return r.get("result")


def _post_json(url, path, payload):
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _post_form(url, path, fields):
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _login_access_token(ha_url, username, password):
    """OAuth login flow -> access token for the svc user."""
    client_id = ha_url.rstrip("/") + "/"
    flow = _post_json(ha_url, "/auth/login_flow", {
        "client_id": client_id,
        "redirect_uri": client_id,
        "handler": ["homeassistant", None],
    })
    step = _post_json(ha_url, f"/auth/login_flow/{flow['flow_id']}", {
        "client_id": client_id,
        "username": username,
        "password": password,
    })
    code = step.get("result")
    if not code:
        raise SystemExit(f"login flow did not return auth code: {step}")
    tok = _post_form(ha_url, "/auth/token", {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
    })
    return tok["access_token"]


async def provision(args):
    admin_tok = _load_token_from_env(args.admin_env)
    admin = Ws(await _ws(args.ha_url, admin_tok))

    me = await admin.call(type="auth/current_user")
    print(f"admin identity: {me.get('name')} (owner={me.get('is_owner')}, admin={me.get('is_admin')})",
          file=sys.stderr)
    if not me.get("is_admin"):
        raise SystemExit("admin-env token is not admin — cannot create users")

    users = await admin.call(type="config/auth/list")
    # Match by username or bare name — a user created without a credential
    # has username=None (e.g. a previous half-finished provision run).
    existing = next((u for u in users
                     if u.get("username") == args.user
                     or (not u.get("system_generated")
                         and u.get("name") == args.user)), None)
    password = secrets.token_urlsafe(24)
    if existing:
        print(f"user {args.user} exists (id={existing['id']})", file=sys.stderr)
        if args.if_exists == "abort":
            raise SystemExit("user exists and --if-exists=abort")
        user_id = existing["id"]
        # Ensure a working password credential so the OAuth step succeeds.
        # This HA version has no list_users command — try create, and if the
        # credential already exists fall back to admin_change_password.
        try:
            await admin.call(type="config/auth_provider/homeassistant/create",
                             user_id=user_id, username=args.user, password=password)
            print("attached homeassistant credential to existing user", file=sys.stderr)
        except RuntimeError:
            try:
                await admin.call(type="config/auth_provider/homeassistant/admin_change_password",
                                 user_id=user_id, password=password)
            except RuntimeError:
                await admin.call(type="config/auth_provider/homeassistant/admin_change_password",
                                 username=args.user, password=password)
            print("re-set credential password for token mint", file=sys.stderr)
    else:
        before_ids = {u["id"] for u in users}
        await admin.call(
            type="config/auth/create",
            name=args.user,
            group_ids=["system-users"],
            local_only=False,
        )
        after = await admin.call(type="config/auth/list")
        new = [u for u in after if u["id"] not in before_ids and u.get("name") == args.user]
        if not new:
            raise SystemExit("config/auth/create succeeded but new user not found in list")
        user_id = new[0]["id"]
        # Older HA: config/auth/create takes no credentials — add the
        # username/password login via the auth provider API.
        await admin.call(type="config/auth_provider/homeassistant/create",
                         user_id=user_id, username=args.user, password=password)
        print(f"created user {args.user} id={user_id} (non-admin) + credential",
              file=sys.stderr)

    # OAuth login as the svc user, then mint one LLAT per lane.
    access = _login_access_token(args.ha_url, args.user, password)
    svc = Ws(await _ws(args.ha_url, access))
    who = await svc.call(type="auth/current_user")
    print(f"svc identity: {who.get('name')} owner={who.get('is_owner')} admin={who.get('is_admin')}",
          file=sys.stderr)
    if who.get("is_owner") or who.get("is_admin"):
        raise SystemExit("refusing: svc user came out privileged")

    tokens = {}
    for lane in args.lanes.split(","):
        lane = lane.strip()
        r = await svc.call(type="auth/long_lived_access_token",
                           client_name=lane, lifespan=LLAT_LIFESPAN_DAYS)
        tokens[lane] = r
        print(f"  minted LLAT client_name={lane} fp={_fp(r)}", file=sys.stderr)

    out = {"user": args.user, "user_id": user_id, "ha_url": args.ha_url,
           "tokens": tokens}
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(args.out, flags, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(out, f, indent=2)
    print(f"wrote {args.out} (0600)", file=sys.stderr)


async def verify(args):
    if args.token_file:
        data = json.load(open(args.token_file))
        token = data["tokens"][args.lane]
    else:
        token = _load_token_from_env(args.env)
    ws = Ws(await _ws(args.ha_url, token))
    u = await ws.call(type="auth/current_user")
    print(json.dumps({"name": u.get("name"), "is_owner": u.get("is_owner"),
                      "is_admin": u.get("is_admin"), "id": u.get("id")}))


async def list_tokens(args):
    token = _load_token_from_env(args.env) if args.env else args.token
    ws = Ws(await _ws(args.ha_url, token))
    me = await ws.call(type="auth/current_user")
    toks = await ws.call(type="auth/refresh_tokens")
    for t in toks:
        print(json.dumps({
            "id": t["id"], "type": t.get("type"), "client_name": t.get("client_name"),
            "client_id": t.get("client_id"), "created_at": t.get("created_at"),
            "is_current": t.get("is_current"),
        }))
    print(f"# as user: {me.get('name')} ({me.get('id')})", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("provision")
    p.add_argument("--ha-url", required=True)
    p.add_argument("--admin-env", required=True,
                   help="env file holding the current admin/owner HOME_ASSISTANT_TOKEN")
    p.add_argument("--user", required=True)
    p.add_argument("--lanes", required=True, help="comma-separated lane ids = LLAT client_names")
    p.add_argument("--out", required=True, help="token output json (written 0600)")
    p.add_argument("--if-exists", choices=["reset-password", "abort"],
                   default="reset-password")

    v = sub.add_parser("verify")
    v.add_argument("--ha-url", required=True)
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument("--env", help="env file containing HOME_ASSISTANT_TOKEN")
    g.add_argument("--token-file", help="provision --out json")
    v.add_argument("--lane", help="lane key inside --token-file")

    l = sub.add_parser("list-tokens")
    l.add_argument("--ha-url", required=True)
    g = l.add_mutually_exclusive_group(required=True)
    g.add_argument("--env")
    g.add_argument("--token")

    args = ap.parse_args()
    fn = {"provision": provision, "verify": verify, "list-tokens": list_tokens}[args.cmd]
    asyncio.run(fn(args))


if __name__ == "__main__":
    main()
