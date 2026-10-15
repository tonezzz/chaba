#!/usr/bin/env python3
"""File a lesson into WP lesson CPT — Tony's education ledger.

One post per topic (slug lesson-<md5>): re-asking the same topic UPDATES the
post instead of forking. Agents (Devin/Ada) call this whenever Tony asks a
knowledge question worth retaining.

Usage:
  lesson-add.py --topic "cloud object storage" --level intro \
      --source chat --content-file /tmp/lesson.html [--next-review 2026-11-15]

Requires ~/.config/secrets/wp-boards.env (WP_SITE_URL/WP_APP_USER/WP_APP_PASSWORD).
"""
import argparse, base64, hashlib, json, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

ENV_PATH = Path.home() / ".config/secrets/wp-boards.env"


def load_env(p):
    env = {}
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class WP:
    def __init__(self):
        env = load_env(ENV_PATH)
        self.base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f'{env["WP_APP_USER"]}:{env["WP_APP_PASSWORD"]}'.encode()).decode()
        self.h = {"Authorization": f"Basic {tok}",
                  "Content-Type": "application/json",
                  "User-Agent": "chaba-lessons/1.0"}

    def api(self, route, data=None):
        u = (f"{self.base}/index.php?rest_route="
             f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(u, data=body, headers=self.h,
                                     method="POST" if data else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=45).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--level", default="intro",
                    choices=["intro", "working", "deep"])
    ap.add_argument("--source", default="chat",
                    choices=["chat", "voice", "link"])
    ap.add_argument("--content-file", required=True)
    ap.add_argument("--next-review", default="")
    ap.add_argument("--status", default="open")
    a = ap.parse_args()

    slug = "lesson-" + hashlib.md5(a.topic.strip().lower().encode()).hexdigest()[:12]
    wp = WP()
    payload = {
        "title": f"Lesson — {a.topic}",
        "slug": slug,
        "status": "private",
        "content": Path(a.content_file).read_text(),
        "meta": {
            "topic": a.topic,
            "level": a.level,
            "source": a.source,
            "learned_at": str(date.today()),
            "next_review": a.next_review,
            "status": a.status,
        },
    }
    existing = wp.api(f"/wp/v2/lesson&slug={slug}&status=private")
    if existing:
        pid = existing[0]["id"]
        wp.api(f"/wp/v2/lesson/{pid}", payload)
        print(f"updated {slug} (post {pid})")
    else:
        r = wp.api("/wp/v2/lesson", payload)
        print(f"created {slug} (post {r.get('id')})")


if __name__ == "__main__":
    main()
