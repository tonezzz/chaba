#!/usr/bin/env python3
"""Export the WP lesson corpus to Education: wiki pages
(card wiki-member-knowledge-surface-migrate-wp-3a1cf2).

Reads go through the board-api door (/lesson op=topics + op=get) — the
runner never holds WP creds. Pages go back through /publish ->
wiki-education, so the door owns the wiki write and a rerun dedupes on
the deterministic idempotency key.

  default (--dry-run): fetch + convert, print the page plan.
  --out FILE:          also write a pages JSONL for review/archive.
  --apply:             POST each page to /publish sinks=["wiki-education"].
                       Needs Education: + แม่แบบ:Education on wiki.h3
                       (LocalSettings step) and wiki creds in
                       wiki-h3-gizmo.env on the board-api host; failures
                       queue to the publication outbox, not the caller.
  --only SUBSTR:       restrict to slugs/topics containing SUBSTR.
  --limit N:           cap the number of lesson pages processed.

Series convention (plan doc 2026-11-06-wiki-member-knowledge-surface.yml):
an '<stem>-map' lesson becomes the Education:<Hub> page itself — the
curated hub content lands there and a generated '== Series ==' link list
is appended. Extend SERIES when new topic families appear.
"""
import argparse, json, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "board"))

import publication as pub

try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"

# topic-stem -> hub page name. '<stem>-map' lessons carry the hub's
# curated content; other '<stem>-*' topics are series members.
SERIES = {"ada-nest": "Ada-Nest", "trade": "Trade"}

META_KEYS = ("level", "source", "learned_at", "next_review", "status",
             "updated", "no_th")


def post(api, path, body):
    req = urllib.request.Request(
        f"{api}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path} -> {e.code}: "
                           f"{e.read()[:300].decode('utf-8', 'replace')}")


def inventory(api):
    """[{slug, topic}] for every lesson (door pages up to 500)."""
    r = post(api, "/lesson", {"op": "topics", "from": "devin"})
    return r.get("topics") or []


def fetch(api, slug):
    return post(api, "/lesson",
                {"op": "get", "slug": slug, "from": "devin"})


def lesson_page(rec):
    meta = rec.get("meta") or {}
    topic = (meta.get("topic")
             or (rec.get("title") or "")
             .replace("Education — ", "").strip())
    return {
        "wiki_title": pub.lesson_wiki_title(topic),
        "slug": rec.get("slug", ""),
        "topic": topic,
        "meta": {k: meta[k] for k in META_KEYS if meta.get(k) not in
                 (None, "")},
        "wikitext": pub.html_to_wikitext(rec.get("content") or ""),
    }


def series_hubs(pages):
    """Retitle '<stem>-map' pages to their hub name and append a series
    link list; emit a stub hub when a series has members but no map."""
    extra = []
    for stem, hub in SERIES.items():
        hub_title = f"Education:{hub}"
        members = [p for p in pages
                   if p["topic"].lower().startswith(stem + "-")
                   or p["topic"].lower() == stem]
        if len(members) < 2:
            continue
        links = "\n".join(
            f"* [[{p['wiki_title']}|{p['topic']}]]"
            for p in sorted(members, key=lambda p: p["topic"]))
        block = f"\n\n== Series ==\n\n{links}"
        map_page = next((p for p in members
                         if p["topic"].lower() == f"{stem}-map"), None)
        if map_page is not None:
            map_page["wiki_title"] = hub_title
            map_page["wikitext"] += block
        else:
            extra.append({
                "wiki_title": hub_title, "slug": "", "topic": hub,
                "meta": {"status": "index"},
                "wikitext": f"Series hub for '{stem}-*' lessons.{block}"})
    return extra


def index_page(pages):
    """Education:Index — generated rollup grouped by level."""
    groups = {}
    for p in sorted(pages, key=lambda p: p["topic"].lower()):
        line = f"* [[{p['wiki_title']}|{p['topic']}]]"
        nr = (p["meta"].get("next_review") or "")
        if nr:
            line += f" — next review {nr}"
        groups.setdefault(p["meta"].get("level") or "other",
                          []).append(line)
    parts = ["Machine-generated index of the Education ledger — "
             "rebuilt daily by chaba-lessons-due "
             "(scripts/lessons-due.py) and on demand by "
             "scripts/wiki-lesson-migrate.py; do not hand-edit."]
    for lvl in ("intro", "working", "deep", "other"):
        if groups.get(lvl):
            parts.append(f"\n== {lvl.title()} ==\n" + "\n".join(groups[lvl]))
    return {"wiki_title": "Education:Index", "slug": "",
            "topic": "education index",
            "meta": {"status": "index", "level": ""},
            "wikitext": "\n".join(parts)}


def apply_page(api, p):
    ev = {"kind": "lesson", "title": p["topic"], "body": p["wikitext"],
          "source": "wiki-migrate", "visibility": "private",
          "from": "devin",
          "sinks": ["wiki-education"],
          "meta": {"wiki_title": p["wiki_title"], "topic": p["topic"],
                   "format": "wikitext", **p["meta"]}}
    r = post(api, "/publish", ev)
    rec = (r.get("receipts") or {}).get("wiki-education") or {}
    return rec.get("status", "?"), rec.get("reason") or rec.get("ref") or r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="publish pages via /publish (default: dry-run)")
    ap.add_argument("--out", default="",
                    help="write the pages JSONL here")
    ap.add_argument("--only", default="",
                    help="only slugs/topics containing this substring")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.2,
                    help="delay between /publish calls in --apply")
    ap.add_argument("--api", default=API)
    a = ap.parse_args()

    topics = inventory(a.api)
    if a.only:
        needle = a.only.lower()
        topics = [t for t in topics
                  if needle in (t.get("slug", "") + t.get("topic", ""))
                  .lower()]
    if a.limit:
        topics = topics[:a.limit]
    print(f"{len(topics)} lessons to export", file=sys.stderr)

    pages, errors = [], []
    for i, t in enumerate(topics, 1):
        slug = t.get("slug", "")
        try:
            pages.append(lesson_page(fetch(a.api, slug)))
        except Exception as e:
            errors.append({"slug": slug, "error": str(e)[:200]})
        if not i % 25:
            print(f"  fetched {i}/{len(topics)}", file=sys.stderr)
    pages += series_hubs(pages)
    pages.append(index_page([p for p in pages
                             if p["meta"].get("status") != "index"]))

    if a.out:
        Path(a.out).write_text(
            "\n".join(json.dumps(p, ensure_ascii=False) for p in pages)
            + "\n")
        print(f"wrote {a.out}", file=sys.stderr)
    for e in errors:
        print(f"  ERROR {e['slug']}: {e['error']}", file=sys.stderr)

    if not a.apply:
        for p in pages:
            meta = p["meta"]
            flags = ",".join(str(meta.get(k)) for k in
                             ("level", "next_review") if meta.get(k))
            print(f"{p['wiki_title']:<48} {p['slug']:<16} {flags}")
        print(f"\n{len(pages)} pages ({len(errors)} errors) — dry-run; "
              f"--apply publishes via /publish")
        return 1 if errors else 0

    ok = fail = 0
    for p in pages:
        status, detail = apply_page(a.api, p)
        mark = "ok" if status in ("delivered", "skipped") else "FAIL"
        if mark == "ok":
            ok += 1
        else:
            fail += 1
        print(f"{mark:<4} {p['wiki_title']:<48} {status} {detail}")
        time.sleep(a.sleep)
    print(f"\n{ok} delivered/skipped, {fail} failed, "
          f"{len(errors)} export errors")
    return 1 if (fail or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
