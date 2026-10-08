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

# Nav-section derivation — canonical definition lives in
# docs/ssot/infrastructure/ssot.cms.yml (nav block); keep this map in
# sync. Domains not listed get their own auto-section after PAGE_ORDER.
PAGE_ORDER = ["digests", "reports", "cameras", "flood", "news", "bench",
              "ops", "research", "projects", "personal", "docs", "meta",
              "pages"]
DOMAIN_SECTION = {
    "cctv": "cameras",
    "flood": "flood",
    "news": "news", "media": "news", "weather": "news",
    "finance": "news",
    "bench": "bench", "lab": "bench",
    "ops": "ops", "infra": "ops", "monitoring": "ops",
    "health": "ops", "security": "ops", "dev": "ops", "test": "ops",
    "research": "research", "architecture": "research", "ada": "research",
    "chaba-core": "research", "memory": "research",
    "direction": "research",
    "projects": "projects", "purchase": "projects",
    "personal": "personal", "car-activity": "personal",
    "docs": "docs", "policy": "docs",
    "meta": "meta",
}
SECTION_TITLES = {
    "digests": "Digests", "reports": "Reports", "cameras": "Cameras",
    "flood": "Flood", "news": "News & media", "bench": "Bench",
    "ops": "Ops & infra", "research": "Research & notes",
    "projects": "Projects", "personal": "Personal",
    "docs": "Docs & policy", "meta": "Meta", "pages": "Pages",
}
SECTION_CAP = 30  # per-section row cap; cameras alone is ~60 keys


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
            "kind": (meta.get("kind") or [""])[0],
            "report_role": (meta.get("report_role") or [""])[0],
            "domain": (meta.get("domain") or ["-"])[0],
            "summary": (meta.get("summary") or [""])[0],
            "updated": (meta.get("updated") or ["-"])[0][:16],
            "fresh": (meta.get("fresh_for") or ["-"])[0],
            "stale": stale(meta, now),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def row_section(row: dict) -> str:
    """Nav section for one index row — pure meta, no slug matching."""
    if row["report_role"] == "digest":
        return "digests"
    if row["kind"] == "report":
        return "reports"
    dom = row["domain"]
    if dom in DOMAIN_SECTION:
        return DOMAIN_SECTION[dom]
    if dom == "-":
        return "pages"
    return dom  # auto-section for a domain not yet in the map


def group_rows(rows: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """-> ordered [(section_id, title, rows)] per ssot.cms.yml nav."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(row_section(r), []).append(r)
    out = []
    for sec in PAGE_ORDER:
        if sec in groups:
            out.append((sec, SECTION_TITLES[sec], groups.pop(sec)))
    for sec in sorted(groups):  # auto-sections for unmapped domains
        out.append((sec, sec.replace("-", " ").title(), groups[sec]))
    return out


def render(rows: list[dict], now: datetime.datetime) -> str:
    lines = [f"# Reports index — {now:%Y-%m-%d %H:%M}Z\n",
             "Every live CMS page, grouped by nav section"
             " (meta kind/domain — ssot.cms.yml). Read the linked page",
             "only when the summary isn't enough.\n"]
    for _sec, title, srows in group_rows(rows):
        shown = srows[:SECTION_CAP]
        lines.append(f"\n## {title} ({len(srows)})\n")
        lines += ["| slug | domain | updated | fresh | summary |",
                  "|---|---|---|---|---|"]
        for r in shown:
            flag = " ⚠STALE" if r["stale"] else ""
            summ = (r["summary"] or r["title"])[:80]
            lines.append(f"| {r['slug']} | {r['domain']} | {r['updated']}"
                         f"{flag} | {r['fresh']} | {summ} |")
        if len(srows) > len(shown):
            lines.append(f"\n_…{len(srows) - len(shown)} more in this"
                         " section — see the CMS app._")
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
        "status": ["active"], "page_role": ["index"],
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
