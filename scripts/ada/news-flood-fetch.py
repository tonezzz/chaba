#!/usr/bin/env python3
"""news-flood-fetch.py — automated flood-news page for the Ada CMS news-* group.

Fetches Thailand flood coverage from Google News RSS (no API key):
  en  https://news.google.com/rss/search?q=thailand+flood&hl=en&gl=TH&ceid=TH:en
  th  https://news.google.com/rss/search?q=น้ำท่วม&hl=th&gl=TH&ceid=TH:th

Renders news-flood in the required news-* structure (H1, TL;DR, 3-5 items
with headline/summary/why-it-matters/source, ICT footer) and publishes to
ada-cms-pages. Writes are content_md5-gated — an unchanged digest produces
no revision. Adds the page to the news-system index if missing.

Designed for a systemd timer on idc01 (hourly is plenty for news).

  news-flood-fetch.py            # fetch + publish
  news-flood-fetch.py --dry-run  # render, print, don't write
"""

import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

MDDB = "http://100.74.146.0:11023/v1"
COLLECTION = "ada-cms-pages"
SLUG = "news-flood"
ICT = timezone(timedelta(hours=7))

FEEDS = {
    "en": "https://news.google.com/rss/search?q=thailand+flood&hl=en&gl=TH&ceid=TH:en",
    "th": "https://news.google.com/rss/search?q=%E0%B8%99%E0%B9%89%E0%B8%B3%E0%B8%97%E0%B9%88%E0%B8%A7%E0%B8%A1&hl=th&gl=TH&ceid=TH:th",
}

MAX_ITEMS = 5

WHY = {
    "en": "Flood event — check whether affected provinces overlap your area.",
    "th": "เหตุน้ำท่วม — เช็คว่าจังหวัดที่ได้รับผลกระทบตรงกับพื้นที่ของคุณไหม",
}
TLDR_EMPTY = {
    "en": "No major flood reports in the feed right now.",
    "th": "ตอนนี้ไม่มีข่าวน้ำท่วมสำคัญในฟีด",
}
TITLE = {"en": "Flood News", "th": "ข่าวน้ำท่วม"}


def fetch_feed(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "news-flood-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        source_el = it.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        if title and link:
            items.append({"title": title, "link": link,
                          "pub": pub, "source": source})
    return items


def render(lang: str, items: list[dict]) -> str:
    now = datetime.now(ICT).strftime("%H:%M")
    title = TITLE[lang]
    if not items:
        tldr = TLDR_EMPTY[lang]
    else:
        first = items[0]["title"]
        tldr = first if len(first) <= 110 else first[:107] + "..."
        tldr = f"TL;DR: {tldr}"
    out = [f"# {title}", "", tldr, "", "## Top Stories", ""]
    for it in items[:MAX_ITEMS]:
        head = it["title"]
        if len(head) > 90:
            head = head[:87].rstrip() + "..."
        out.append(
            f"- **{head}** — {it['source']}. "
            f"Why it matters: {WHY[lang]} "
            f"[Source]({it['link']})")
    out += ["", f"*Updated {now} ICT*", ""]
    return "\n".join(out)


def post(path: str, body: dict):
    req = urllib.request.Request(f"{MDDB}{path}",
        data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_doc(key: str, lang: str):
    try:
        return post("/get", {"collection": COLLECTION, "key": key, "lang": lang})
    except Exception:
        return None


def publish(lang: str, content: str, items: list[dict], dry: bool) -> str:
    # hash the story SET (sorted links) — Google News reshuffles item order
    # hourly, which would otherwise churn a revision per run with no new news
    md5 = hashlib.md5(
        "\n".join(sorted(i["link"] for i in items[:MAX_ITEMS])).encode()
    ).hexdigest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"format": ["markdown"], "instance": ["tony"], "kind": ["page"],
            "slug": [SLUG], "lang": [lang], "title": [TITLE[lang]],
            "updated": [now], "content_md5": [md5]}
    doc = get_doc(SLUG, lang)
    if doc and md5 == ((doc.get("meta") or {}).get("content_md5") or [""])[0]:
        return f"{lang}: unchanged"
    if not dry:
        post("/add", {"collection": COLLECTION, "key": SLUG, "lang": lang,
                      "contentMd": content, "meta": meta})
    return f"{lang}: {'would update' if dry else 'updated'}"


def ensure_index(dry: bool):
    """Add news-flood to the news-system index links if missing."""
    doc = get_doc("news-system", "en")
    body = (doc or {}).get("contentMd") or ""
    if not body or f"(#/{SLUG})" in body:
        return
    link = f"- [News Flood](#/{SLUG}) — automated Thai flood feed"
    # insert into the Pages list, before the structure section
    idx = body.find("## Required structure")
    if idx < 0:
        new = body.rstrip() + "\n" + link + "\n"
    else:
        new = body[:idx].rstrip() + "\n" + link + "\n\n" + body[idx:]
    if dry:
        print("index: would add news-flood link")
        return
    meta = dict(doc.get("meta") or {})
    meta["updated"] = [datetime.now(timezone.utc).isoformat(timespec="seconds")]
    post("/add", {"collection": COLLECTION, "key": "news-system", "lang": "en",
                  "contentMd": new, "meta": meta})
    print("index: added news-flood link")


def main() -> int:
    dry = "--dry-run" in sys.argv
    for lang, url in FEEDS.items():
        try:
            items = fetch_feed(url)
        except Exception as e:
            print(f"{lang}: feed fetch failed — {e}", file=sys.stderr)
            continue
        content = render(lang, items)
        if dry:
            print(f"--- {lang} ({len(items)} items) ---")
            print(content)
        print(publish(lang, content, items, dry))
    ensure_index(dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
