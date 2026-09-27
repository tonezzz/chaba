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

def main():
    pages = get_pages()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    passed = failed = 0
    for d in sorted(pages, key=lambda x: x["key"]):
        if only and not d["key"].startswith(only): continue
        fails = audit(d)
        if fails:
            failed += 1; print(f"FAIL {d['key']:42} {', '.join(fails)}")
        else:
            passed += 1; print(f"pass {d['key']:42} {len(d.get('contentMd') or '')}c")
    print(f"\n{passed} pass · {failed} fail")

main()
