#!/usr/bin/env python3
"""Education review queue — lessons with next_review <= today & status != learned.

Writes ONE living private WP page (slug: education-due) so Tony's review list
is always current in wp-admin / member view. Runs via timer; also prints the
list for CLI use.

Usage: lessons-due.py [--dry-run]
"""
import base64, html, json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ENV_PATH = Path.home() / ".config/secrets/wp-boards.env"
DUE_SLUG = "education-due"
BGE_SHADOW_REPORT = os.environ.get(
    "BGE_EDU_SHADOW_REPORT",
    str(Path.home() / ".cache" / "bge-education-shadow-v2.json"),
)


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


def review_bucket(meta: dict, today: str) -> str:
    """-> 'learned' | 'due' | 'upcoming' for one lesson's meta.
    Extracted so scripts/education-report.py buckets door-fetched rows
    with the identical rule (card
    education-maintenance-consolidated-report). NB: a lesson with no
    next_review lands in 'upcoming' — the audit's R1:no-next-review
    flag is what marks it broken, not this queue."""
    if meta.get("status") == "learned":
        return "learned"
    nr = meta.get("next_review") or ""
    return "due" if (nr and nr <= today) else "upcoming"


def load_bge_related(
    due: list[tuple], titles: dict[str, str]
) -> dict[str, list[str]]:
    """Read a fresh, read-only BGE shadow report for related suggestions."""
    try:
        report = json.loads(Path(BGE_SHADOW_REPORT).read_text())
        run = datetime.fromisoformat(
            str(report["run"]).replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - run).total_seconds() > 48 * 3600:
            return {}
        by_slug = {row[4] for row in due}
        related = {}
        for row in report.get("results") or []:
            slug = row.get("slug")
            if slug not in by_slug:
                continue
            names = []
            for hit in (row.get("result") or {}).get("results") or []:
                key = str(hit.get("key") or "")
                if key.startswith("lesson/") and key != f"lesson/{slug}":
                    related_slug = key.removeprefix("lesson/")
                    names.append(titles.get(related_slug, related_slug))
            if names:
                related[slug] = names[:3]
        return related
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def main():
    dry = "--dry-run" in sys.argv
    wp = WP()
    lessons = wp.api("/wp/v2/lesson&status=any&per_page=100")
    today = date.today().isoformat()
    due, upcoming = [], []
    for p in lessons:
        m = p.get("meta", {})
        bucket = review_bucket(m, today)
        if bucket == "learned":
            continue
        nr = m.get("next_review") or ""
        link = p.get("link", "")
        title = p.get("title", {}).get("rendered", "")
        row = (nr, title, link, m.get("level", ""), p.get("slug", ""))
        (due if bucket == "due" else upcoming).append(row)

    due.sort()
    lis = "".join(
        f'<li><a href="{link}">{t}</a> — due {nr} ({lvl})</li>'
        for nr, t, link, lvl, _ in due)
    if not lis:
        lis = "<li>Nothing due — all caught up.</li>"
    up = "".join(
        f'<li>{t} — {nr}</li>' for nr, t, link, lvl, _ in sorted(upcoming)[:10])
    titles = {
        p.get("slug", ""): p.get("title", {}).get("rendered", "")
        for p in lessons
    }
    related = load_bge_related(due, titles)
    related_items = []
    for _nr, title, _link, _level, slug in due:
        names = related.get(slug)
        if names:
            related_items.append(
                f"<li>{html.escape(title)}: "
                f"{html.escape(', '.join(names))}</li>")
    related_html = (
        "<h3>Related lesson suggestions (BGE shadow)</h3><ul>"
        + "".join(related_items)
        + "</ul>"
        if related_items else "")
    content = (f"<h3>Due now ({len(due)})</h3><ul>{lis}</ul>"
               f"<h3>Upcoming</h3><ul>{up}</ul>{related_html}"
               f"<p><small>Updated {today} — mark a lesson status=learned "
               f"or push next_review to clear it.</small></p>")

    print(f"due={len(due)} upcoming={len(upcoming)}")
    for nr, t, *_ in due:
        print(f"  {nr}  {t[:70]}")
    if related:
        print(f"bge_related={len(related)}")
        for slug, names in sorted(related.items()):
            print(f"  BGE {slug}: {', '.join(names)}")
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
