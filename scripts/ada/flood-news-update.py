#!/usr/bin/env python3
"""Flood-news automation — pull current flood news from RSS feeds and
update the `flood-report` CMS page (ada-cms-pages) with a timestamped
auto-news block.

Implements the RSS-ingestion recommendation from the news-source-assessment
page (replaces the web_search dependency for this page — feeds need no
API key). Stdlib only: no feedparser/requests required on the host.

Each run:
  1. Fetch the configured Google News RSS feeds (Thai + English queries for
     Bang Phli / Samut Prakan / Bangkok flooding).
  2. Keep items published within --since-hours, dedup by normalized title,
     newest first, cap at --max-items.
  3. Rewrite the managed block between <!-- flood-news:auto --> markers in
     each language variant of the target page (inserted before the first
     "##" heading when markers are absent). Existing dated log sections
     below are preserved.
  4. Skip the MDDB write entirely when the item set is unchanged (the
     fetch-stamp is ignored in the comparison) — safe to run on a timer
     without churning revisions.

Usage:
    flood-news-update.py --dry-run            # show block, no write
    flood-news-update.py                      # update flood-report (all langs)
    flood-news-update.py --page flood-report --lang en
    flood-news-update.py --since-hours 96 --max-items 8

Env:
    MDDB_BASE_URL   default http://100.74.146.0:11023/v1
"""
import argparse
import email.utils
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
BLOCK_BEGIN = "<!-- flood-news:auto -->"
BLOCK_END = "<!-- /flood-news:auto -->"
ICT = timezone(timedelta(hours=7))

FEEDS = [
    ("bangphli", "https://news.google.com/rss/search?q=%E0%B8%99%E0%B9%89%E0%B8%B3%E0%B8%97%E0%B9%88%E0%B8%A7%E0%B8%A1%20%E0%B8%9A%E0%B8%B2%E0%B8%87%E0%B8%9E%E0%B8%A5%E0%B8%B5&hl=th&gl=TH&ceid=TH:th"),
    ("samutprakan", "https://news.google.com/rss/search?q=%E0%B8%99%E0%B9%89%E0%B8%B3%E0%B8%97%E0%B9%88%E0%B8%A7%E0%B8%A1%20%E0%B8%AA%E0%B8%A1%E0%B8%B8%E0%B8%97%E0%B8%A3%E0%B8%9B%E0%B8%A3%E0%B8%B2%E0%B8%81%E0%B8%B2%E0%B8%A3&hl=th&gl=TH&ceid=TH:th"),
    ("bangkok-th", "https://news.google.com/rss/search?q=%E0%B8%99%E0%B9%89%E0%B8%B3%E0%B8%97%E0%B9%88%E0%B8%A7%E0%B8%A1%20%E0%B8%81%E0%B8%A3%E0%B8%B8%E0%B8%87%E0%B9%80%E0%B8%97%E0%B8%9E&hl=th&gl=TH&ceid=TH:th"),
    ("bangkok-en", "https://news.google.com/rss/search?q=flooding%20Bangkok%20OR%20%22Bang%20Phli%22&hl=en-US&gl=TH&ceid=TH:en"),
]


def fetch_feed(name, url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "chaba-flood-news/1.0"})
    try:
        data = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception as e:
        print(f"warn: feed {name} fetch failed: {e}", file=sys.stderr)
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"warn: feed {name} parse failed: {e}", file=sys.stderr)
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub_raw = (it.findtext("pubDate") or "").strip()
        src = it.find("source")
        source = (src.text or "").strip() if src is not None else ""
        try:
            pub = email.utils.parsedate_to_datetime(pub_raw)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pub = None
        if title and link:
            items.append({"title": html.unescape(title), "link": link,
                          "pub": pub, "source": html.unescape(source) or name})
    return items


def dedup_key(title):
    # Google News titles end with " - <publisher>"; drop it for dedup.
    t = re.sub(r"\s+-\s+[^-]+$", "", title)
    return re.sub(r"[^0-9a-z\u0e00-\u0e7f]+", "", t.lower())


def collect(since_hours, max_items):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    seen = {}
    for name, url in FEEDS:
        for item in fetch_feed(name, url):
            if item["pub"] and item["pub"] < cutoff:
                continue
            key = dedup_key(item["title"])
            if not key:
                continue
            prev = seen.get(key)
            if prev is None or ((item["pub"] or datetime.min.replace(tzinfo=timezone.utc))
                                > (prev["pub"] or datetime.min.replace(tzinfo=timezone.utc))):
                seen[key] = item
    items = sorted(seen.values(),
                   key=lambda i: i["pub"] or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
    return items[:max_items]


def render_block(items, now_ict, since_hours):
    stamp = now_ict.strftime("%Y-%m-%d %H:%M")
    lines = [BLOCK_BEGIN,
             f"## ข่าวน้ำท่วมอัตโนมัติ — ดึงเมื่อ {stamp} น. (ICT)",
             ""]
    for i in items:
        pub = i["pub"].astimezone(ICT).strftime("%Y-%m-%d %H:%M") if i["pub"] else "ไม่ทราบเวลา"
        title = i["title"] if len(i["title"]) <= 140 else i["title"][:137].rstrip() + "…"
        lines.append(f"*   **[{title}]({i['link']})** — {i['source']} · เผยแพร่ {pub}")
    lines += ["",
              f"*รวบรวมอัตโนมัติจาก Google News RSS · {len(items)} รายการใน {since_hours} ชม.ล่าสุด · "
              f"สคริปต์ scripts/ada/flood-news-update.py*",
              BLOCK_END]
    return "\n".join(lines)


BLOCK_RE = re.compile(
    re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.S)


def _item_lines(block):
    """Item bullets only — the header fetch-stamp is excluded so an
    unchanged item set is treated as no-change even when run later."""
    return [l for l in block.splitlines() if l.lstrip().startswith("*")]


UPDATED_RE = re.compile(r"^\*\*(อัปเดตล่าสุด|Updated):\*\*.*$", re.M)


def apply_block(body, block, now_ict):
    """Replace the managed block, or insert it before the first ## heading.
    Also refresh the **อัปเดตล่าสุด:** line when present."""
    new = UPDATED_RE.sub(f"**อัปเดตล่าสุด:** {now_ict.strftime('%Y-%m-%d %H:%M')}", body, count=1)
    if BLOCK_RE.search(new):
        return BLOCK_RE.sub(lambda m: block, new, count=1)
    m = re.search(r"^## ", new, re.M)
    if m:
        return new[:m.start()] + block + "\n\n" + new[m.start():]
    return new.rstrip() + "\n\n" + block + "\n"


def get_page(key, lang):
    req = urllib.request.Request(
        f"{MDDB}/search",
        data=json.dumps({"collection": COLLECTION, "query": "", "limit": 500}).encode(),
        headers={"Content-Type": "application/json"})
    docs = json.load(urllib.request.urlopen(req, timeout=60))
    return [d for d in docs if d.get("key") == key and (lang is None or d.get("lang") == lang)]


def publish(doc, body, now):
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta["updated"] = [now.isoformat(timespec="seconds")]
    meta["last_verified"] = [now.date().isoformat()]
    meta["lang"] = [doc.get("lang") or "en"]
    payload = {"collection": COLLECTION, "key": doc["key"],
               "lang": doc.get("lang") or "en", "contentMd": body, "meta": meta}
    req = urllib.request.Request(
        f"{MDDB}/add",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=120)


def main():
    ap = argparse.ArgumentParser(description="Fetch flood news RSS and update the flood-report CMS page")
    ap.add_argument("--page", default="flood-report", help="CMS page slug (default flood-report)")
    ap.add_argument("--lang", default=None, help="only update this lang variant (default: all)")
    ap.add_argument("--since-hours", type=int, default=72)
    ap.add_argument("--max-items", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    now_ict = now.astimezone(ICT)
    items = collect(args.since_hours, args.max_items)
    print(f"{len(items)} flood items within {args.since_hours}h")
    for i in items:
        pub = i["pub"].astimezone(ICT).strftime("%m-%d %H:%M") if i["pub"] else "?"
        print(f"  [{pub}] {i['title'][:90]} ({i['source']})")
    if not items:
        print("nothing new — page left untouched")
        return 0

    block = render_block(items, now_ict, args.since_hours)
    if args.dry_run:
        print("\n" + block)
        return 0

    docs = get_page(args.page, args.lang)
    if not docs:
        print(f"error: no {COLLECTION} docs for key={args.page} lang={args.lang}", file=sys.stderr)
        return 2
    for doc in docs:
        body = doc.get("contentMd") or ""
        existing = BLOCK_RE.search(body)
        if existing and _item_lines(existing.group(0)) == _item_lines(block):
            print(f"skip {doc['id']} — item set unchanged")
            continue
        new_body = apply_block(body, block, now_ict)
        if new_body == body:
            print(f"skip {doc['id']} — block unchanged")
            continue
        publish(doc, new_body, now)
        print(f"updated {doc['id']} ({len(new_body) - len(body):+d}c)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
