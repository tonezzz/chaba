#!/usr/bin/env python3
"""Export the WP report CPT to Reports: wiki pages
(card wiki-member-knowledge-surface-migrate-wp-3a1cf2).

Member-facing reports (usage-ledger class) are living pages —
Reports:<report_type>/<period>, machine-overwritten per period. Reads go
through the board-api door (/report mode=wp-list + wp-get) — the runner
never holds WP creds. Pages go back through /publish -> wiki-reports, so
the door owns the wiki write and a rerun dedupes on the deterministic
idempotency key.

  default (--dry-run): fetch + convert, print the page plan.
  --out FILE:          also write a pages JSONL for review/archive.
  --apply:             POST each page to /publish sinks=["wiki-reports"].
                       Needs Reports: + แม่แบบ:Report on wiki.h3
                       (LocalSettings step) and wiki creds in
                       wiki-h3-gizmo.env on the board-api host; failures
                       queue to the publication outbox, not the caller.
  --only SUBSTR:       restrict to slugs/types containing SUBSTR.
  --limit N:           cap the number of report pages processed.
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
    """[{slug, report_type, period, ...}] for every WP report post."""
    r = post(api, "/report", {"mode": "wp-list", "from": "devin"})
    return r.get("reports") or []


def fetch(api, slug):
    return post(api, "/report",
                {"mode": "wp-get", "slug": slug, "from": "devin"})


def report_page(rec):
    meta = rec.get("meta") or {}
    rtype = str(meta.get("report_type") or rec.get("slug") or "report")
    period = str(meta.get("period") or "")
    return {
        "wiki_title": pub.report_wiki_title(rtype, period),
        "slug": rec.get("slug", ""),
        "report_type": rtype,
        "period": period,
        "meta": {"report_type": rtype, "period": period,
                 "source_key": meta.get("source_key", ""),
                 "status": "current",
                 "updated": (rec.get("modified") or "")[:10]},
        "wikitext": pub.html_to_wikitext(rec.get("content") or ""),
    }


def index_page(pages):
    """Reports:Index — generated rollup grouped by report_type."""
    groups = {}
    for p in sorted(pages, key=lambda p: p["report_type"].lower()):
        line = f"* [[{p['wiki_title']}|{p['wiki_title'][8:]}]]"
        src = p["meta"].get("source_key")
        if src:
            line += f" — source {src}"
        groups.setdefault(p["report_type"], []).append(line)
    parts = ["Machine-generated index of the member-facing reports — "
             "rebuilt by scripts/wiki-report-migrate.py; do not "
             "hand-edit."]
    for rtype in sorted(groups):
        parts.append(f"\n== {rtype} ==\n" + "\n".join(groups[rtype]))
    return {"wiki_title": "Reports:Index", "slug": "",
            "report_type": "index", "period": "",
            "meta": {"report_type": "", "period": "", "status": "index",
                     "source_key": "wiki-report-migrate"},
            "wikitext": "\n".join(parts)}


def apply_page(api, p):
    ev = {"kind": "report", "title": p["wiki_title"][8:],
          "body": p["wikitext"],
          "source": "wiki-migrate", "visibility": "private",
          "from": "devin",
          "sinks": ["wiki-reports"],
          "meta": {"wiki_title": p["wiki_title"], "format": "wikitext",
                   **p["meta"]}}
    r = post(api, "/publish", ev)
    rec = (r.get("receipts") or {}).get("wiki-reports") or {}
    return rec.get("status", "?"), rec.get("reason") or rec.get("ref") or r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="publish pages via /publish (default: dry-run)")
    ap.add_argument("--out", default="",
                    help="write the pages JSONL here")
    ap.add_argument("--only", default="",
                    help="only slugs/types containing this substring")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.2,
                    help="delay between /publish calls in --apply")
    ap.add_argument("--api", default=API)
    a = ap.parse_args()

    items = inventory(a.api)
    if a.only:
        needle = a.only.lower()
        items = [t for t in items
                 if needle in (t.get("slug", "") +
                               t.get("report_type", "")).lower()]
    if a.limit:
        items = items[:a.limit]
    print(f"{len(items)} report posts to export", file=sys.stderr)

    pages, errors = [], []
    for t in items:
        slug = t.get("slug", "")
        try:
            pages.append(report_page(fetch(a.api, slug)))
        except Exception as e:
            errors.append({"slug": slug, "error": str(e)[:200]})
    if pages:
        pages.append(index_page(pages))

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
                             ("period", "source_key") if meta.get(k))
            print(f"{p['wiki_title']:<48} {p['slug']:<20} {flags}")
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
