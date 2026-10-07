#!/usr/bin/env python3
"""cms-report-reflect — mirror an ada-cms-pages report into the report graph.

Report-graph nodes whose producer is a CMS page (published by Ada, not by
a local generator) never emit meta.yml on their own — the page lives in
MDDB while the graph reads the served checkout. This reflector closes the
contract:

  1. fetch the page doc from MDDB (ada-cms-pages, key=<slug>)
  2. snapshot contentMd to reports/<slug>-<YYYY-MM-DD>.md when the
     content changed since the latest snapshot (append-only artifacts)
  3. write the node's meta.yml with generated_at = the page's own
     `updated` — staleness then measures the report's freshness, not
     when this reflector last ran
  4. report missing meta-contract fields (summary/domain/fresh_for/
     confidence) in meta.extra so gaps are visible, not silent

Run periodically (chaba-cms-reflect.timer); also run by hand after a
session publishes a report page.

Usage: cms-report-reflect.py --slug chaba-systemwide-assessment
                             --node systemwide-assessment
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import report as rlib  # noqa: E402
import yaml  # noqa: E402

MDDB = os.environ.get("MDDB_BASE_URL",
                      "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
META_FIELDS = ("summary", "domain", "fresh_for", "confidence")


def _post(path: str, payload: dict, timeout: int = 20):
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_page(slug: str) -> dict | None:
    docs = _post("/search", {"collection": COLLECTION, "limit": 500})
    if not isinstance(docs, list):
        return None
    for d in docs:
        if d.get("key") == slug:
            return d
    return None


def _meta_first(meta: dict, name: str) -> str:
    v = meta.get(name)
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")


def find_node(node_id: str) -> dict | None:
    reg = yaml.safe_load(
        (REPO / "docs/ssot/infrastructure/ssot.reports.yml").read_text())
    for n in reg.get("nodes", []):
        if n.get("id") == node_id:
            return n
    return None


def snapshot(content: str, outdir: Path, slug: str) -> str | None:
    """Write reports/<slug>-<date>.md when content differs from the newest
    snapshot. Returns the snapshot filename written, else None."""
    digest = hashlib.sha256(content.encode()).hexdigest()
    snaps = sorted(outdir.glob(f"{slug}-*.md"))
    for p in reversed(snaps):
        try:
            if hashlib.sha256(p.read_bytes()).hexdigest() == digest:
                return None
            break
        except OSError:
            continue
    name = f"{slug}-{datetime.now().astimezone().strftime('%Y-%m-%d')}.md"
    (outdir / name).write_text(content)
    return name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="ada-cms-pages key")
    ap.add_argument("--node", required=True, help="ssot.reports.yml node id")
    args = ap.parse_args()

    node = find_node(args.node)
    if not node:
        print(f"node {args.node!r} not in ssot.reports.yml", file=sys.stderr)
        return 2
    meta_path = REPO / (node.get("meta") or f"reports/meta.{args.node}.yml")
    outdir = REPO / (node.get("output") or "reports")
    outdir.mkdir(parents=True, exist_ok=True)
    gen_by = f"scripts/ada/cms-report-reflect.py --slug {args.slug}"
    sources = [f"mddb {COLLECTION}/{args.slug}"]

    try:
        doc = fetch_page(args.slug)
    except Exception as e:
        rlib.write_meta(meta_path, node=args.node,
                        layer=node.get("layer") or "L2-domain",
                        generated_by=gen_by, status="unreachable",
                        purpose=node.get("purpose"),
                        summary=f"mddb fetch failed: {e}", sources=sources,
                        children=node.get("children"))
        print(f"{args.node}: unreachable — {e}")
        return 0

    if not doc:
        rlib.write_meta(meta_path, node=args.node,
                        layer=node.get("layer") or "L2-domain",
                        generated_by=gen_by, status="missing",
                        purpose=node.get("purpose"),
                        summary=f"cms page {args.slug!r} not published",
                        sources=sources, children=node.get("children"))
        print(f"{args.node}: missing — no cms page {args.slug!r}")
        return 0

    meta = doc.get("meta") or {}
    content = doc.get("contentMd") or doc.get("content") or ""
    updated = _meta_first(meta, "updated")
    summary = _meta_first(meta, "summary")
    missing_fields = [f for f in META_FIELDS if not _meta_first(meta, f)]
    snap = snapshot(content, outdir, args.slug) if content else None

    rlib.write_meta(
        meta_path, node=args.node,
        layer=node.get("layer") or "L2-domain",
        generated_by=gen_by, status="ok",
        purpose=node.get("purpose"),
        summary=summary or f"cms page {args.slug} mirrored",
        sources=sources, children=node.get("children"),
        generated_at=updated or None,
        extra={
            "page_updated": updated,
            "confidence": _meta_first(meta, "confidence") or None,
            "reflected_at": rlib.now_iso(),
            "snapshot": snap,
            "missing_meta_fields": missing_fields or None,
        })
    print(f"{args.node}: ok — page updated {updated}"
          + (f", snapshot {snap}" if snap else "")
          + (f", missing meta fields {missing_fields}"
             if missing_fields else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
