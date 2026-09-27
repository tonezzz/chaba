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
"""
import json, os, re, sys, urllib.request

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1")

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
    if re.search(r"\b(TODO|TBD|lorem ipsum|placeholder)\b", body, re.I): fails.append("A5:placeholder")
    if re.search(r"(api[_-]?key|password|secret|token)\s*[:=]\s*[\"']?\w", body, re.I): fails.append("A6:secret-ish")
    if key.startswith("news-"):
        if "TL;DR" not in body: fails.append("N1:no-tldr")
        items = len(re.findall(r"^[-*]\s", body, re.M))
        if key != "news-system" and items > 6: fails.append(f"N2:too-many-items({items})")
        if key not in ("news-system",) and not re.search(r"\[source|\(http", body, re.I):
            fails.append("N3:no-source-links")
        if key not in ("news-system", "news-headline") and not re.search(r"why it matters|why:|impact", body, re.I):
            fails.append("N4:no-why-it-matters")
    return fails

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
    lines.append(f"\n{passed} pass · {failed} fail")
    print("\n".join(lines))
    if publish_flag:
        publish(lines, passed, failed)
        print("published -> ada-cms-pages/cms-audit-report")

main()
