#!/usr/bin/env python3
"""Education review queue — lessons with next_review <= today & status != learned.

Maintains ONE living due-list page per destination so the review queue
is always current:

  - wiki  -> Education:Due on wiki.h3 via the /wiki/page door (the
             post-migration surface; card
             wiki-member-knowledge-surface-migrate-wp-3a1cf2)
  - wp    -> private WP page slug education-due (post 354), the
             pre-migration surface — kept during the transition while
             the WP lesson CPT is still the write-canonical store

Reads come through the board-api /lesson door (no WP creds on the
runner). --source wiki is the default post-migration; a door that
predates the wiki read path answers without source=wiki and this
script fails loudly instead of silently auditing the WP corpus.

Usage: lessons-due.py [--dry-run] [--source wiki|wp] [--dest wiki|wp|both]
                      [--api BASE]

Env: LESSON_SOURCE (default wiki) · LESSON_DUE_DEST (default both) ·
     BOARD_API / RUNNER_API door base (default: idc03 tailnet) ·
     BGE_EDU_SHADOW_REPORT (optional read-only BGE shadow report; a
     fresh one appends related-lesson suggestions to both dests)
"""
import argparse, base64, html, json, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "board"))
try:
    import dispatch_repos as dr
    API_BASE = dr.board_api_base()
except Exception:
    API_BASE = (os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
                or "https://idc03.taila0626a.ts.net:10000").rstrip("/")

ENV_PATH = Path.home() / ".config/secrets/wp-boards.env"
DUE_SLUG = "education-due"
DUE_WIKI_TITLE = "Education:Due"
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


def door_post(api_base: str, path: str, body: dict) -> dict:
    body = {"from": "lessons-due", **body}
    req = urllib.request.Request(
        f"{api_base}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


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


def fetch_rows(source: str, api_base: str):
    """-> [{'slug','topic','level','next_review','status','href',
           'wiki_title'}] — normalized across the two stores."""
    if source == "wiki":
        r = door_post(api_base, "/lesson",
                      {"op": "list", "source": "wiki"})
        if r.get("source") != "wiki":
            raise RuntimeError(
                "door answered without source=wiki — the running "
                "board-api predates the wiki read path (merge + "
                "restart on idc03 first)")
        rows = []
        for l in r.get("lessons") or []:
            rows.append({"slug": l.get("slug", ""),
                         "topic": l.get("topic", ""),
                         "level": l.get("level", ""),
                         "next_review": l.get("next_review", ""),
                         "status": l.get("status", ""),
                         "href": l.get("url", ""),
                         "wiki_title": l.get("wiki_title", "")})
        return rows
    wp = WP()
    lessons = wp.api("/wp/v2/lesson&status=any&per_page=100")
    rows = []
    for p in lessons:
        m = p.get("meta", {})
        rows.append({"slug": p.get("slug", ""),
                     "topic": m.get("topic")
                     or p.get("title", {}).get("rendered", ""),
                     "level": m.get("level", ""),
                     "next_review": m.get("next_review", ""),
                     "status": m.get("status", ""),
                     "href": p.get("link", ""),
                     "wiki_title": ""})
    return rows


def bucket_rows(rows: list, today: str):
    """-> (due, upcoming) sorted row lists, learned excluded."""
    due, upcoming = [], []
    for r in rows:
        b = review_bucket({"status": r["status"],
                           "next_review": r["next_review"]}, today)
        if b == "due":
            due.append(r)
        elif b == "upcoming":
            upcoming.append(r)
    due.sort(key=lambda r: r["next_review"])
    upcoming.sort(key=lambda r: r["next_review"])
    return due, upcoming


def _wiki_link(r: dict) -> str:
    """[[Education:X|topic]] internal link; falls back to plain text."""
    if r.get("wiki_title"):
        return f"[[{r['wiki_title']}|{r['topic']}]]"
    return r["topic"]


def load_bge_related(due: list) -> dict:
    """-> {due_slug: [related_slug, ...]} from a fresh read-only BGE
    shadow report. {} on missing, stale (>48h), or malformed reports."""
    try:
        report = json.loads(Path(BGE_SHADOW_REPORT).read_text())
        run = datetime.fromisoformat(
            str(report["run"]).replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - run).total_seconds() > 48 * 3600:
            return {}
        due_slugs = {r["slug"] for r in due}
        related = {}
        for row in report.get("results") or []:
            slug = row.get("slug")
            if slug not in due_slugs:
                continue
            names = []
            for hit in (row.get("result") or {}).get("results") or []:
                key = str(hit.get("key") or "")
                if key.startswith("lesson/") and key != f"lesson/{slug}":
                    names.append(key.removeprefix("lesson/"))
            if names:
                related[slug] = names[:3]
        return related
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def _related_row(rows_by_slug: dict, slug: str) -> dict:
    return rows_by_slug.get(slug) or {"topic": slug, "wiki_title": ""}


def due_wikitext(due: list, upcoming: list, today: str,
                 related: dict = None, rows_by_slug: dict = None) -> str:
    rows_by_slug = rows_by_slug or {}
    lines = [f"== Due now ({len(due)}) ==", ""]
    if due:
        lines += [f"* {_wiki_link(r)} — due {r['next_review']} "
                  f"({r['level']})" for r in due]
    else:
        lines.append("* Nothing due — all caught up.")
    lines += ["", "== Upcoming ==", ""]
    lines += [f"* {_wiki_link(r)} — {r['next_review']}"
              for r in upcoming[:10]]
    if related:
        lines += ["", "== Related lesson suggestions (BGE shadow) ==", ""]
        for r in due:
            names = related.get(r["slug"])
            if names:
                links = ", ".join(
                    _wiki_link(_related_row(rows_by_slug, s))
                    for s in names)
                lines.append(f"* {_wiki_link(r)} — related: {links}")
    lines += ["",
              f"Updated {today} — mark a lesson status=learned or push "
              "next_review to clear it.",
              "", "[[Category:Education]]", ""]
    return "\n".join(lines)


def due_html(due: list, upcoming: list, today: str,
             related: dict = None, rows_by_slug: dict = None) -> str:
    rows_by_slug = rows_by_slug or {}
    lis = "".join(
        f'<li><a href="{r["href"]}">{r["topic"]}</a> — due '
        f'{r["next_review"]} ({r["level"]})</li>' for r in due)
    if not lis:
        lis = "<li>Nothing due — all caught up.</li>"
    up = "".join(f'<li>{r["topic"]} — {r["next_review"]}</li>'
                 for r in upcoming[:10])
    items = []
    for r in due:
        names = (related or {}).get(r["slug"])
        if names:
            topics = ", ".join(
                html.escape(_related_row(rows_by_slug, s)["topic"])
                for s in names)
            items.append(f"<li>{html.escape(r['topic'])}: {topics}</li>")
    related_html = (
        "<h3>Related lesson suggestions (BGE shadow)</h3><ul>"
        + "".join(items) + "</ul>" if items else "")
    return (f"<h3>Due now ({len(due)})</h3><ul>{lis}</ul>"
            f"<h3>Upcoming</h3><ul>{up}</ul>{related_html}"
            f"<p><small>Updated {today} — mark a lesson status=learned "
            f"or push next_review to clear it.</small></p>")


def write_wiki(api_base: str, wikitext: str) -> str:
    r = door_post(api_base, "/wiki/page",
                  {"title": DUE_WIKI_TITLE, "wikitext": wikitext,
                   "summary": "education due-review refresh"})
    return (f"{r.get('action', '?')} {r.get('wiki_title', DUE_WIKI_TITLE)}"
            f" rev={r.get('revid')}")


def write_wp(wp: WP, html: str) -> str:
    existing = wp.api(f"/wp/v2/pages&slug={DUE_SLUG}&status=private")
    payload = {"title": "Education — Due for review", "slug": DUE_SLUG,
               "status": "private", "content": html}
    if existing:
        wp.api(f"/wp/v2/pages/{existing[0]['id']}", payload)
        return f"updated page {existing[0]['id']}"
    r = wp.api("/wp/v2/pages", payload)
    return f"created page {r.get('id')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", choices=["wiki", "wp"],
                    default=os.environ.get("LESSON_SOURCE", "wiki"))
    ap.add_argument("--dest", choices=["wiki", "wp", "both"],
                    default=os.environ.get("LESSON_DUE_DEST", "both"))
    ap.add_argument("--api", default=API_BASE)
    a = ap.parse_args()

    today = date.today().isoformat()
    rows = fetch_rows(a.source, a.api)
    due, upcoming = bucket_rows(rows, today)
    related = load_bge_related(due)
    rows_by_slug = {r["slug"]: r for r in rows}

    print(f"source={a.source} due={len(due)} upcoming={len(upcoming)}")
    for r in due:
        print(f"  {r['next_review']}  {r['topic'][:70]}")
    if related:
        print(f"bge_related={len(related)}")
    if a.dry_run:
        print("\n--- Education:Due wikitext ---")
        print(due_wikitext(due, upcoming, today, related, rows_by_slug))
        return 0

    fails = 0
    if a.dest in ("wiki", "both"):
        try:
            print(f"wiki: {write_wiki(a.api, due_wikitext(
                due, upcoming, today, related, rows_by_slug))}")
        except Exception as e:
            fails += 1
            print(f"wiki dest failed: {e}", file=sys.stderr)
    if a.dest in ("wp", "both"):
        try:
            print(f"wp: {write_wp(WP(), due_html(
                due, upcoming, today, related, rows_by_slug))}")
        except Exception as e:
            fails += 1
            print(f"wp dest failed: {e}", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
