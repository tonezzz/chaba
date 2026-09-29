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
    flood-news-update.py --all                # every page in the feeds config
    flood-news-update.py --page flood-report-nongdon --lang th
    flood-news-update.py --since-hours 96 --max-items 8

Feeds come from flood-news-feeds.json (next to this script): a map of
page slug -> [[name, rss-url], ...]. Override with --config or env
FLOOD_NEWS_FEEDS. --feed name=url can be repeated for ad-hoc runs.

Env:
    MDDB_BASE_URL     default http://100.74.146.0:11023/v1
    FLOOD_NEWS_FEEDS  path to the feeds config
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
REGISTRY = "ada-cms-automation"  # per-page switches/knobs + worker state
BLOCK_BEGIN = "<!-- flood-news:auto -->"
BLOCK_END = "<!-- /flood-news:auto -->"
ICT = timezone(timedelta(hours=7))
FEEDS_CONFIG = os.environ.get(
    "FLOOD_NEWS_FEEDS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "flood-news-feeds.json"))


def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def list_registry():
    """Registry docs keyed by page slug. MDDB down -> {} (seed-only mode)."""
    try:
        docs = _post("search", {"collection": REGISTRY, "query": "", "limit": 500})
    except Exception as e:
        print(f"warn: automation registry unreachable ({e}) — seed config only",
              file=sys.stderr)
        return {}, False
    out = {}
    for d in docs:
        try:
            out[d["key"]] = json.loads(d.get("contentMd") or "{}")
        except (KeyError, json.JSONDecodeError) as e:
            print(f"warn: bad registry doc {d.get('id')}: {e}", file=sys.stderr)
    return out, True


def save_registry_doc(page, cfg):
    body = json.dumps(cfg, ensure_ascii=False, indent=2)
    now = datetime.now(timezone.utc)
    meta = {"kind": ["automation-config"], "bank": ["cms"], "scope": ["tony"],
            "status": ["active"], "source": ["api"],
            "written_by": ["flood-news-update"], "subject": [page],
            "attribute": ["automation"], "slug": [page],
            "title": [f"CMS automation: {page}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": page, "lang": "en",
                  "contentMd": body, "meta": meta}, timeout=120)


def seed_entry(config, page):
    entry = config.get(page)
    if isinstance(entry, dict):
        return dict(entry)
    if isinstance(entry, list):
        return {"feeds": entry}
    return {}


def effective_config(page, seed, reg, overrides):
    """Merged switches/knobs for one page — registry wins over seed.
    Returns (cfg, ok) — ok=False when no feeds resolve."""
    cfg = {"enabled": True, "interval_min": 0, "run_now": False}
    cfg.update(seed)
    if reg:
        cfg.update(reg)
    if overrides is not None:
        cfg["feeds"] = overrides
    feeds = cfg.get("feeds")
    if not feeds or not isinstance(feeds, list):
        return cfg, False
    cfg["feeds"] = [tuple(f) for f in feeds]
    return cfg, True


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
        desc_raw = (it.findtext("description") or "")
        desc = html.unescape(re.sub(r"<[^>]+>", " ", desc_raw))
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
                          "pub": pub, "source": html.unescape(source) or name,
                          "desc": desc})
    return items


def dedup_key(title):
    # Google News titles end with " - <publisher>"; drop it for dedup.
    t = re.sub(r"\s+-\s+[^-]+$", "", title)
    return re.sub(r"[^0-9a-z\u0e00-\u0e7f]+", "", t.lower())


def collect(feeds, since_hours, max_items, require=None):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    req_re = re.compile(require, re.I) if require else None
    seen = {}
    for name, url in feeds:
        for item in fetch_feed(name, url):
            if item["pub"] and item["pub"] < cutoff:
                continue
            if req_re and not req_re.search(item["title"] + " " + item["desc"]):
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


# Matches both **อัปเดตล่าสุด:** ... and **อัปเดตล่าสุด: <text>** styles.
UPDATED_RE = re.compile(r"^\*\*(อัปเดตล่าสุด|Updated)\s*:?.*$", re.M)


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


def load_config():
    try:
        return json.load(open(FEEDS_CONFIG))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: cannot load feeds config {FEEDS_CONFIG}: {e}")


def _gated(cfg, now, force):
    """(skip_reason or None). enabled and interval_min gate auto runs;
    run_now and --force bypass interval_min but never 'enabled'."""
    if not cfg.get("enabled", True):
        return "disabled"
    if force or cfg.get("run_now"):
        return None
    interval = int(cfg.get("interval_min") or 0)
    last = cfg.get("last_run")
    if interval and last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now < last_dt + timedelta(minutes=interval):
                return f"interval (last run {last})"
        except ValueError:
            pass
    return None


def update_page(page, cfg, args, now, now_ict, registry_up, require_default):
    why = _gated(cfg, now, args.force)
    if why:
        print(f"== {page}: skipped ({why})")
        return 0
    since = int(cfg.get("since_hours") or args.since_hours)
    limit = int(cfg.get("max_items") or args.max_items)
    items = collect(cfg["feeds"], since, limit,
                    cfg.get("require") or require_default)
    print(f"== {page}: {len(items)} flood items within {since}h"
          + (" [run_now]" if cfg.get("run_now") else ""))
    for i in items:
        pub = i["pub"].astimezone(ICT).strftime("%m-%d %H:%M") if i["pub"] else "?"
        print(f"  [{pub}] {i['title'][:90]} ({i['source']})")

    def write_state(status, count):
        if args.dry_run or not registry_up:
            return
        st = dict(cfg)
        st.update({"run_now": False, "last_run": now.isoformat(timespec="seconds"),
                   "last_status": status, "last_count": count})
        try:
            save_registry_doc(page, st)
        except Exception as e:
            print(f"  warn: registry write-back failed: {e}", file=sys.stderr)

    if not items:
        print("  nothing new — page left untouched")
        write_state("no-items", 0)
        return 0

    block = render_block(items, now_ict, since)
    if args.dry_run:
        print("\n" + block + "\n")
        return 0

    docs = get_page(page, args.lang)
    langs = cfg.get("langs")
    if isinstance(langs, list) and langs:
        docs = [d for d in docs if (d.get("lang") or "en") in langs]
    if not docs:
        print(f"  error: no {COLLECTION} docs for key={page} lang={args.lang}", file=sys.stderr)
        write_state("error: page missing", 0)
        return 2
    for doc in docs:
        body = doc.get("contentMd") or ""
        existing = BLOCK_RE.search(body)
        if existing and _item_lines(existing.group(0)) == _item_lines(block):
            print(f"  skip {doc['id']} — item set unchanged")
            continue
        new_body = apply_block(body, block, now_ict)
        if new_body == body:
            print(f"  skip {doc['id']} — block unchanged")
            continue
        publish(doc, new_body, now)
        print(f"  updated {doc['id']} ({len(new_body) - len(body):+d}c)")
    write_state("ok", len(items))
    return 0


def parse_feed_override(raw):
    name, _, url = raw.partition("=")
    if not name or not url:
        raise SystemExit(f"error: --feed expects name=url, got '{raw}'")
    return name, url


def main():
    ap = argparse.ArgumentParser(description="Fetch flood news RSS and update CMS flood pages")
    ap.add_argument("--page", default="flood-report", help="CMS page slug (default flood-report)")
    ap.add_argument("--all", action="store_true",
                    help="update every page configured in the feeds file")
    ap.add_argument("--lang", default=None, help="only update this lang variant (default: all)")
    ap.add_argument("--since-hours", type=int, default=72)
    ap.add_argument("--max-items", type=int, default=6)
    ap.add_argument("--feed", action="append", default=[],
                    help="ad-hoc feed as name=url (repeatable; overrides config)")
    ap.add_argument("--config", help="feeds JSON path (default: flood-news-feeds.json)")
    ap.add_argument("--force", action="store_true",
                    help="ignore interval_min gating (still honors enabled)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    global FEEDS_CONFIG
    if args.config:
        FEEDS_CONFIG = args.config
    config = load_config()
    overrides = [parse_feed_override(f) for f in args.feed] or None
    registry, registry_up = list_registry()

    now = datetime.now(timezone.utc)
    now_ict = now.astimezone(ICT)
    if args.all:
        pages = sorted({k for k in config if not k.startswith("_")} | set(registry))
    else:
        pages = [args.page]
    rc = 0
    for page in pages:
        cfg, ok = effective_config(
            page, seed_entry(config, page), registry.get(page), overrides)
        if not ok:
            print(f"== {page}: skipped (no feeds configured)")
            continue
        try:
            rc = update_page(page, cfg, args, now, now_ict, registry_up,
                             config.get("_require_default")) or rc
        except SystemExit:
            raise
        except Exception as e:
            print(f"== {page}: error {e}", file=sys.stderr)
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
