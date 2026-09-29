#!/usr/bin/env python3
"""CMS page audit — mechanical quality gate for ada-cms-pages.

Rules (docs-as-code adapted):
  A1 non-empty body (>200c)
  A2 meta complete: slug,title,format,updated,kind=page
  A3 H1 present and matches title-ish
  A4 markdown structure: at least one heading or list
  A5 no placeholder markers (TODO/TBD/lorem/placeholder/draft)
  A6 no secrets (token/password/key= patterns)
  N* news-* pages: TL;DR line, <=6 items, source links, "why it matters"
  C* consolidation/obsolete (warnings, not failures):
    C1 near-duplicate slug pairs (>=70% token overlap) — merge candidates
    C2 stale living page: `updated` older than STALE_DAYS
  S* memory-schema conformance (warnings, not failures):
    S1 doc missing schema fields — run scripts/ada/cms-normalize-meta.py
       (fields: bank, scope, status, source, written_by, subject,
        attribute, valid_from, last_verified)
"""
import datetime, json, os, re, sys, urllib.request

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1")
STALE_DAYS = int(os.environ.get("CMS_AUDIT_STALE_DAYS", "14"))
# Living pages exempt from C2 staleness — point-in-time reports are
# SUPPOSED to be dated. Opt out by keeping a -report/-assessment/-proposal
# suffix, or add the slug here.
REPORT_SLUG_RE = re.compile(r"(report|assessment|proposal|analysis|review|incident|demo)$")
# Memory-schema fields every page should carry after cms-normalize-meta.py.
SCHEMA_FIELDS = ("bank", "scope", "status", "source", "written_by",
                 "subject", "attribute", "valid_from", "last_verified")

def get_pages():
    req = urllib.request.Request(f"{MDDB}/search",
        data=json.dumps({"collection": "ada-cms-pages", "filter_meta": {"kind": ["page"]}, "limit": 200}).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))

def audit(doc):
    key = doc["key"]; body = doc.get("contentMd") or ""
    meta = doc.get("meta") or {}
    fails = []
    if len(body.strip()) < 200: fails.append("A1:empty-or-thin")
    for f in ("slug", "title", "format", "updated"):
        if not meta.get(f): fails.append(f"A2:missing-{f}")
    if (meta.get("kind") or [""])[0] != "page": fails.append("A2:kind!=page")
    h1 = re.search(r"^#\s+(.+)$", body, re.M)
    if not h1: fails.append("A3:no-h1")
    else:
        title = (meta.get("title") or [""])[0].lower()
        words = [w for w in re.findall(r"[a-z]+", title) if len(w) > 3]
        if words and not any(w in h1.group(1).lower() for w in words): fails.append("A3:h1-title-mismatch")
    if not re.search(r"^(#{1,3}\s|[-*]\s)", body, re.M): fails.append("A4:no-structure")
    # A5 is skipped on the audit's own report — its body lists rule names
    # like "A5:placeholder" verbatim and would fail itself every run.
    # TODO/TBD stay case-sensitive (uppercase marker convention) so a page
    # titled "Todo List" doesn't flag itself; lorem/placeholder insensitive.
    if key != "cms-audit-report" and re.search(
            r"\b(?:TODO|TBD)\b|(?i:lorem ipsum|placeholder)", body): fails.append("A5:placeholder")
    if re.search(r"(api[_-]?key|password|secret|token)\s*[:=]\s*[\"']?\w", body, re.I): fails.append("A6:secret-ish")
    # N-rules apply to news-* digests only. Pages normalized by
    # cms-normalize-meta.py carry attribute — a news-* slug classed as
    # e.g. attribute=assessment (news-source-assessment) is exempt.
    attr = (meta.get("attribute") or [""])[0]
    if key.startswith("news-") and attr in ("", "news"):
        if "TL;DR" not in body: fails.append("N1:no-tldr")
        items = len(re.findall(r"^[-*]\s", body, re.M))
        if key != "news-system" and items > 6: fails.append(f"N2:too-many-items({items})")
        if key not in ("news-system",) and not re.search(r"\[source|\(http", body, re.I):
            fails.append("N3:no-source-links")
        if key not in ("news-system", "news-headline") and not re.search(r"why it matters|why:|impact", body, re.I):
            fails.append("N4:no-why-it-matters")
    return fails


def slug_tokens(slug: str) -> set[str]:
    return {t for t in re.split(r"[-_]+", slug.lower()) if len(t) > 2}


def consolidation_warnings(docs: list[dict]) -> list[str]:
    """C-rules — warnings, never failures.

    C1: near-duplicate slug pairs — >=70% token overlap suggests two
        pages covering the same subject (merge or supersede one).
    C2: living page whose `updated` is older than STALE_DAYS and is not
        a point-in-time report slug — obsolete content likely.
    """
    warns: list[str] = []
    today = datetime.date.today()
    docs_by_key = {d["key"]: d for d in docs}
    toks = {d["key"]: slug_tokens(d["key"]) for d in docs}
    keys = sorted(toks)
    for i, key in enumerate(keys):
        for other in keys[i + 1:]:
            a, b = toks[key], toks[other]
            if not a or not b:
                continue
            overlap = len(a & b) / len(a | b)
            if overlap >= 0.7:
                warns.append(
                    f"C1 duplicate-ish: {key} ~ {other} ({overlap:.0%} token overlap)")
        meta = docs_by_key[key].get("meta") or {}
        upd = (meta.get("updated") or [""])[0][:10]
        if upd and not REPORT_SLUG_RE.search(key):
            try:
                age = (today - datetime.date.fromisoformat(upd)).days
                if age > STALE_DAYS:
                    warns.append(f"C2 stale {key}: last updated {upd} ({age}d ago)")
            except ValueError:
                pass
    return warns


def schema_warnings(docs: list[dict]) -> list[str]:
    """S-rules — memory-schema conformance, warnings only."""
    warns: list[str] = []
    for d in sorted(docs, key=lambda x: x["id"]):
        meta = d.get("meta") or {}
        missing = [f for f in SCHEMA_FIELDS if not meta.get(f)]
        if missing:
            warns.append(f"S1 {d['id']}: missing schema meta {', '.join(missing)}")
    return warns

def publish(lines: list[str], passed: int, failed: int) -> None:
    """Upsert results to ada-cms-pages/cms-audit-report."""
    import datetime
    body = ("# CMS audit\n\nRun " +
            datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds") +
            f" — {passed} pass, {failed} fail\n\n```\n" + "\n".join(lines) + "\n```\n")
    payload = {"collection": "ada-cms-pages", "key": "cms-audit-report",
               "lang": "en", "contentMd": body,
               "meta": {"kind": ["page"], "slug": ["cms-audit-report"],
                        "title": ["CMS Audit Report"], "format": ["markdown"],
                        "updated": [datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")],
                        "instance": ["cms-audit"]}}
    req = urllib.request.Request(f"{MDDB}/add",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30)


def main():
    publish_flag = "--publish" in sys.argv
    only = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
    pages = get_pages()
    lines, passed, failed = [], 0, 0
    for d in sorted(pages, key=lambda x: x["key"]):
        if only and not d["key"].startswith(only): continue
        fails = audit(d)
        if fails:
            failed += 1; lines.append(f"FAIL {d['key']:42} {', '.join(fails)}")
        else:
            passed += 1; lines.append(f"pass {d['key']:42} {len(d.get('contentMd') or '')}c")
    warns = [] if only else consolidation_warnings(pages) + schema_warnings(pages)
    lines.append(f"\n{passed} pass · {failed} fail · {len(warns)} warnings")
    if warns:
        lines.append("\n## Consolidation / obsolete (warnings)")
        lines.extend(warns)
    print("\n".join(lines))
    if publish_flag:
        publish(lines, passed, failed)
        print("published -> ada-cms-pages/cms-audit-report")

main()
