#!/usr/bin/env python3
"""site-preflight.py — pre-onboarding checks for a LINE-managed WP site.

Card line-wp-site-manager (OPS-0640), customer-site onboarding
(docs/kb/wp-customer-site-onboarding.md). Run from any tailnet host
BEFORE a site is registered in ssot.wp-boards.yml `sites:` — it proves
the REST surface is up, the app password authenticates, and the vhost's
permalink quirk is known, so onboarding never wires a lane to a dead
endpoint.

Anonymous mode (no creds needed):
    site-preflight.py https://example.com/wp

Auth mode — verifies a minted application password end-to-end:
    site-preflight.py https://example.com/wp --env-file ~/.config/secrets/wp-<slug>.env

Mint env file (0600, never echoes the password):
    site-preflight.py https://example.com/wp --write-env ~/.config/secrets/wp-<slug>.env \
        --user <wp-user>          # password via WP_PREFLIGHT_PASS or getpass

Checks:
  1. front page reachable (follows redirects, flags the 2026-10-14
     infinite-301 failure mode)
  2. REST index — /wp-json/ first, index.php?rest_route= fallback
     (Plesk vhosts without rewrites only serve the ?rest_route= form —
     recorded as sites.<slug>.rest_route_style in ssot.wp-boards.yml)
  3. /wp/v2/users anonymous enumeration — WP-default leak, warn only
  4. /wp/v2/users/me unauthenticated must be 401
  5. --env-file: GET users/me with the app password must be 200 and
     report the authenticated login + roles

Exit 0 = every required check passed (warnings don't fail).
"""

import argparse
import base64
import getpass
import json
import os
import stat
import sys
import urllib.error
import urllib.request

TIMEOUT = 20
failures = []


def say(msg=""):
    print(msg)


def ok(msg):
    say(f"   ok   {msg}")


def warn(msg):
    say(f"   warn {msg}")


def bad(msg):
    say(f"   FAIL {msg}")
    failures.append(msg)


def get(url, auth=None, max_redirects=10):
    """GET url -> (status, body_bytes, final_url). Never raises on HTTP
    errors; raises on network failure. auth = (user, password) adds a
    Basic header — app-password auth is plain HTTP Basic over TLS."""
    req = urllib.request.Request(url, headers={"User-Agent": "chaba-site-preflight/1.0"})
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    visited = set()
    cur = req
    for _ in range(max_redirects + 1):
        try:
            resp = opener.open(cur, timeout=TIMEOUT)
            return resp.status, resp.read(), resp.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                nxt = urllib.request.urljoin(
                    cur.full_url, e.headers.get("Location", ""))
                if nxt in visited:
                    raise RuntimeError(
                        f"redirect loop at {cur.full_url} -> {nxt}")
                visited.add(cur.full_url)
                cur = urllib.request.Request(
                    nxt, headers=dict(cur.header_items()))
                continue
            return e.code, e.read(), cur.full_url
    raise RuntimeError(f"too many redirects from {url}")


def load_env(path):
    """Parse KEY=VALUE env file (never source it) — same contract as the
    scripts/ada/* WP writers (WP_BOARDS_ENV)."""
    env = {}
    with open(os.path.expanduser(path)) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def rest_base(site):
    """Return (rest_prefix, style). Try pretty /wp-json/ first, then the
    Plesk-style index.php?rest_route= form."""
    site = site.rstrip("/")
    for prefix, style in ((f"{site}/wp-json", "pretty"),
                          (f"{site}/index.php?rest_route=", "index.php")):
        try:
            status, body, _ = get(prefix + ("" if style == "pretty" else ""))
        except Exception:
            continue
        if status == 200:
            try:
                idx = json.loads(body)
                return prefix, style, idx
            except json.JSONDecodeError:
                continue
    return None, None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("site", help="WP base URL, e.g. https://example.com/wp")
    ap.add_argument("--env-file", help="wp-<slug>.env to authenticate with")
    ap.add_argument("--write-env", metavar="PATH",
                    help="write a 0600 env file (asks for app password)")
    ap.add_argument("--user", help="WP app-password user (with --write-env)")
    args = ap.parse_args()
    site = args.site.rstrip("/")

    say(f"== 1. front page {site}/")
    try:
        status, _, final = get(site + "/")
        if status == 200:
            ok(f"HTTP 200 (final: {final})")
        else:
            bad(f"front page HTTP {status}")
    except Exception as e:
        bad(f"front page unreachable: {e}")

    say("== 2. REST index")
    prefix, style, idx = rest_base(site)
    if idx is None:
        bad(f"no REST index at {site}/wp-json/ or index.php?rest_route=")
        prefix = f"{site}/index.php?rest_route="
    else:
        routes = len(idx.get("routes", {}))
        ok(f"{idx.get('name', '?')!r} — {routes} routes via "
           f"{'/wp-json/' if style == 'pretty' else 'index.php?rest_route='}")
        if style == "index.php":
            warn("pretty /wp-json/ unavailable — Plesk vhost without "
                 "rewrites; record rest_route_style: index.php and prefer "
                 "/index.php/%postname%/ permalinks (boards site precedent)")

    def wpv2(path):
        # prefix is either <site>/wp-json or <site>/index.php?rest_route=
        # — both take the route path appended directly.
        return get(f"{prefix}{path}")

    say("== 3. anonymous surface")
    try:
        status, body, _ = wpv2("/wp/v2/users?per_page=5")
        if status == 200:
            users = json.loads(body)
            warn(f"/wp/v2/users enumerable anonymously ({len(users)} shown) "
                 "— WP default; slugs only, optional hardening")
        else:
            ok(f"/wp/v2/users -> {status} (enumeration blocked)")
    except Exception as e:
        warn(f"/wp/v2/users probe failed: {e}")

    try:
        status, _, _ = wpv2("/wp/v2/users/me")
        if status in (401, 403):
            ok(f"users/me unauthenticated -> {status}")
        else:
            bad(f"users/me unauthenticated -> {status} (expected 401/403)")
    except Exception as e:
        bad(f"users/me probe failed: {e}")

    auth = None
    if args.env_file:
        say(f"== 4. app-password auth ({args.env_file})")
        try:
            env = load_env(args.env_file)
            for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD"):
                if k not in env:
                    bad(f"env file missing {k}")
            auth = (env["WP_APP_USER"], env["WP_APP_PASSWORD"])
            if env.get("WP_SITE_URL", "").rstrip("/") != site:
                warn(f"env WP_SITE_URL={env.get('WP_SITE_URL')} != {site}")
        except FileNotFoundError:
            bad(f"env file not found: {args.env_file}")
        if auth:
            try:
                status, body, _ = get(f"{prefix}/wp/v2/users/me", auth=auth)
                if status == 200:
                    me = json.loads(body)
                    ok(f"authenticated as {me.get('slug')} "
                       f"(id={me.get('id')}, name={me.get('name')!r})")
                else:
                    bad(f"users/me with app password -> {status} "
                        "(bad creds or app passwords disabled — check "
                        "WP 5.6+ and no plugin is stripping Basic auth)")
            except Exception as e:
                bad(f"authenticated probe failed: {e}")

    if args.write_env:
        say(f"== 5. write env {args.write_env}")
        user = args.user or input("WP_APP_USER: ").strip()
        pw = os.environ.get("WP_PREFLIGHT_PASS") or getpass.getpass(
            "WP_APP_PASSWORD (paste, not echoed): ")
        path = os.path.expanduser(args.write_env)
        content = (f"WP_SITE_URL={site}\nWP_APP_USER={user}\n"
                   f"WP_APP_PASSWORD={pw}\n")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.chmod(path, 0o600)
        st = os.stat(path)
        assert stat.S_IMODE(st.st_mode) == 0o600
        ok(f"wrote {path} mode 0600 — value never printed")

    say()
    if failures:
        say(f"preflight FAILED — {len(failures)} check(s)")
        return 1
    say("preflight OK — site is ready to register in ssot.wp-boards.yml sites:")
    return 0


if __name__ == "__main__":
    sys.exit(main())
