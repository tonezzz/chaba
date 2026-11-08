#!/usr/bin/env python3
"""Backfill the lesson corpus into MDDB chaba-lessons.

Reads every lesson through board-api /lesson {op:list|get,
source:wiki} (--source wp for the frozen WP CPT), builds the SAME
chaba-lessons doc the capture-time dual-write produces
(board_api.lesson_mddb_doc — imported so shapes can't drift), and
POSTs it to MDDB /v1/add. Idempotent: MDDB upserts by
key=lesson-<md5(topic)>; re-running refreshes modified pages.

Why (card assessments-to-education-split-ssot-keep-113ca4): lessons
were filed to the WP CPT, then the wiki Education: namespace — but
were never indexed anywhere an agent could read them back. The
mddb-cms content plane (chaba-*/kb-* collections) is the retrieval
surface for the assessments-to-Education split; without this mirror
research moved from bloated-but-findable to thin-and-invisible.

Usage:
  lesson-mddb-backfill.py [--source wiki|wp] [--mddb URL] [--api URL]
                          [--only SLUG] [--limit N] [--dry-run]

Defaults match the door: api = tailnet board-api, mddb = the content
plane (mddb-cms, MDDB_BASE_URL).
"""
import argparse
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"

MDDB = "http://100.102.134.91:11027/v1"


def _board_api():
    spec = importlib.util.spec_from_file_location(
        "board_api", Path(__file__).resolve().parent / "board-api.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _post(url: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="wiki", choices=["wiki", "wp"])
    ap.add_argument("--mddb", default=MDDB)
    ap.add_argument("--api", default=API)
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    bapi = _board_api()
    try:
        r = _post(f"{a.api}/lesson", {"op": "list", "source": a.source})
    except urllib.error.HTTPError as e:
        sys.exit(f"list failed: board-api {e.code} "
                 f"{e.read()[:300].decode('utf-8', 'replace')}")
    lessons = r.get("lessons") or []
    if a.only:
        lessons = [l for l in lessons if l.get("slug") == a.only]
        if not lessons:
            sys.exit(f"no such lesson: {a.only}")
    if a.limit:
        lessons = lessons[:a.limit]
    print(f"{len(lessons)} lessons from source={a.source}")

    ok = failed = 0
    for l in lessons:
        slug = l["slug"]
        try:
            row = _post(f"{a.api}/lesson",
                        {"op": "get", "source": a.source, "slug": slug})
        except urllib.error.HTTPError as e:
            print(f"SKIP {slug}: get {e.code}")
            failed += 1
            continue
        meta = row.get("meta") or {}
        body_text = row.get("content") or ""
        if a.source != "wiki":      # wp rows carry HTML -> flatten
            body_text = bapi.pub.html_to_wikitext(body_text)
        doc = bapi.lesson_mddb_doc(
            slug, meta.get("topic") or row.get("title") or slug,
            meta.get("level") or "intro",
            meta.get("source") or meta.get("lesson_source") or "chat",
            body_text, meta,
            wiki_title=row.get("wiki_title", ""),
            store=a.source,
            post_id=row.get("post_id"),
            url=row.get("url", ""))
        if a.dry_run:
            print(f"DRY  {slug} {doc['meta']['topic'][0]!r} "
                  f"{len(doc['contentMd'])}c")
            ok += 1
            continue
        try:
            _post(f"{a.mddb}/add", doc, timeout=60)
            print(f"ADD  {slug} {doc['meta']['topic'][0]!r}")
            ok += 1
        except Exception as e:
            print(f"FAIL {slug}: {e}")
            failed += 1
    print(f"done: {ok} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
