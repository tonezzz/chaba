#!/usr/bin/env python3
"""Education review queue — lessons with next_review <= today & status != learned.

Writes ONE living private WP page (slug: education-due) so Tony's review list
is always current in wp-admin / member view. Runs via timer; also prints the
list for CLI use.

Usage: lessons-due.py [--dry-run]
"""
import base64, json, sys, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

ENV_PATH = Path.home() / ".config/secrets/wp-boards.env"
DUE_SLUG = "education-due"


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
                  "User-Agent": "chaba-lessons-due/1.0"}

    def api(self, route, data=None):
        u = (f"{self.base}/index.php?rest_route="
             f"{urllib.parse.quote(route, safe='/&=')}")
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(u, data=body, headers=self.h,
                                     method="POST" if data else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=45).read())


def main():
    dry = "--dry-run" in sys.argv
    wp = WP()
    lessons = wp.api("/wp/v2/lesson&status=any&per_page=100")
    today = date.today().isoformat()
    due, upcoming = [], []
    for p in lessons:
        m = p.get("meta", {})
        if m.get("status") == "learned":
            continue
        nr = m.get("next_review") or ""
        link = p.get("link", "")
        title = p.get("title", {}).get("rendered", "")
        row = (nr, title, link, m.get("level", ""), p.get("slug", ""))
        (due if nr and nr <= today else upcoming).append(row)

    due.sort()
    lis = "".join(
        f'<li><a href="{link}">{t}</a> — due {nr} ({lvl})</li>'
        for nr, t, link, lvl, _ in due)
    if not lis:
        lis = "<li>Nothing due — all caught up.</li>"
    up = "".join(
        f'<li>{t} — {nr}</li>' for nr, t, link, lvl, _ in sorted(upcoming)[:10])
    content = (f"<h3>Due now ({len(due)})</h3><ul>{lis}</ul>"
               f"<h3>Upcoming</h3><ul>{up}</ul>"
               f"<p><small>Updated {today} — mark a lesson status=learned "
               f"or push next_review to clear it.</small></p>")

    print(f"due={len(due)} upcoming={len(upcoming)}")
    for nr, t, *_ in due:
        print(f"  {nr}  {t[:70]}")
    if dry:
        return
    existing = wp.api(f"/wp/v2/pages&slug={DUE_SLUG}&status=private")
    payload = {"title": "Education — Due for review", "slug": DUE_SLUG,
               "status": "private", "content": content}
    if existing:
        wp.api(f"/wp/v2/pages/{existing[0]['id']}", payload)
        print(f"updated page {existing[0]['id']}")
    else:
        r = wp.api("/wp/v2/pages", payload)
        print(f"created page {r.get('id')}")


if __name__ == "__main__":
    main()
