#!/usr/bin/env python3
"""Shared ada-cms-pages/reports-index regeneration.

The canonical regen lives in ada-pi (tool_runner._cms_reports_index) and
fires on Ada's own cms tool writes; raw /v1/add writers never trigger it,
so in-repo generators that publish pages call this instead. One render,
one filter set: superseded / archived / retracted / expired docs are never
surfaced (kind=archive is also dropped by the kind gate), and pages past
their fresh_for TTL carry the ⚠STALE flag.

Used by report-daily-brief.py and cam-wall-cms.py.
"""
from __future__ import annotations

import datetime
import json
import urllib.request

# Lifecycle statuses that must never surface in the index. kind:page
# docs with status=superseded are inside their retention window — still
# real pages, but replaced; the index would otherwise list them as fresh
# content for up to ARCHIVE_DAYS.
EXCLUDED_STATUS = {"superseded", "archived", "retracted", "expired"}
MAX_ROWS = 60


def _post(mddb: str, path: str, payload: dict, timeout: float = 60):
    req = urllib.request.Request(
        f"{mddb.rstrip('/')}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def list_docs(mddb: str, collection: str) -> list[dict]:
    """Paginated collection scan — a fixed limit silently drops docs once
    the collection outgrows it (ada-cms-pages is already >300)."""
    docs, offset = [], 0
    while True:
        page = _post(mddb, "search",
                     {"collection": collection, "query": "",
                      "limit": 500, "offset": offset})
        if isinstance(page, dict):
            page = page.get("documents") or page.get("docs") or []
        docs += page
        if len(page) < 500:
            return docs
        offset += 500


def stale(meta: dict, now: datetime.datetime) -> bool:
    ff = (meta.get("fresh_for") or [""])[0]
    upd = (meta.get("updated") or [""])[0]
    if not ff or not upd:
        return False
    try:
        secs = int(float(ff[:-1]) * {"h": 3600, "d": 86400, "m": 60}[ff[-1]])
        dt = datetime.datetime.fromisoformat(upd.replace("Z", "+00:00"))
        return (now - dt).total_seconds() > secs
    except Exception:
        return False


def index_rows(docs: list[dict], now: datetime.datetime) -> list[dict]:
    rows = []
    for d in docs:
        # index the en variant only — a th mirror row carries no extra
        # signal and doubles the row count (cctv pages flooded past
        # MAX_ROWS and pushed real reports out of the index)
        if d.get("lang") == "th":
            continue
        meta = d.get("meta") or {}
        if (meta.get("kind") or [""])[0] not in ("report", "page"):
            continue
        if (meta.get("status") or [""])[0] in EXCLUDED_STATUS:
            continue
        slug = (meta.get("slug") or [d.get("key") or "?"])[0]
        if slug == "reports-index":
            continue
        rows.append({
            "slug": slug,
            "title": (meta.get("title") or [slug])[0],
            "domain": (meta.get("domain") or ["-"])[0],
            "summary": (meta.get("summary") or [""])[0],
            "updated": (meta.get("updated") or ["-"])[0][:16],
            "fresh": (meta.get("fresh_for") or ["-"])[0],
            "stale": stale(meta, now),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def render(rows: list[dict], now: datetime.datetime) -> str:
    lines = [f"# Reports index — {now:%Y-%m-%d %H:%M}Z\n",
             "Brief summaries of every report page — read the linked page",
             "only when the summary isn't enough.\n",
             "| slug | domain | updated | fresh | summary |",
             "|---|---|---|---|---|"]
    for r in rows[:MAX_ROWS]:
        flag = " ⚠STALE" if r["stale"] else ""
        summ = (r["summary"] or r["title"])[:80]
        lines.append(f"| {r['slug']} | {r['domain']} | {r['updated']}"
                     f"{flag} | {r['fresh']} | {summ} |")
    return "\n".join(lines)


def regen_reports_index(mddb_base: str, written_by: str,
                        collection: str = "ada-cms-pages",
                        instance: str | None = None,
                        now: datetime.datetime | None = None) -> bool:
    """Rewrite ada-cms-pages/reports-index from the current doc set."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    md = render(index_rows(list_docs(mddb_base, collection), now), now)
    meta = {
        "kind": ["page"], "slug": ["reports-index"],
        "title": [f"Reports index — {now:%Y-%m-%d %H:%M}Z"],
        "format": ["markdown"], "domain": ["meta"],
        "summary": ["Auto-generated index of report pages — "
                    "slug, domain, staleness, one-line brief."],
        "fresh_for": ["6h"],
        "updated": [now.isoformat(timespec="seconds")],
        "written_by": [written_by],
    }
    if instance:
        meta["instance"] = [instance]
    _post(mddb_base, "add", {
        "collection": collection, "key": "reports-index", "lang": "en",
        "contentMd": md, "meta": meta})
    return True
