#!/usr/bin/env python3
"""cms-publish-site.py — publish public CMS pages to the www.surf-thailand.com
static webroot on the idc02 edge.

Card: OPS-0474 (www-surf-thailand-com-tenant-sub-webs).
Reads an ada-cms-pages[-<tenant>] MDDB collection, selects docs carrying
meta.public (truthy: true/yes/1), renders minimal dark HTML, and writes:

  <out>/<tenant>/<key>.html          default lang (en, or the only lang)
  <out>/<tenant>/<key>.<lang>.html   other langs
  <out>/<tenant>/index.html          list of published pages

Publishing is per-member opt-in: the page owner sets meta.public via the
standard write path (cms_publish_page / cms meta edit). Nothing without the
flag leaves the tailnet.

Runs on idc02 (mddb reachable over tailnet; webroot is local). Stdlib only.

Usage:
  cms-publish-site.py --tenant kk-ha [--dry-run]
  cms-publish-site.py --tenant tony-ha
  cms-publish-site.py --all

Env:
  MDDB_BASE_URL   default http://100.102.134.91:11023/v1
  CMS_SITE_ROOT   default ~/.config/containers/caddy/data/www (idc02 edge
                  caddy-edge webroot, mounted as /data,Z/www in-container)
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MDDB = os.environ.get("MDDB_BASE_URL",
                      "http://100.102.134.91:11023/v1").rstrip("/")
SITE_ROOT = Path(os.environ.get(
    "CMS_SITE_ROOT",
    os.path.expanduser("~/.config/containers/caddy/data/www")))
TENANTS = {"kk-ha": "ada-cms-pages-kk",
           "tony-ha": "ada-cms-pages"}

CSS = """\
html,body{margin:0;background:#0b0b0d;color:#e8e8ea;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.65}
main{max-width:52rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
h1{font-size:1.6rem;border-bottom:1px solid #2a2a2e;padding-bottom:.6rem}
h2{font-size:1.2rem;margin-top:2rem}
h3{font-size:1.05rem;margin-top:1.5rem}
a{color:#7db4ff}
code{background:#1a1a1f;padding:.1em .35em;border-radius:4px;font-size:.92em}
pre{background:#141418;padding:1rem;border-radius:8px;overflow-x:auto}
pre code{background:none;padding:0}
ul,ol{padding-left:1.4rem}
li{margin:.3rem 0}
.meta{color:#8a8a92;font-size:.85rem;margin-top:.4rem}
nav.pages{margin-top:2rem}
nav.pages a{display:block;padding:.6rem .2rem;border-bottom:1px solid #1c1c20;text-decoration:none}
nav.pages a:hover{color:#fff}
blockquote{border-left:3px solid #2a2a2e;margin-left:0;padding-left:1rem;color:#b8b8be}
table{border-collapse:collapse}td,th{border:1px solid #2a2a2e;padding:.35em .7em}
"""


def _post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _meta1(meta: dict, name: str) -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def is_public(doc: dict) -> bool:
    return _meta1(doc.get("meta"), "public").lower() in ("true", "yes", "1")


def md_to_html(md: str) -> str:
    """Minimal markdown renderer — headings, lists, code, inline styles.
    The PWA viewer remains the rich surface; this is the static public lane."""
    out, in_code, in_list, para = [], False, None, []

    def flush_para():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    def inline(t: str) -> str:
        t = html.escape(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
        t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   r'<a href="\2" rel="noopener">\1</a>', t)
        return t

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            flush_para(); flush_list()
            if not in_code:
                out.append("<pre><code>"); in_code = True
            else:
                out.append("</code></pre>"); in_code = False
            continue
        if in_code:
            out.append(html.escape(line) + "\n")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush_para(); flush_list()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)", line)
        if m:
            flush_para()
            if in_list != "ul":
                flush_list(); out.append("<ul>"); in_list = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if m:
            flush_para()
            if in_list != "ol":
                flush_list(); out.append("<ol>"); in_list = "ol"
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if re.match(r"^>\s?(.*)", line):
            flush_para(); flush_list()
            out.append(f"<blockquote>{inline(re.match(r'^>\\s?(.*)', line).group(1))}</blockquote>")
            continue
        if not line.strip():
            flush_para(); flush_list()
            continue
        flush_list()
        para.append(line.strip())
    flush_para(); flush_list()
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def page_html(title: str, body: str, sub: str = "") -> str:
    subline = f'<div class="meta">{html.escape(sub)}</div>' if sub else ""
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><main><h1>{html.escape(title)}</h1>{subline}{body}</main></body></html>")


def publish(tenant: str, collection: str, dry: bool = False) -> dict:
    docs = _post("search", {"collection": collection, "limit": 1000})
    if not isinstance(docs, list):
        docs = docs.get("result", docs.get("docs", []))
    public = [d for d in docs if is_public(d)]
    # default lang page = en if present else the only lang variant
    by_key: dict[str, list] = {}
    for d in public:
        by_key.setdefault(d.get("key", ""), []).append(d)

    outdir = SITE_ROOT / tenant
    written, removed = [], []
    files: dict[str, str] = {}
    for key, variants in sorted(by_key.items()):
        langs = sorted({d.get("lang", "en") for d in variants})
        for d in variants:
            lang = d.get("lang", "en")
            title = _meta1(d.get("meta"), "title") or key
            sub = f"{tenant} · {lang}" + (
                f" · verified {_meta1(d.get('meta'), 'last_verified')}"
                if _meta1(d.get("meta"), "last_verified") else "")
            name = f"{key}.html" if lang == "en" or len(langs) == 1 \
                else f"{key}.{lang}.html"
            files[name] = page_html(title, md_to_html(d.get("contentMd", "")), sub)

    links = []
    for key, variants in sorted(by_key.items()):
        langs = sorted({d.get("lang", "en") for d in variants})
        title = _meta1(variants[0].get("meta"), "title") or key
        base = f"{key}.html" if "en" in langs or len(langs) == 1 \
            else f"{key}.{langs[0]}.html"
        extra = "".join(
            f' · <a href="{key}.{l}.html">{l}</a>'
            for l in langs if f"{key}.{l}.html" != base)
        links.append(f'<a href="{base}">{html.escape(title)}</a>{extra}')
    files["index.html"] = page_html(
        f"{tenant} — published pages",
        '<nav class="pages">' + "".join(links) + "</nav>" or "<p>No pages yet.</p>",
        f"{len(by_key)} page(s)")

    if not dry:
        outdir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            p = outdir / name
            if not p.exists() or p.read_text() != content:
                p.write_text(content)
                written.append(name)
        for stale in outdir.glob("*.html"):
            if stale.name not in files:
                stale.unlink()
                removed.append(stale.name)
    return {"tenant": tenant, "collection": collection,
            "public_pages": len(by_key), "files": len(files),
            "written": sorted(written), "removed": sorted(removed)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", choices=sorted(TENANTS))
    ap.add_argument("--collection", help="override mddb collection")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tenants = TENANTS if a.all else {a.tenant: a.collection or TENANTS[a.tenant]}
    for tenant, coll in tenants.items():
        r = publish(tenant, coll, dry=a.dry_run)
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
