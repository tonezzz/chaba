#!/usr/bin/env python3
"""ensure-agent-users.py — provision the devin/ada/chaba WP agent
identities on boards.surf-thailand.com (card
lesson-comments-dev-board).

Why: wp-comment-sync's digest lane routes member comments to kanban
cards; the actioning agent then replies IN-THREAD via board-api
POST /wp-comment. For that reply to carry a real author and skip the
WP hold/moderation queue, each agent needs its own WP user with the
`chaba_agent` role (registered by chaba-boards.php >= 0.11.0:
read + read_private_posts + moderate_comments) and an Application
Password. This script creates/updates the users and mints the app
passwords, then writes ~/.config/secrets/wp-agent-users.env — the file
board-api and wp-comment-sync read (they never hold WP admin creds).

Auth — there is NO WP-CLI/SSH path to the h3 Plesk host (ssot.secrets
gap), so this drives wp-admin over HTTP exactly like
deploy-plugin-zip.sh, then uses the WP REST API with either:

  1. cookie session + X-WP-Nonce (default): logs in with the wp-admin
     credential file (~/.config/secrets/boards-surf-thailand-com-
     wp-admin-credential, "user,password" — lives on tony-omen),
     scrapes the wp_rest nonce off wp-admin/profile.php.
  2. --admin-app-password: Basic auth as an administrator app
     password (WP_ADMIN_USER/WP_ADMIN_APP_PASSWORD env) — the cleaner
     path once one is minted; skips the cookie dance entirely.

Deploy order: chaba-boards 0.11.0 must be live FIRST (the chaba_agent
role must exist or user creation fails with rest_user_invalid_role).

Usage:
  python3 scripts/wp-boards/ensure-agent-users.py                # create/ensure + write env
  python3 scripts/wp-boards/ensure-agent-users.py --check        # verify env identities work
  python3 scripts/wp-boards/ensure-agent-users.py --rotate       # revoke + remint app passwords
  python3 scripts/wp-boards/ensure-agent-users.py --identities devin,ada
  python3 scripts/wp-boards/ensure-agent-users.py --dry-run

Env out (default ~/.config/secrets/wp-agent-users.env, mode 0600):
  WP_SITE_URL, WP_AGENT_<NAME>_USER/_APP_PASSWORD/_USER_ID/_NAME/_ROLE
Copy it to every host that runs board-api or wp-comment-sync
(idc03 today):  scp <out> idc03:~/.config/secrets/wp-agent-users.env
"""
from __future__ import annotations

import argparse
import base64
import getpass
import http.cookiejar
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SITE = os.environ.get(
    "WP_SITE_URL", "https://boards.surf-thailand.com/wp").rstrip("/")
DEFAULT_CRED_FILE = os.path.expanduser(
    "~/.config/secrets/boards-surf-thailand-com-wp-admin-credential")
DEFAULT_OUT = os.path.expanduser("~/.config/secrets/wp-agent-users.env")
IDENTITIES = ("devin", "ada", "chaba")
AGENT_ROLE = "chaba_agent"
APP_PASSWORD_NAME = "chaba-agent"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class WpAdminError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# transport — two auth modes over the same REST surface
# --------------------------------------------------------------------------

class WpAdmin:
    """WP REST client authenticated as an administrator.

    mode 'app':   HTTP Basic with an administrator Application Password.
    mode 'cookie': wp-login.php session + X-WP-Nonce (wp_rest nonce
                  scraped from an admin page).
    """

    def __init__(self, site: str, mode: str, user: str = "",
                 password: str = "", nonce: str = ""):
        self.site = site.rstrip("/")
        self.mode = mode
        self.user = user
        self.password = password
        self.nonce = nonce
        self._cj = http.cookiejar.CookieJar()
        self._op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj))

    # -- auth setup ---------------------------------------------------------

    @classmethod
    def via_app_password(cls, site: str, user: str, password: str):
        return cls(site, "app", user=user, password=password)

    @classmethod
    def via_wp_login(cls, site: str, user: str, password: str):
        """wp-login.php cookie flow (deploy-plugin-zip.sh pattern), then
        scrape the wp_rest nonce off wp-admin/profile.php."""
        self = cls(site, "cookie")
        data = urllib.parse.urlencode({
            "log": user, "pwd": password, "wp-submit": "Log In",
            "redirect_to": f"{site}/wp-admin/",
            "testcookie": "1",
        }).encode()
        req = urllib.request.Request(
            f"{site}/wp-login.php", data=data,
            headers={"User-Agent": UA,
                     "Cookie": "wordpress_test_cookie=WP+Cookie+check"})
        try:
            self._op.open(req, timeout=30)
        except urllib.error.HTTPError:
            pass  # wp-login redirects; the cookie jar is what matters
        logged_in = any("wordpress_logged_in" in c.name
                        for c in self._cj)
        if not logged_in:
            raise WpAdminError(
                "wp-login failed — check the admin credential file")
        html = self._get_raw(f"{site}/wp-admin/profile.php")
        m = re.search(r'wpApiSettings\s*=\s*\{[^}]*?"nonce"\s*:\s*'
                      r'"([a-f0-9]+)"', html, re.S)
        if not m:
            m = re.search(r'"nonce"\s*:\s*"([a-f0-9]{10})"', html)
        if not m:
            raise WpAdminError(
                "no wp_rest nonce on profile.php — is the account an "
                "administrator?")
        self.nonce = m.group(1)
        return self

    # -- transport ------------------------------------------------------------

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": UA,
             "Content-Type": "application/json"}
        if self.mode == "app":
            tok = base64.b64encode(
                f"{self.user}:{self.password}".encode()).decode()
            h["Authorization"] = f"Basic {tok}"
        else:
            h["X-WP-Nonce"] = self.nonce
        if extra:
            h.update(extra)
        return h

    def _open(self, req: urllib.request.Request):
        try:
            return self._op.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            body = e.read()[:400].decode("utf-8", "replace")
            raise WpAdminError(f"HTTP {e.code}: {body}") from e

    def _get_raw(self, url: str) -> str:
        return self._open(urllib.request.Request(
            url, headers=self._headers())).read().decode("utf-8", "replace")

    def api(self, method: str, route: str, data: dict | None = None):
        """REST call. `route` is the rest_route path after /wp/v2/."""
        url = (f"{self.site}/index.php?rest_route="
               f"{urllib.parse.quote('/wp/v2/' + route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(
            url, data=body, method=method, headers=self._headers())
        raw = self._open(req).read()
        return json.loads(raw) if raw else {}


# --------------------------------------------------------------------------
# provisioning steps
# --------------------------------------------------------------------------

def find_user(wp: WpAdmin, login: str) -> dict | None:
    """REST user objects don't expose `username` — the nicename (slug)
    is the reliable handle for logins we control."""
    users = wp.api("GET", f"users&slug={urllib.parse.quote(login)}")
    if isinstance(users, list) and users:
        return users[0]
    users = wp.api("GET", f"users&per_page=100&search={login}")
    if isinstance(users, list):
        for u in users:
            if u.get("slug") == login:
                return u
    return None


def ensure_user(wp: WpAdmin, login: str, display: str,
                dry_run: bool) -> dict:
    """Create the WP user (or converge an existing one) with the
    chaba_agent role. Returns the user object."""
    user = find_user(wp, login)
    if user:
        have = set(user.get("roles") or [])
        if AGENT_ROLE not in have and not dry_run:
            wp.api("PUT", f"users/{user['id']}",
                   {"roles": [AGENT_ROLE]})
            user = wp.api("GET", f"users/{user['id']}")
        return user
    if dry_run:
        return {"id": 0, "slug": login, "name": display,
                "roles": [AGENT_ROLE], "_dry": True}
    payload = {
        "username": login,
        "name": display,
        "email": f"{login}@agents.chaba.invalid",
        "password": secrets.token_urlsafe(24),
        "roles": [AGENT_ROLE],
    }
    try:
        return wp.api("POST", "users", payload)
    except WpAdminError as e:
        if "invalid_role" in str(e) or "rest_user_invalid_role" in str(e):
            raise WpAdminError(
                f"role '{AGENT_ROLE}' missing — deploy chaba-boards "
                f">= 0.11.0 to boards.surf-thailand.com first") from e
        raise


def app_passwords(wp: WpAdmin, user_id: int) -> list:
    r = wp.api("GET", f"users/{user_id}/application-passwords")
    return r if isinstance(r, list) else []


def ensure_app_password(wp: WpAdmin, user_id: int, login: str,
                        rotate: bool, dry_run: bool) -> str | None:
    """Return the plaintext app password — minting a new one when none
    named APP_PASSWORD_NAME exists (or always when rotate). Plaintext
    is only returned at creation; an existing one cannot be read back,
    so --rotate is the remint path."""
    existing = [p for p in app_passwords(wp, user_id)
                if p.get("name") == APP_PASSWORD_NAME]
    if existing and not rotate:
        print(f"  {login}: app password '{APP_PASSWORD_NAME}' already "
              f"exists (uuid {existing[0].get('uuid','?')[:8]}…) — "
              f"reusing; --rotate to remint")
        return None
    if dry_run:
        return "dry-run-password"
    for p in existing:                      # rotate: revoke old first
        wp.api("DELETE",
               f"users/{user_id}/application-passwords/{p['uuid']}")
    r = wp.api("POST", f"users/{user_id}/application-passwords",
               {"name": APP_PASSWORD_NAME})
    pw = r.get("password") if isinstance(r, dict) else None
    if not pw:
        raise WpAdminError(
            f"{login}: app-password create returned no password: {r}")
    return pw


def _read_env_file(path: Path) -> dict:
    env = {}
    try:
        for ln in path.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return env


def write_env(out: Path, site: str, results: dict[str, dict],
              passwords: dict[str, str | None]):
    """Write wp-agent-users.env, preserving credentials of identities
    not touched this run and of app passwords that already existed
    (plaintext is only returned at mint time — never invent one)."""
    env = _read_env_file(out)
    env["WP_SITE_URL"] = site
    for name in sorted(results):
        u = results[name]
        pre = f"WP_AGENT_{name.upper()}_"
        env[pre + "USER"] = u.get("username") or name
        env[pre + "USER_ID"] = str(u.get("id") or "")
        env[pre + "NAME"] = u.get("name") or name
        env[pre + "ROLE"] = AGENT_ROLE
        pw = passwords.get(name)
        if pw:
            env[pre + "APP_PASSWORD"] = pw
        elif pre + "APP_PASSWORD" not in env:
            env[pre + "APP_PASSWORD"] = ""
    header = [
        "# wp-agent-users.env — agent WP identities for board-api",
        "# POST /wp-comment + wp-comment-sync acks (card",
        "# lesson-comments-dev-board). Provisioned by",
        "# scripts/wp-boards/ensure-agent-users.py — do not hand-edit;",
        "# re-run with --rotate to remint app passwords.",
    ]
    body = [f"{k}={v}" for k, v in sorted(env.items()) if v != ""]
    missing = [k for k, v in sorted(env.items()) if v == ""]
    if missing:
        body += [f"# {k}=<unset — run ensure-agent-users.py "
                 f"--rotate to mint>" for k in missing]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text("\n".join(header + body) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(out)


def check_identities(env_path: Path):
    """--check: verify each WP_AGENT_* identity's app password actually
    authenticates and lands on the right user (GET users/me)."""
    env = {}
    for ln in env_path.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    site = env.get("WP_SITE_URL", SITE).rstrip("/")
    ok = True
    for name in IDENTITIES:
        ukey = f"WP_AGENT_{name.upper()}_USER"
        pkey = f"WP_AGENT_{name.upper()}_APP_PASSWORD"
        user, pw = env.get(ukey), env.get(pkey)
        if not user or not pw or pw.startswith("<"):
            print(f"  {name}: MISSING creds in {env_path}")
            ok = False
            continue
        wp = WpAdmin.via_app_password(site, user, pw)
        try:
            me = wp.api("GET", "users/me")
            roles = me.get("roles") or []
            good = AGENT_ROLE in roles
            print(f"  {name}: user={me.get('slug') or me.get('id')} "
                  f"roles={roles} -> {'OK' if good else 'WRONG ROLE'}")
            ok = ok and good
        except WpAdminError as e:
            print(f"  {name}: AUTH FAIL {e}")
            ok = False
    return 0 if ok else 1


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--identities", default=",".join(IDENTITIES),
                    help="comma list (default devin,ada,chaba)")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="wp-agent-users.env output path")
    ap.add_argument("--cred-file", default=DEFAULT_CRED_FILE,
                    help="wp-admin 'user,password' credential file")
    ap.add_argument("--admin-user", default=os.environ.get(
        "WP_ADMIN_USER", ""))
    ap.add_argument("--admin-password",
                    default=os.environ.get("WP_ADMIN_PASSWORD", ""))
    ap.add_argument("--admin-app-password",
                    default=os.environ.get("WP_ADMIN_APP_PASSWORD", ""))
    ap.add_argument("--rotate", action="store_true",
                    help="revoke + remint app passwords")
    ap.add_argument("--check", action="store_true",
                    help="verify env identities (no provisioning)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    if args.check:
        return check_identities(out)

    names = [n.strip().lower()
             for n in args.identities.split(",") if n.strip()]
    bad = [n for n in names if n not in IDENTITIES]
    if bad:
        print(f"FAIL: unknown identities {bad} — "
              f"valid: {sorted(IDENTITIES)}", file=sys.stderr)
        return 2

    # --- admin auth -------------------------------------------------------
    if args.admin_app_password:
        wp = WpAdmin.via_app_password(
            args.site, args.admin_user or "admin",
            args.admin_app_password)
        print(f"auth: administrator app password ({args.admin_user})")
    else:
        user, password = args.admin_user, args.admin_password
        if not (user and password):
            try:
                raw = Path(args.cred_file).expanduser().read_text()
                user, _, password = raw.strip().partition(",")
            except OSError:
                pass
        if not (user and password):
            if not user:
                user = input("wp-admin user: ").strip()
            password = getpass.getpass("wp-admin password: ")
        wp = WpAdmin.via_wp_login(args.site, user.strip(),
                                  password.strip())
        print(f"auth: wp-login cookie session ({user.strip()})")

    # --- provision ----------------------------------------------------------
    results, passwords = {}, {}
    for name in names:
        display = name.capitalize()
        print(f"== {name} (login '{name}', role {AGENT_ROLE})")
        try:
            u = ensure_user(wp, name, display, args.dry_run)
        except WpAdminError as e:
            print(f"  FAIL: {e}", file=sys.stderr)
            return 1
        results[name] = u
        uid = u.get("id") or 0
        print(f"  user id={uid} slug={u.get('slug')} "
              f"roles={u.get('roles')}")
        if uid:
            try:
                pw = ensure_app_password(
                    wp, uid, name, args.rotate, args.dry_run)
                passwords[name] = pw
            except WpAdminError as e:
                print(f"  app-password FAIL: {e}", file=sys.stderr)
                return 1

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    write_env(out, args.site, results, passwords)

    print(f"\nwrote {out} (0600)")
    print("next: scp it to every host running board-api / "
          "wp-comment-sync (idc03), then verify:")
    print(f"  python3 {Path(__file__).name} --check --out {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
