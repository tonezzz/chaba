#!/usr/bin/env python3
"""Normalize ada-cms-pages document meta onto the memory-bank schema
(ssot.apps.ada-memory-schema.yml) so pages are searchable/filterable with
the same conventions as bank documents.

Adds/aligns (never removes existing keys like use_count/last_used):

  bank          "cms"                                   (registry bank name)
  scope         "tony"                                  (cms bank is tony-instance)
  kind          "page"                                  (fixes docs missing kind)
  status        "active"                                (recall filters on this)
  source        api | voice | manual | import | extract (non-enum values move
                                                        to origin_source)
  written_by    inferred: cms-audit.py for instance=cms-audit, else
                cms_publish_page (the standard write path for this collection)
  subject       the page slug — join key matching bank-doc convention
  attribute     content type derived from slug: news | report | assessment |
                proposal | plan | benchmark | summary | demo | incident |
                analysis | audit | page
  valid_from    date of meta.updated (best available) or today
  last_verified date of meta.updated or today
  lang          the doc's real lang (fixes meta/lang mismatches)

`updated` is left untouched when present — it tracks content freshness and
the audit's C2 staleness check depends on it; a meta-only pass must not
bump it. When missing it is populated from the doc's addedAt epoch (real
creation time — updatedAt is useless here because normalization itself
bumps it, which would make stale pages look fresh).

Content fixes applied with --apply (mechanical, audit-driven):
  - missing H1 -> "# <title>" prepended (audit rule A3)

Usage:
    cms-normalize-meta.py             # dry-run — print planned changes
    cms-normalize-meta.py --apply     # write to MDDB
    cms-normalize-meta.py --key flood-report --apply

Env:
    MDDB_BASE_URL   default http://100.74.146.0:11023/v1
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
SOURCE_ENUM = {"voice", "manual", "import", "extract", "api"}

# Suffix rules first — e.g. news-source-assessment is an assessment ABOUT
# news, not a news digest; the ^news- prefix rule runs last.
_TYPE_RULES = [
    (r"-report$|reports$|results$", "report"),
    (r"-assessment$", "assessment"),
    (r"-proposal$", "proposal"),
    (r"-plan$", "plan"),
    (r"benchmark|^bench-", "benchmark"),
    (r"-summary$", "summary"),
    (r"-demo$|demo$", "demo"),
    (r"incident", "incident"),
    (r"analysis|audit", "analysis"),
    (r"^news-", "news"),
]


def page_type(slug):
    for pat, t in _TYPE_RULES:
        if re.search(pat, slug):
            return t
    return "page"


def first(meta, name):
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def list_docs():
    req = urllib.request.Request(
        f"{MDDB}/search",
        data=json.dumps({"collection": COLLECTION, "query": "", "limit": 500}).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def normalized_meta(doc, today):
    """Return (new_meta, changes) where changes is [(field, old, new)]."""
    meta = doc.get("meta") or {}
    key, lang = doc["key"], doc.get("lang") or "en"
    slug = first(meta, "slug") or key
    updated = first(meta, "updated")
    added = (datetime.fromtimestamp(doc["addedAt"], timezone.utc).isoformat(timespec="seconds")
             if doc.get("addedAt") else "")
    if not updated and added:
        updated = added
    date_ref = updated[:10] if re.match(r"\d{4}-\d{2}-\d{2}", updated or "") else today
    created = added[:10] or date_ref
    source = first(meta, "source")

    want = {
        "bank": "cms",
        "scope": "tony",
        "kind": "page",
        "status": first(meta, "status") or "active",
        "source": source if source in SOURCE_ENUM else "api",
        "written_by": first(meta, "written_by") or
            ("cms-audit.py" if first(meta, "instance") == "cms-audit" else "cms_publish_page"),
        "subject": slug,
        "attribute": page_type(slug),
        "valid_from": first(meta, "valid_from") or created,
        "last_verified": first(meta, "last_verified") or date_ref,
        "lang": lang,
        "format": first(meta, "format") or "markdown",
    }
    if updated:
        want["updated"] = updated
    if not slug or not first(meta, "slug"):
        want["slug"] = key
    if not first(meta, "title"):
        h1 = re.search(r"^#\s+(.+)$", doc.get("contentMd") or "", re.M)
        want["title"] = h1.group(1).strip() if h1 else key
    if source and source not in SOURCE_ENUM:
        want["origin_source"] = source

    # Canonical field order first, then any pre-existing extras (use_count,
    # last_used, worthy, instance, ...) in their original order.
    merged = {}
    for k, v in want.items():
        merged[k] = [str(v)]
    for k, v in meta.items():
        if k not in merged:
            merged[k] = v if isinstance(v, list) else [str(v)]

    changes = []
    for k, v in merged.items():
        old = meta.get(k)
        old_s = old[0] if isinstance(old, list) and old else ("" if old is None else str(old))
        if old_s != v[0]:
            changes.append((k, old_s or "∅", v[0]))
    return merged, changes


def publish(doc, meta):
    payload = {"collection": COLLECTION, "key": doc["key"],
               "lang": doc.get("lang") or "en",
               "contentMd": doc.get("contentMd") or "", "meta": meta}
    req = urllib.request.Request(
        f"{MDDB}/add", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=120)


def main():
    ap = argparse.ArgumentParser(description="Normalize ada-cms-pages meta to the memory schema")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--key", help="only this page key")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date().isoformat()
    docs = list_docs()
    if args.key:
        docs = [d for d in docs if d.get("key") == args.key]
    changed = skipped = 0
    for d in sorted(docs, key=lambda x: x["id"]):
        new_meta, changes = normalized_meta(d, today)
        # A3 fix: prepend an H1 when the body lacks one.
        h1_missing = not re.search(r"^#\s+", d.get("contentMd") or "", re.M)
        if h1_missing:
            title = first(d.get("meta"), "title") or first(new_meta, "title") or d["key"]
            changes.append(("content", "∅", f"+ '# {title}' (H1)"))
        if not changes:
            skipped += 1
            continue
        changed += 1
        print(f"{d['id']}")
        for f, old, new in changes:
            print(f"    {f:15} {old}  ->  {new}")
        if args.apply:
            if h1_missing:
                title = first(new_meta, "title") or d["key"]
                d["contentMd"] = f"# {title}\n\n" + (d.get("contentMd") or "").lstrip()
            publish(d, new_meta)
    verb = "applied" if args.apply else "planned"
    print(f"\n{changed} docs to update ({verb}), {skipped} already conformant"
          + ("" if args.apply else " — re-run with --apply"))


if __name__ == "__main__":
    sys.exit(main())
