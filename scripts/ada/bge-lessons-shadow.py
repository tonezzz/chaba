#!/usr/bin/env python3
"""Mirror Education lessons into an isolated BGE-M3 shadow collection.

This is deliberately separate from the production Ada banks. It reads
lessons through board-api, writes only to mddb-embed, and is intended to
feed the read-only bge-hybrid-recall shadow path.
"""
import argparse
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser


BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
MDDB = os.environ.get(
    "BGE_HYBRID_MDDB_URL", "http://100.123.163.11:11028/v1").rstrip("/")
COLLECTION = "bge-lessons-shadow"


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def post(url, payload, timeout=60, attempts=3):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    err = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            err = RuntimeError(f"{exc.code} from {url}: {detail}")
        except Exception as exc:
            err = exc
        if attempt + 1 < attempts:
            time.sleep(2 * (attempt + 1))
    raise err


def text_from_html(value):
    parser = TextParser()
    parser.feed(html.unescape(value or ""))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def lessons():
    listing = post(f"{BOARD_API}/lesson", {"op": "list", "from": "devin"})
    return listing.get("lessons") or []


def lesson(slug):
    return post(f"{BOARD_API}/lesson",
                {"op": "get", "slug": slug, "from": "devin"})


def sync(limit=0):
    rows = lessons()
    if limit:
        rows = rows[:limit]
    written = 0
    for row in rows:
        slug = row.get("slug")
        if not slug:
            continue
        full = lesson(slug)
        content = text_from_html(full.get("content"))
        title = text_from_html(full.get("title"))
        if len(content) < 20:
            continue
        meta = {
            key: value if isinstance(value, list) else [str(value)]
            for key, value in dict(full.get("meta") or {}).items()
        }
        meta.update({"shadow_source": ["education-lesson"],
                     "shadow_model": ["bge-m3"]})
        post(f"{MDDB}/add", {
            "collection": COLLECTION,
            "key": f"lesson/{slug}",
            "lang": "en",
            "contentMd": f"{title}\n\n{content}",
            "meta": meta,
        })
        written += 1
    print(json.dumps({"collection": COLLECTION, "lessons": written}))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.sync:
        parser.error("--sync is required")
    return sync(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
