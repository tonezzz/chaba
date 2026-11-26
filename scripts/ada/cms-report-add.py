#!/usr/bin/env python3
"""cms-report-add.py — governed writer for a single user-requested CMS report.

A dispatch/operator writes a report into a lane's CMS collection so Ada can
answer from it in a later session. This is the "ask Tony to create a report"
path: it does NOT give the assistant a write tool on her own lane.

Usage:
  python3 scripts/ada/cms-report-add.py --lane kk --slug water-report \
    --title "Water report" --content-file /tmp/report.md \
    --domain home --summary "..." --card kk-cms-only-memory-pilot-acceptance
  # add --apply to write; default is a dry run

Contract:
  - lane -> collection is pinned (no free-form collection argument)
  - slug/domain/summary/title/content are validated before any network call
  - an existing page is never overwritten without --overwrite; the old
    content hash is recorded in meta.timeline
  - meta follows docs/ssot/infrastructure/ssot.cms.yml required_meta
    (kind, domain, status, slug, title, format, updated) + recommended meta
  - /v1/add uses `contentMd` (camelCase) — `content_md` silently stores empty
  - after the write the page is read back and reports-index is regenerated
  - --public is opt-in and requires --source (the static publisher's gate)

Env:
  MDDB_CMS_URL  default http://100.102.134.91:11027/v1 (CMS plane)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SSOT_CMS = REPO / "docs/ssot/infrastructure/ssot.cms.yml"
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import cms_index  # noqa: E402

LANES = {
    "tony": "ada-cms-pages",
    "kk": "ada-cms-pages-kk",
    "kk-dev": "ada-cms-pages-kk-dev",
    "mn": "ada-cms-pages-mn",
}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
DEFAULT_CMS = "http://100.102.134.91:11027/v1"


def canonical_domains() -> set[str]:
    """Domains come from SSOT so a new canonical domain needs no code edit."""
    try:
        import yaml
        data = yaml.safe_load(SSOT_CMS.read_text())
        return set((data.get("meta") or {}).get("domain", {}).get(
            "canonical", {}) or {})
    except Exception:
        return {"cctv", "flood", "news", "media", "weather", "finance",
                "bench", "lab", "ops", "infra", "monitoring", "health",
                "security", "dev", "test", "research", "architecture",
                "ada", "chaba-core", "memory", "docs", "policy",
                "projects", "purchase", "direction", "personal", "home",
                "car-activity", "meta"}


def _post(mddb: str, path: str, payload: dict, timeout: float = 30) -> dict:
    req = urllib.request.Request(
        f"{mddb.rstrip('/')}/{path}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def get_page(mddb: str, collection: str, key: str, lang: str) -> dict | None:
    try:
        return _post(mddb, "get", {"collection": collection, "key": key,
                                   "lang": lang})
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            return None
        raise


def validate(args: argparse.Namespace, content: str) -> list[str]:
    errs: list[str] = []
    if args.lane not in LANES:
        errs.append(f"lane must be one of {sorted(LANES)}")
    if not SLUG_RE.match(args.slug or ""):
        errs.append("slug must match ^[a-z0-9][a-z0-9-]{0,79}$")
    if not (args.title or "").strip():
        errs.append("title required")
    if not content.strip():
        errs.append("content file is empty")
    if args.domain not in canonical_domains():
        errs.append(f"domain {args.domain!r} is not canonical — "
                    "pick an existing one from ssot.cms.yml")
    if not (args.summary or "").strip():
        errs.append("summary required (one-line brief for the CMS catalog)")
    if args.public and not (args.source or "").strip():
        errs.append("--public requires --source (static publish gate)")
    if args.lang not in ("en", "th"):
        errs.append("lang must be en or th")
    return errs


def build_meta(args: argparse.Namespace, content: str, now: dt.datetime,
               previous: dict | None = None) -> dict:
    meta: dict[str, list[str]] = {
        "kind": ["report"],
        "domain": [args.domain],
        "status": ["active"],
        "slug": [args.slug],
        "title": [args.title.strip()],
        "format": ["markdown"],
        "updated": [now.isoformat(timespec="seconds")],
        "summary": [args.summary.strip()],
        "fresh_for": [args.fresh_for],
        "written_by": [args.written_by],
        "card": [args.card],
    }
    if args.source:
        meta["sources"] = [s.strip() for s in args.source.split(",") if s.strip()]
    if args.public:
        meta["public"] = ["true"]
    if previous:
        meta["supersedes"] = [args.slug]
        prior = str(previous.get("contentMd") or previous.get("content_md") or "")
        digest = hashlib.sha256(prior.encode()).hexdigest()[:12]
        timeline = [x for x in (previous.get("meta") or {}).get("timeline", [])
                    if isinstance(x, str)]
        timeline.append(f"{now:%Y-%m-%dT%H:%M} overwritten by "
                        f"{args.written_by}; prior sha256:{digest}")
        meta["timeline"] = timeline[-40:]
    return meta


def payload(args: argparse.Namespace, content: str, now: dt.datetime,
            previous: dict | None = None) -> dict:
    return {
        "collection": LANES[args.lane],
        "key": args.slug,
        "lang": args.lang,
        "contentMd": content,
        "meta": build_meta(args, content, now, previous),
    }


def write(args: argparse.Namespace, content: str) -> dict:
    mddb = args.mddb.rstrip("/")
    collection = LANES[args.lane]
    now = dt.datetime.now(dt.timezone.utc)
    previous = get_page(mddb, collection, args.slug, args.lang)
    if previous and not args.overwrite:
        raise SystemExit(
            f"{collection}/{args.slug} ({args.lang}) already exists — "
            "pass --overwrite to replace it")
    body = payload(args, content, now, previous)
    _post(mddb, "add", body)

    written = get_page(mddb, collection, args.slug, args.lang)
    if not written:
        raise RuntimeError("post-write verification failed: page not readable")
    stored = str(written.get("contentMd") or written.get("content_md") or "")
    if stored.strip() != content.strip():
        raise RuntimeError(
            "post-write verification failed: content differs (did the "
            "writer send contentMd?)")

    indexed = True
    if not args.no_index:
        indexed = cms_index.regen_reports_index(
            mddb, args.written_by, collection=collection, instance=args.lane)
    return {"page": f"{collection}/{args.slug} ({args.lang})",
            "verified": True, "indexed": bool(indexed),
            "bytes": len(content), "previous": bool(previous)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lane", required=True, help="kk | kk-dev | tony | mn")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--content-file", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--card", default="", help="board card id for the audit trail")
    ap.add_argument("--source", default="", help="comma-separated source refs")
    ap.add_argument("--fresh-for", default="7d")
    ap.add_argument("--lang", default="en", choices=("en", "th"))
    ap.add_argument("--written-by", default="cms-report-add.py")
    ap.add_argument("--public", action="store_true",
                    help="opt into the static site publish gate")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--no-index", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-write default; same as omitting --apply")
    ap.add_argument("--mddb", default=__import__("os").environ.get(
        "MDDB_CMS_URL", DEFAULT_CMS))
    args = ap.parse_args()

    content = Path(args.content_file).read_text()
    errs = validate(args, content)
    if errs:
        for err in errs:
            print(f"REFUSED: {err}", file=sys.stderr)
        return 2
    if args.dry_run or not args.apply:
        print(f"DRY RUN — no write. would write to {LANES[args.lane]}/"
              f"{args.slug} ({args.lang})")
        print(json.dumps(payload(args, content, dt.datetime.now(
            dt.timezone.utc)), indent=2, ensure_ascii=False))
        return 0
    result = write(args, content)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
