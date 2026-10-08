#!/usr/bin/env python3
"""cms-ia-normalize.py — one-shot IA normalization for ada-cms-pages
(card cms-ia-reorg, 2026-10-08).

Applies the naming/grouping standard in
docs/ssot/infrastructure/ssot.cms.yml to the live collection:

  1. domain backfill — DOMAIN_MAP gives every untagged page its domain;
     DOMAIN_RULES are the prefix fallback for keys not in the map.
  2. domain aliases — infrastructure -> infra, ada-architecture -> ada,
     uncategorized -> '' (pages in it get DOMAIN_MAP values instead).
  3. status fixes — missing/'published' -> active. 'stub' stays (it is a
     real state: placeholder pages). Dead states never touched.
  4. kind fixes — missing -> page; 'benchmark' -> report (kind=benchmark
     is invisible to cms_read list/search and reports-index, which only
     accept page|report).
  5. supersede/redirect — SUPERSEDE maps dead-twin keys to their
     canonical page (status=superseded + superseded_by + timeline line).
     Content is left alone — superseded docs are the history.

Usage:
    cms-ia-normalize.py             # dry-run — print planned changes
    cms-ia-normalize.py --apply     # write to MDDB
    cms-ia-normalize.py --key cam-dohweb-bang-pu-sukhumvit-out --apply

Env:
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
DEAD_STATUS = {"superseded", "archived", "retracted", "expired"}
# Dead twins -> canonical page. dohweb cams: same PER_* DOH streams the
# 'traffic' registry zone already publishes — zones.yml trimmed so
# cam-wall-cms stops regenerating them. infrastructure-digest /
# uncategorized-digest retired by the domain merge + full tagging.
# gold-report is a th-only slug twin of gold-price-report.
SUPERSEDE = {
    "cam-dohweb-vibhavadi-don-mueang-in":
        "cam-traffic-doh-vibhavadi-rangsit-don-mueang-inbound",
    "cam-dohweb-min-buri-hwy304-in":
        "cam-traffic-doh-min-buri-bangkok-inbound-hwy-304",
    "cam-dohweb-bang-pu-sukhumvit-out":
        "cam-traffic-doh-bang-pu-sukhumvit-road-outbound",
    "cam-dohweb-hwy303-phra-samut-chedi-in":
        "cam-traffic-doh-hwy-303-ratsadon-burana-phra-samut-chedi-inbound",
    "infrastructure-digest": "infra-digest",
    "uncategorized-digest": "reports-index",
    "services-by-host-2026-09-30": "services-by-host",
    "gold-report": "gold-price-report",
}

DOMAIN_ALIASES = {
    "infrastructure": "infra",
    "ada-architecture": "ada",
    "uncategorized": None,   # bucket retired — DOMAIN_MAP/RULES reassign
}

# Domain per key for untagged (or alias-collapsed) pages. Explicit beats
# regex — the whole point of the reorg is that a human placed each page.
DOMAIN_MAP = {
    # ada — Ada's own system: voice, memory, tools, sessions, plans
    "ada-deep-research-assessment": "ada",
    "ada-deploy-pipeline": "ada",
    "ada-dev-lab-plan": "ada",
    "ada-dev-to-fix-casting-issue": "ada",
    "ada-embedding-system-assessment": "ada",
    "ada-programming-status": "ada",
    "ada-recall-architecture": "ada",
    "ada-session-health": "ada",
    "ada-tool-selection": "ada",
    "ada-tools-report": "ada",          # alias collapse ada-architecture
    "ada-decision-flow": "ada",         # was 'architecture' — it's Ada's
    "assessing-memory-options": "memory",
    "memory-audit": "memory",
    "memory-yml-proposal": "memory",
    "weaviate-report": "architecture",
    "orchestration-conflicts": "architecture",
    # bench — benchmarks, measurements, scenario suites
    "bench-jev": "bench",
    "bench-ping": "bench",
    "benchmark-casting": "bench",
    "benchmark-reports": "bench",
    "benchmark-system": "bench",
    "gemini-or-embedding-benchmark": "bench",
    "gev-screen-interaction-benchmark": "bench",
    "mddb-index-build-benchmark": "bench",
    "openjev-verdict-benchmark": "bench",
    "voice-latency-20261001": "bench",
    "colab-gpu-results": "bench",
    "lab-results": "bench",             # status-only fix too
    # cctv — non cam-* camera docs
    "camera-sources-2026-09-30": "cctv",
    "cctv-request-flow": "cctv",
    # chaba-core — chaba system design/plans
    "chaba-edge-plan": "chaba-core",
    "chaba-ha-plan": "chaba-core",
    "chaba-lab": "chaba-core",
    "chaba-project": "chaba-core",
    "chaba-systemwide-assessment": "chaba-core",
    # dev — devin/dev-tooling work reports
    "devin-job-report": "dev",
    "devin-job-report-fail": "dev",
    "devin-status-report-20261002": "dev",
    "document-search-report-20261002": "dev",
    "fix-vcast-controls": "dev",
    # docs — manuals, explainers, how-it-works
    "ada-chaba-devin-teamup": "docs",
    "cms-page-standard": "docs",
    "line-bot": "docs",
    "line-yomi": "docs",
    "yomi-vs-line-bot": "docs",
    # finance — market/gold reports
    "gold-price-report": "finance",
    "gold-report": "finance",           # superseded th twin
    "market-report": "finance",
    # flood — untagged flood pages
    "flood-report": "flood",
    "flood-report-nongdon-saraburi": "flood",
    # infra — hosts, migrations, capacity
    "host-verification-2026-09-30": "infra",
    "hosting-provider-assessment": "infra",
    "idc02-proposal": "infra",
    "mddb-follower-migration-plan": "infra",
    "migration-analysis-idc01": "infra",
    "storage-offload-report": "infra",
    "tony-omen-shutdown-assessment": "infra",
    "verified-routes": "infra",
    "services-by-host-2026-09-30": "infra",   # superseded, still tagged
    "tv-action-cast-browser-20261002": "infra",   # was 'infrastructure'
    "vms-wall-outage-20261001": "infra",          # was 'infrastructure'
    "infrastructure-digest": "infra",             # superseded twin
    # meta — the cms system itself
    "cms-audit-report": "meta",
    "digest-weekly": "meta",
    "uncategorized-digest": "meta",     # superseded bucket page
    # monitoring — watchtowers
    "monitoring-proposal": "monitoring",
    "power-trend": "monitoring",
    # news — feed/news pages
    "news-bangplee": "news",
    "news-headline": "news",
    "news-source-assessment": "news",
    "news-system": "news",
    "news-tabsai": "news",
    "news-thailand": "news",
    "news-world": "news",
    "news-flood": "flood",              # flood news belongs with flood
    # ops — incidents, audits, self-reports
    "attention-report": "ops",
    "auto-report": "ops",
    "bloat-report": "ops",
    "issue-voice-enrollment": "ops",
    "system-incident-report": "ops",
    "transcript-audit-2026-09-28": "ops",
    "transcript-audit-2026-09-29": "ops",
    "vcast-failure-report": "ops",
    # personal — notes for Tony/KK
    "emotion-behavior-report": "personal",
    "free-towing-bangphli": "personal",
    "free-towing-pattaya": "personal",
    "idea-summary": "personal",
    "my-words": "personal",
    "my-words-kk": "personal",
    "nut-benefits-summary": "personal",
    "nut-summary": "personal",
    "style-update-relative-time": "personal",
    "today-plan": "personal",
    "todo-list": "personal",
    "muizenberg-surf-song": "media",
    "tts-voice-catalog": "media",
    # policy — rules/standards enforced on agents
    "benchmark-standard": "policy",
    "document-audit-policy": "policy",
    # projects — project trackers
    "gev": "projects",
    "nest-portable-brains": "projects",
    # research — external assessments/explorations
    "assessing-obsidian-uxui": "research",
    "colab-assessment": "research",
    "deep-dive-analysis": "research",
    "gemini-deep-research": "research",
    "gesture-ui-options": "research",
    "jev-ai-assessment": "research",
    "jev-unsloth-finetune": "research",
    "neuralink-report": "research",
    "tiny-models-research": "research",
    # test — probes/demos
    "rich-demo": "test",
    "tv-plug-test-report": "test",
    # weather
    "weather-station-details": "weather",
}

# Prefix fallbacks for keys not in DOMAIN_MAP — mirrors ssot.cms.yml
# prefix_families. Used only when a doc has no domain at all.
DOMAIN_RULES = [
    (r"^camwall-|^cam-|^cctv-|^dvr-wall|^wall-", "cctv"),
    (r"^flood-", "flood"),
    (r"^news-", "news"),
    (r"^bench-|benchmark", "bench"),
    (r"^services-|^host-", "infra"),
    (r"-digest$", None),    # digests already carry their own domain
    (r"^ada-", "ada"),
    (r"^chaba-", "chaba-core"),
]


def _first(meta: dict, name: str) -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def _domain_for(key: str, cur: str) -> str:
    if cur:
        alias = DOMAIN_ALIASES.get(cur, cur)
        if alias:                       # mapped alias or unchanged
            return DOMAIN_MAP.get(key) or alias
        cur = ""                        # alias -> None: fall through
    if key in DOMAIN_MAP:
        return DOMAIN_MAP[key]
    for pat, dom in DOMAIN_RULES:
        if re.search(pat, key):
            return dom or cur
    return cur


def list_docs() -> list[dict]:
    docs, offset = [], 0
    while True:
        req = urllib.request.Request(
            f"{MDDB}/search",
            data=json.dumps({"collection": COLLECTION, "query": "",
                             "limit": 500, "offset": offset}).encode(),
            headers={"Content-Type": "application/json"})
        page = json.load(urllib.request.urlopen(req, timeout=60))
        if isinstance(page, dict):
            page = page.get("documents") or page.get("docs") or []
        docs += page
        if len(page) < 500:
            return docs
        offset += 500


def publish(doc: dict, meta: dict) -> None:
    req = urllib.request.Request(
        f"{MDDB}/add",
        data=json.dumps({"collection": COLLECTION, "key": doc["key"],
                         "lang": doc.get("lang") or "en",
                         "contentMd": doc.get("contentMd") or "",
                         "meta": meta}).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=120)


def plan(doc: dict, today: str) -> tuple[dict, list]:
    """-> (new_meta, [(field, old, new)]) — meta-only changes."""
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    key = doc.get("key") or ""
    changes = []

    def setf(name, new):
        old = _first(meta, name)
        if old != new:
            meta[name] = [new]
            changes.append((name, old or "∅", new))

    # supersede/redirect first — supersedes wins over everything else
    if key in SUPERSEDE and _first(meta, "status") not in DEAD_STATUS:
        setf("status", "superseded")
        setf("superseded_by", SUPERSEDE[key])
        setf("last_verified", today)
        tl = [x for x in meta.get("timeline", []) if isinstance(x, str)]
        tl.append(f"{today} superseded by {SUPERSEDE[key]} "
                  "(cms-ia-reorg dedup)")
        meta["timeline"] = tl[-40:]
        # still normalize domain below — dead twins stay findable by meta

    kind = _first(meta, "kind")
    if not kind:
        setf("kind", "page")
    elif kind == "benchmark":
        setf("kind", "report")

    status = _first(meta, "status")
    if key not in SUPERSEDE and status not in DEAD_STATUS:
        if not status or status == "published":
            setf("status", "active")

    dom = _first(meta, "domain")
    new_dom = _domain_for(key, dom)
    if new_dom and new_dom != dom:
        setf("domain", new_dom)
    elif not dom and not new_dom:
        changes.append(("domain", "∅", "!! UNMAPPED — needs a domain"))

    # page_role backfill (ssot.cms.yml nav.camera_subgroups) — the CMS
    # viewer sub-groups cameras on meta, not slugs. cam-wall-cms stamps
    # this on new writes; this covers pages already live.
    if _first(meta, "domain") == "cctv" and not _first(meta, "page_role"):
        if key == "cctv-walls" or key.startswith("cms-wall-index"):
            setf("page_role", "index")
        elif key == "dvr-wall" or key.startswith("camwall-") \
                or key.startswith("wall-"):
            setf("page_role", "wall")
        elif key.startswith("cam-"):
            setf("page_role", "cam")

    return meta, changes


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Normalize ada-cms-pages meta onto ssot.cms.yml")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--key", help="only this page key")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date().isoformat()
    docs = list_docs()
    if args.key:
        docs = [d for d in docs if d.get("key") == args.key]
    changed = skipped = 0
    unmapped = []
    for d in sorted(docs, key=lambda x: str(x.get("id"))):
        meta, changes = plan(d, today)
        if not changes:
            skipped += 1
            continue
        changed += 1
        print(f"{d['key']} [{d.get('lang') or 'en'}]")
        for f, old, new in changes:
            print(f"    {f:14} {old}  ->  {new}")
            if f == "domain" and new.startswith("!!"):
                unmapped.append(d["key"])
        if args.apply:
            publish(d, meta)
    verb = "applied" if args.apply else "planned"
    print(f"\n{changed} docs {verb}, {skipped} already conformant"
          + ("" if args.apply else " — re-run with --apply"))
    if unmapped:
        print("UNMAPPED keys needing a domain:", sorted(set(unmapped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
