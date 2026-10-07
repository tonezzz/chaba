#!/usr/bin/env python3
"""report-ai-edge.py — weekly 'ai-edge' leaf report: edge/micro-AI feed.

Continuous-education feed for the Nest track: deterministic pulls only
(no LLM — matches the zero-LLM detection standard; a missing source
degrades a section, never kills the report).

Sources:
  arXiv      export.arxiv.org/api/query — cs.LG/cs.CL × Nest keywords
  HF papers  huggingface.co/api/daily_papers — last 7d, top upvotes
  GitHub     api.github.com/search/repositories — new trending repos

Writes (per ssot.reports.yml + ssot.apps.cms-reports.yml leaf contract):
  reports/ai-edge/AI-EDGE-<yyyymmdd>.md      dated artifact
  reports/meta.ai-edge.yml                 node meta
  ~/var/chaba/reports/timeline.jsonl       appended event
  ada-cms-pages/ai-edge-report             CMS page (kind:report)

Usage: report-ai-edge.py [--print] [--days N]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

NODE = "ai-edge"
LAYER = "L2-domain"
OUT_DIR = REPO / "reports" / "ai-edge"
META = REPO / "reports" / "meta.ai-edge.yml"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
CMS_SLUG = "ai-edge-report"

# Nest watchlist — keywords that make a paper/repo relevant to us
KEYWORDS = [
    "tinyml", "tiny ml", "edge device", "on-device", "federated",
    "distillation", "quantiz", "pruning", "microcontroller", "mamba",
    "state space", "mixture of expert", "small language model",
    "efficient inference", "wasm", "neural architecture search",
    "neuroevolution", "sparse", "low-power", "embedded",
]
GH_TOPICS = ["tinyml", "federated-learning", "edge-ai", "onnx",
             "llama.cpp", "microcontrollers"]

_UA = {"User-Agent": "chaba-report-ai-edge/1.0"}


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


# --------------------------------------------------------------- sources

def fetch_arxiv(days: int) -> list[dict]:
    """Recent cs.LG/cs.CL/cs.RO hits on Nest keywords (AND within abstract)."""
    terms = " OR ".join(f'abs:"{k}"' for k in
                        ("tinyml", "on-device", "federated learning",
                         "quantization", "knowledge distillation",
                         "microcontroller", "state space model",
                         "mixture of experts"))
    q = urllib.parse.urlencode({
        "search_query":
            f"(cat:cs.LG OR cat:cs.CL) AND ({terms})",
        "sortBy": "submittedDate", "sortOrder": "descending",
        "max_results": "40"})
    try:
        xml = _get(f"http://export.arxiv.org/api/query?{q}")
    except Exception as e:
        return [{"error": f"arxiv: {e}"}]
    ns = {"a": "http://www.w3.org/2005/Atom"}
    cutoff = datetime.datetime.now(datetime.timezone.utc) - \
        datetime.timedelta(days=days + 3)  # arxiv lag
    out = []
    for e in ET.fromstring(xml).findall("a:entry", ns):
        pub = (e.findtext("a:published", "", ns) or "")[:10]
        title = " ".join((e.findtext("a:title", "", ns) or "").split())
        link = e.findtext("a:id", "", ns) or ""
        try:
            dt = datetime.datetime.fromisoformat(pub).replace(
                tzinfo=datetime.timezone.utc)
            if dt < cutoff:
                continue
        except ValueError:
            pass
        hits = [k for k in KEYWORDS if k in title.lower()]
        out.append({"title": title, "link": link, "date": pub,
                    "hits": hits})
    return out[:15]


def fetch_hf_papers(days: int) -> list[dict]:
    """HF daily papers, last N days, ranked by upvotes."""
    out = []
    today = datetime.date.today()
    for i in range(days):
        d = (today - datetime.timedelta(days=i)).isoformat()
        try:
            data = json.loads(_get(
                f"https://huggingface.co/api/daily_papers?date={d}"))
        except Exception:
            continue
        for p in data or []:
            pap = p.get("paper") or {}
            title = pap.get("title") or ""
            hits = [k for k in KEYWORDS if k in
                    (title + " " + (pap.get("summary") or "")[:400]).lower()]
            if not hits:
                continue
            out.append({"title": title,
                        "link": f"https://huggingface.co/papers/{pap.get('id','')}",
                        "date": d, "hits": hits[:4],
                        "up": p.get("upvotes") or 0})
    out.sort(key=lambda x: -x["up"])
    return out[:10]


def fetch_github(days: int) -> list[dict]:
    """New repos in Nest topics, created in window, by stars."""
    since = (datetime.date.today() -
             datetime.timedelta(days=days)).isoformat()
    seen, out = set(), []
    for topic in GH_TOPICS:
        q = urllib.parse.quote(f"topic:{topic} created:>{since}")
        try:
            data = json.loads(_get(
                f"https://api.github.com/search/repositories?q={q}"
                "&sort=stars&order=desc&per_page=5"))
        except Exception:
            continue
        for r in data.get("items", []):
            if r["full_name"] in seen:
                continue
            seen.add(r["full_name"])
            out.append({"title": r["full_name"],
                        "link": r["html_url"], "stars": r["stargazers_count"],
                        "desc": (r.get("description") or "")[:140],
                        "topic": topic})
    out.sort(key=lambda x: -x["stars"])
    return out[:10]


# ---------------------------------------------------------------- render

def render(days: int, papers, hf, repos) -> tuple[str, str]:
    now = now_iso()
    lines = [
        "# AI Edge Feed — Nest track",
        f"**Updated:** {now[:16]} · window {days}d · sources: arXiv / HF daily / GitHub",
        "",
        "<!-- ai-edge:auto -->",
    ]
    sec = [("Papers — arXiv (Nest keywords)", papers),
           ("Papers — HF daily (top upvoted, keyword hit)", hf),
           ("New repos", repos)]
    for title, items in sec:
        lines += [f"## {title}", ""]
        if not items:
            lines += ["_source unavailable or no hits_", ""]
            continue
        if items and "error" in items[0]:
            lines += [f"_unavailable: {items[0]['error']}_", ""]
            continue
        for it in items:
            tail = ""
            if it.get("hits"):
                tail = f" `{','.join(it['hits'][:3])}`"
            if it.get("stars"):
                tail = f" ★{it['stars']} · {it.get('topic','')}"
            if it.get("up"):
                tail += f" ↑{it['up']}"
            desc = f" — {it['desc']}" if it.get("desc") else ""
            lines.append(f"- [{it['title']}]({it['link']}){tail}{desc}")
        lines.append("")
    lines += ["<!-- /ai-edge:auto -->", "",
              "_Generated file — do not hand-edit._", ""]
    md = "\n".join(lines)
    n = len([x for s in sec for x in s[1] if "error" not in x])
    return md, f"ai-edge: {n} items ({len(papers)} arXiv/{len(hf)} HF/{len(repos)} repos)"


# ---------------------------------------------------------------- publish

def _mddb_post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def publish_cms(md: str, summary: str) -> bool:
    """Upsert ada-cms-pages/ai-edge-report — leaf report per
    ssot.apps.cms-reports.yml (report_role=leaf, generated_by, sources)."""
    now = now_iso()
    meta = {
        "kind": ["report"], "report_role": ["leaf"], "slug": [CMS_SLUG],
        "title": [f"AI Edge Feed — {now[:10]}"],
        "format": ["markdown"], "lang": ["en"],
        "bank": ["cms"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "subject": [CMS_SLUG], "attribute": ["page"],
        "updated": [now], "last_verified": [now[:10]],
        "domain": ["research"], "summary": [summary[:240]],
        "fresh_for": ["7d"], "confidence": ["high"],
        "generated_by": ["python3 scripts/report-ai-edge.py"],
        "sources": ["export.arxiv.org", "huggingface.co/api/daily_papers",
                    "api.github.com/search/repositories"],
        "written_by": ["report-ai-edge.py"],
        "links": ["reports-index"],
        "timeline": [f"{now[:16]} weekly edition published"],
    }
    _mddb_post("add", {"collection": "ada-cms-pages", "key": CMS_SLUG,
                       "lang": "en", "contentMd": md, "meta": meta},
               timeout=60)
    try:
        from lib.cms_index import regen_reports_index
        regen_reports_index(MDDB, written_by="report-ai-edge.py")
    except Exception as e:
        print(f"warn: reports-index regen failed ({e})", file=sys.stderr)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="print_only", action="store_true")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--no-cms", action="store_true")
    ap.add_argument("--output-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--meta", type=Path, default=META)
    args = ap.parse_args()

    papers = fetch_arxiv(args.days)
    hf = fetch_hf_papers(args.days)
    repos = fetch_github(args.days)
    md, summary = render(args.days, papers, hf, repos)

    if args.print_only:
        print(md)
        print(f"---\nsummary={summary}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    artifact = args.output_dir / f"AI-EDGE-{datetime.date.today():%Y%m%d}.md"
    artifact.write_text(md, encoding="utf-8")

    write_meta(args.meta, node=NODE, layer=LAYER,
               generated_by="python3 scripts/report-ai-edge.py",
               purpose="Weekly edge/micro-AI feed — continuous education "
                       "for the Chaba Nest track",
               status="ok", summary=summary,
               sources=["export.arxiv.org", "huggingface.co",
                        "api.github.com"],
               children=[],
               extra={"window_days": args.days,
                      "items": summary})
    append_timeline(NODE, LAYER, "ok", summary, ref=artifact)

    if not args.no_cms:
        try:
            publish_cms(md, summary)
        except Exception as e:
            print(f"warn: CMS publish failed ({e})", file=sys.stderr)
    print(f"ai-edge: {summary} -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
