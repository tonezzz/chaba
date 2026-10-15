#!/usr/bin/env python3
"""Sync docs/ssot/ssot.repeat-asks.yml -> WP repeat_ask CPT (boards.surf-thailand.com).

One private post per register topic, slug ra-<topic-id> so upserts are
idempotent. Meta: topic/count/last_repeat/status — the admin list sorts by
last_repeat desc (plugin 0.3.7). Runs on a host with ~/.config/secrets/
wp-boards.env (WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD).

Usage: sync-repeat-asks.py [--dry-run]
"""
import base64, json, os, sys, urllib.parse, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REG = REPO / "docs/ssot/ssot.repeat-asks.yml"
ENV_PATH = Path.home() / ".config/secrets/wp-boards.env"


def load_env(p):
    env = {}
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_register(p):
    import yaml
    return yaml.safe_load(p.read_text()) or {}


class WP:
    def __init__(self):
        env = load_env(ENV_PATH)
        self.base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f'{env["WP_APP_USER"]}:{env["WP_APP_PASSWORD"]}'.encode()).decode()
        self.h = {"Authorization": f"Basic {tok}",
                  "Content-Type": "application/json",
                  "User-Agent": "chaba-repeat-asks/1.0"}

    def api(self, route, data=None, method=None):
        u = (f"{self.base}/index.php?rest_route="
             f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(
            u, data=body, headers=self.h,
            method=method or ("POST" if data else "GET"))
        return json.loads(urllib.request.urlopen(req, timeout=45).read())


def topic_html(t):
    hist = t.get("history") or []
    last = max((h.get("at", "") for h in hist), default="")
    rows = "".join(
        f"<tr><td>{h.get('at','')}</td><td>{h.get('ask','')}</td>"
        f"<td>{', '.join(h.get('cards') or []) or '—'}</td></tr>"
        for h in hist)
    return (
        f"<p><b>{t.get('topic','')}</b></p>"
        f"<p>Count: <b>{t.get('count',0)}</b> &middot; Status: "
        f"{t.get('status','')} &middot; Last repeat: {last}</p>"
        f"<p>{t.get('notes','')}</p>"
        f"<table border='1' cellpadding='4'><tr><th>When</th><th>Ask</th>"
        f"<th>Cards</th></tr>{rows}</table>")


def main():
    dry = "--dry-run" in sys.argv
    reg = load_register(REG)
    topics = reg.get("topics") or []
    if not topics:
        print("no topics in register")
        return
    wp = WP()
    for t in topics:
        tid = t.get("id")
        if not tid:
            continue
        slug = f"ra-{tid}"
        hist = t.get("history") or []
        last = max((h.get("at", "") for h in hist), default="")
        payload = {
            "title": t.get("topic", tid)[:200],
            "slug": slug,
            "status": "private",
            "content": topic_html(t),
            "meta": {
                "topic": t.get("topic", ""),
                "count": str(t.get("count", 0)),
                "last_repeat": last,
                "status": str(t.get("status", "")),
            },
        }
        if dry:
            print(f"[dry] {slug}: count={t.get('count')} last={last}")
            continue
        existing = wp.api(f"/wp/v2/repeat_ask&slug={urllib.parse.quote(slug)}&status=private")
        if existing:
            pid = existing[0]["id"]
            wp.api(f"/wp/v2/repeat_ask/{pid}", payload)
            print(f"updated {slug} (post {pid}) count={t.get('count')}")
        else:
            r = wp.api("/wp/v2/repeat_ask", payload)
            print(f"created {slug} (post {r.get('id')}) count={t.get('count')}")


if __name__ == "__main__":
    main()
