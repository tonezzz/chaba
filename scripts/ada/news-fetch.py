#!/usr/bin/env python3
"""News ingestion — pull RSS/Atom feeds into the WordPress `news` CPT.

WordPress is the store; this script is the timer-driven importer. Dedup is
by deterministic slug `n-<md5(link)>` looked up via `?slug=` on the REST
endpoint — no local ledger, safe to run hourly without creating duplicates.

Each run:
  1. Load feeds from news-feeds.json (next to this script, or --config).
  2. Fetch each feed (stdlib only: urllib + ElementTree, RSS + Atom).
  3. For every item newer than --since-hours and matching the optional
     `require` regex, check WP for the slug; insert missing items as
     published `news` posts with provenance meta + category/tag mapping.

Usage:
    news-fetch.py --dry-run            # fetch + show, no writes
    news-fetch.py                      # import all configured feeds
    news-fetch.py --feed thaipbs-world # one feed only
    news-fetch.py --since-hours 48 --max-items 10

Env:
    WP_BOARDS_ENV   path to wp-boards.env (WP_SITE_URL / WP_APP_USER /
                    WP_APP_PASSWORD) — parsed, never sourced (the app
                    password contains spaces).
"""
import argparse
import base64
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ENV_PATH = os.environ.get(
    "WP_BOARDS_ENV",
    os.path.expanduser("~/.config/secrets/wp-boards.env"))
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "news-feeds.json")
ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


def load_wp_env(path):
    env = {}
    for line in open(path):
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    for k in ("WP_SITE_URL", "WP_APP_USER", "WP_APP_PASSWORD"):
        if k not in env:
            sys.exit(f"missing {k} in {path}")
    return env


class WP:
    def __init__(self, site, user, password):
        self.base = site.rstrip("/")
        tok = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.h = {"Authorization": f"Basic {tok}",
                  "Content-Type": "application/json",
                  "User-Agent": "chaba-news-fetch/1.0"}
        self._cats = None
        self._tags = None

    def api(self, route, data=None):
        u = f"{self.base}/index.php?rest_route={urllib.parse.quote(route, safe='/&=')}"
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(u, data=body, headers=self.h,
                                     method="POST" if data else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=45).read())

    def cat_ids(self, slugs):
        if self._cats is None:
            self._cats = {c["slug"]: c["id"]
                          for c in self.api("/wp/v2/categories&per_page=100")}
        return [self._cats[s] for s in slugs if s in self._cats]

    def tag_ids(self, names):
        if self._tags is None:
            self._tags = {t["name"].lower(): t["id"]
                          for t in self.api("/wp/v2/tags&per_page=100")}
        ids = []
        for n in names:
            key = n.lower()
            if key not in self._tags:
                try:
                    t = self.api("/wp/v2/tags", {"name": n})
                    self._tags[key] = t["id"]
                except Exception as e:
                    print(f"  warn: tag {n!r} create failed: {e}", file=sys.stderr)
                    continue
            ids.append(self._tags[key])
        return ids

    def slug_lookup(self, slug):
        r = self.api(f"/wp/v2/news&slug={slug}&per_page=1")
        return r[0]["id"] if isinstance(r, list) and r else None


CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
MEDIA_NS = "{http://search.yahoo.com/mrss/}content"
BLOCK_RE = re.compile(
    r"<(script|style|iframe|form|object|embed|noscript)[^>]*>.*?</\1>",
    re.I | re.S)
ONATTR_RE = re.compile(r'\s+on\w+="[^"]*"|\s+on\w+=\'[^\']*\'', re.I)


def scrub_html(s):
    """Publisher-supplied HTML: drop active markup, keep structure."""
    s = BLOCK_RE.sub("", s or "")
    return ONATTR_RE.sub("", s).strip()


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def fetch_items(url, timeout=25):
    """Return [{title, link, pub, desc, source}] for RSS or Atom feeds."""
    req = urllib.request.Request(url, headers={"User-Agent": "chaba-news-fetch/1.0"})
    try:
        root = ET.fromstring(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception as e:
        print(f"  warn: feed fetch/parse failed: {e}", file=sys.stderr)
        return []
    items = []
    for it in root.iter("item"):  # RSS
        pub = None
        raw = (it.findtext("pubDate") or it.findtext("dc:date") or "").strip()
        if raw:
            try:
                pub = email.utils.parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                pass
        src = it.find("source")
        ce = it.find(CONTENT_NS)
        media = it.find(MEDIA_NS)
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "pub": pub,
            "desc": strip_html(it.findtext("description")),
            "body": scrub_html(ce.text) if ce is not None else "",
            "image": media.get("url", "") if media is not None else "",
            "source": (src.text or "").strip() if src is not None else "",
        })
    ns = {"a": ATOM[1:-1]}
    for it in root.iter(f"{ATOM}entry"):  # Atom
        link = ""
        for l in it.findall(f"{ATOM}link"):
            if l.get("rel", "alternate") == "alternate" and l.get("href"):
                link = l["href"]
                break
        raw = (it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated") or "").strip()
        pub = None
        if raw:
            try:
                pub = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        items.append({
            "title": (it.findtext(f"{ATOM}title") or "").strip(),
            "link": link,
            "pub": pub,
            "desc": strip_html(it.findtext(f"{ATOM}summary")
                               or it.findtext(f"{ATOM}content")),
            "body": scrub_html(it.findtext(f"{ATOM}content")),
            "image": "",
            "source": "",
        })
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--feed", help="only this feed name")
    ap.add_argument("--since-hours", type=float, default=48)
    ap.add_argument("--max-items", type=int, default=15)
    ap.add_argument("--update", action="store_true",
                    help="PATCH existing posts when the feed now carries "
                         "richer content (content:encoded/image)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = json.load(open(args.config))
    feeds = [f for f in cfg["feeds"] if not args.feed or f["name"] == args.feed]
    if not feeds:
        sys.exit(f"no feed matched --feed {args.feed!r}")

    if args.dry_run:
        wp = None
    else:
        env = load_wp_env(ENV_PATH)
        wp = WP(env["WP_SITE_URL"], env["WP_APP_USER"], env["WP_APP_PASSWORD"])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    total_new = total_dup = total_upd = 0

    for f in feeds:
        name = f["name"]
        rx = re.compile(f["require"], re.I) if f.get("require") else None
        cap = f.get("max_items", args.max_items)
        items = fetch_items(f["url"])
        kept, new, dup, upd = 0, 0, 0, 0
        for it in items:
            if kept >= cap:
                break
            if not it["link"] or not it["title"]:
                continue
            if it["pub"] and it["pub"].astimezone(timezone.utc) < cutoff:
                continue
            if rx and not rx.search(f"{it['title']} {it['desc']}"):
                continue
            kept += 1
            slug = "n-" + hashlib.md5(it["link"].encode()).hexdigest()
            if args.dry_run:
                body_len = len(it["body"]) if it["body"] else len(it["desc"])
                print(f"  [{name}] {it['title'][:80]} -> {slug[:14]}… body={body_len}ch")
                continue
            src = it["source"] or name
            pub_s = it["pub"].isoformat(timespec="seconds") if it["pub"] else ""
            body = it["body"][:20000] if it["body"] else f"<p>{html.escape(it['desc'][:1500])}</p>"
            img = (f"<p><img src=\"{html.escape(it['image'])}\" alt=\"\" "
                   f"loading=\"lazy\"></p>\n") if it["image"] else ""
            content = (
                img + body + "\n"
                f"<p class=\"chaba-news-src\">Source: "
                f"<a href=\"{html.escape(it['link'])}\">{html.escape(src)}</a>"
                f" · {html.escape(name)}"
                + (f" · {html.escape(pub_s)}" if pub_s else "") + "</p>")
            existing = wp.slug_lookup(slug)
            if existing and not args.update:
                dup += 1
                continue
            try:
                if existing:
                    wp.api(f"/wp/v2/news/{existing}", {"content": content})
                    upd += 1
                else:
                    wp.api("/wp/v2/news", {
                        "title": it["title"][:200],
                        "slug": slug,
                        "status": "publish",
                        "content": content,
                        "categories": wp.cat_ids(f.get("categories", [])),
                        "tags": wp.tag_ids(f.get("tags", [])),
                        "meta": {"source_feed": name,
                                 "source_url": it["link"],
                                 "published_at": pub_s},
                    })
                    new += 1
            except Exception as e:
                print(f"  warn: write failed for {slug}: {e}", file=sys.stderr)
        print(f"{name}: {new} new, {upd} upd, {dup} dup, {kept} kept of {len(items)}")
        total_new += new
        total_upd += upd
        total_dup += dup
    print(f"total: {total_new} new, {total_upd} upd, {total_dup} dup")


if __name__ == "__main__":
    main()
